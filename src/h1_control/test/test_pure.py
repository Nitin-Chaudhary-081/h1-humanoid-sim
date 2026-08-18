"""Pure-logic unit tests for h1_control (no ROS imports).

Run: PYTHONPATH=src python3 -m pytest test/ -q   (from the package root)
"""

import os
from pathlib import Path

import numpy as np
import pytest

from h1_control.estop import EstopGate
from h1_control.motion_player import (JointMap, MotionReplay, SineGait,
                                      make_motion_player, LOCO_MUJOCO_KEYS)
from h1_control.stand import MAX_POS, MIN_POS, StandController

PKG_ROOT = Path(__file__).resolve().parents[1]
STAND_YAML = PKG_ROOT / "config" / "stand.yaml"
JOINT_MAP_YAML = PKG_ROOT / "config" / "joint_map.yaml"
NPZ_PATH = PKG_ROOT / "data" / "walk.npz"

N_JOINTS = 17  # frozen contract: 17 joints from stand.yaml


# ---------------------------------------------------------------- stand
class TestStand:
    def test_yaml_has_17_joints(self):
        pose = StandController.from_yaml(str(STAND_YAML)).target_pose()
        assert len(pose) == N_JOINTS

    def test_target_pose_roundtrip(self):
        pose = StandController.from_yaml(str(STAND_YAML)).target_pose()
        raw = dict(pose)
        assert StandController(raw).target_pose() == pose

    def test_clamps_above_max(self):
        sc = StandController({"a": 5.0})
        assert sc.target_pose()["a"] == MAX_POS

    def test_clamps_below_min(self):
        sc = StandController({"a": -9.0})
        assert sc.target_pose()["a"] == MIN_POS

    def test_rejects_nan(self):
        with pytest.raises(ValueError):
            StandController({"a": float("nan")})

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            StandController({})

    def test_std_pose_within_bounds(self):
        for v in StandController.from_yaml(str(STAND_YAML)).target_pose().values():
            assert MIN_POS <= v <= MAX_POS


# ------------------------------------------------------------ joint map
class TestJointMap:
    @pytest.fixture(scope="class")
    def jm(self):
        return JointMap.from_yaml(str(JOINT_MAP_YAML),
                                  target_joints=StandController.from_yaml(
                                      str(STAND_YAML)).joints)

    def test_map_keys_are_valid_loco_keys(self):
        jm = JointMap.from_yaml(str(JOINT_MAP_YAML))
        assert set(jm.mapping.keys()) <= set(LOCO_MUJOCO_KEYS)
        # 15 of the 19 DOFs mapped; shx/shz (4) intentionally unmapped
        assert len(jm.mapping) == 15

    def test_complete_pose_covers_17_joints(self, jm):
        pose = jm.apply(dict.fromkeys(LOCO_MUJOCO_KEYS, 0.3))
        assert len(pose) == N_JOINTS

    def test_unmapped_keys_do_not_leak(self, jm):
        # shx/shz (shoulder roll/yaw) are not in the map; those heinz joints
        # are NOT part of the 17 commanded joints -> their value vanishes
        vals = dict.fromkeys(LOCO_MUJOCO_KEYS, 0.0)
        vals["l_arm_shx"] = 0.7
        vals["r_arm_shx"] = -0.7
        pose = jm.apply(vals)
        assert set(pose.keys()) == set(jm.targets)
        assert "left_shoulder_roll_joint" not in pose
        # and every commanded joint is present (zero for unmapped)
        assert len([v for v in pose.values() if v == 0.0]) >= 2

    def test_mapped_value_passes_through(self, jm):
        vals = dict.fromkeys(LOCO_MUJOCO_KEYS, 0.0)
        vals["hip_flexion_l"] = 0.4
        assert jm.apply(vals)["left_hip_pitch_joint"] == pytest.approx(0.4)

    def test_leg_axis_columns_match_config(self, jm):
        # npz col order (joint_names[1:]) must line up with LOCO_MUJOCO_KEYS
        assert LOCO_MUJOCO_KEYS[3] == "knee_angle_l"
        assert jm.mapping["knee_angle_l"] == "left_knee_joint"
        assert jm.mapping["back_bkz"] == "torso_joint"

    def test_unknown_target_rejected(self):
        with pytest.raises(ValueError):
            JointMap({"a": "nope_joint"}, target_joints=("x",))

    def test_zero_pose_complete(self, jm):
        assert len(jm.zero_pose()) == N_JOINTS
        assert all(v == 0.0 for v in jm.zero_pose().values())


# -------------------------------------------------------- motion replay
@pytest.fixture(scope="module")
def jm():
    return JointMap.from_yaml(str(JOINT_MAP_YAML),
                              target_joints=StandController.from_yaml(
                                  str(STAND_YAML)).joints)


class TestMotionReplayNpz:
    def test_load_and_duration(self, jm):
        if not NPZ_PATH.is_file():
            pytest.skip("walk.npz not present")
        rep = MotionReplay.from_npz(str(NPZ_PATH), jm, window_s=30.0)
        assert 0.0 < rep.duration <= 30.0
        assert rep.playback_rate == 100.0

    def test_resample_rate(self, jm):
        if not NPZ_PATH.is_file():
            pytest.skip("walk.npz not present")
        rep = MotionReplay.from_npz(str(NPZ_PATH), jm, window_s=10.0)
        # consecutive grid-step samples must be close (dt = 1/rate)
        a = rep.sample_at(1.0)
        b = rep.sample_at(1.0 + 1.0 / rep.playback_rate)
        for k in a:
            assert abs(a[k] - b[k]) < 0.15

    def test_values_within_source_range(self, jm):
        if not NPZ_PATH.is_file():
            pytest.skip("walk.npz not present")
        with np.load(str(NPZ_PATH), allow_pickle=True) as d:
            lo = d["qpos"][:, 7:].min(axis=0)
            hi = d["qpos"][:, 7:].max(axis=0)
            lo_map = dict(zip(LOCO_MUJOCO_KEYS, lo))
            hi_map = dict(zip(LOCO_MUJOCO_KEYS, hi))
        rep = MotionReplay.from_npz(str(NPZ_PATH), jm, window_s=30.0)
        for t in np.linspace(0.0, 29.0, 200):
            pose = rep.sample_at(t)
            for loco_key in LOCO_MUJOCO_KEYS:
                h1 = jm.mapping.get(loco_key)
                if h1 is None:
                    continue
                assert lo_map[loco_key] - 1e-6 <= pose[h1] <= hi_map[loco_key] + 1e-6

    def test_periodic(self, jm):
        if not NPZ_PATH.is_file():
            pytest.skip("walk.npz not present")
        rep = MotionReplay.from_npz(str(NPZ_PATH), jm, window_s=5.0)
        a = rep.sample_at(3.0)
        b = rep.sample_at(3.0 + rep.duration)
        assert a == pytest.approx(b)

    def test_speed_multiplier_slows(self, jm):
        if not NPZ_PATH.is_file():
            pytest.skip("walk.npz not present")
        rep = MotionReplay.from_npz(str(NPZ_PATH), jm, window_s=5.0,
                                    speed_multiplier=0.5)
        slow = rep.sample_at(2.0)          # nominal time 2*0.5 = 1.0 s
        nom = MotionReplay.from_npz(str(NPZ_PATH), jm, window_s=5.0,
                                    speed_multiplier=1.0).sample_at(1.0)
        assert slow == pytest.approx(nom)
        assert rep.realtime_duration == pytest.approx(2.0 * rep.duration)

    def test_complete_17_joint_pose(self, jm):
        if not NPZ_PATH.is_file():
            pytest.skip("walk.npz not present")
        rep = MotionReplay.from_npz(str(NPZ_PATH), jm, window_s=5.0)
        assert len(rep.sample_at(1.0)) == N_JOINTS

    def test_rejects_bad_inputs(self, jm):
        with pytest.raises(ValueError):
            MotionReplay(np.zeros((10, 19)), LOCO_MUJOCO_KEYS, -1.0, jm)
        with pytest.raises(ValueError):
            MotionReplay(np.zeros((10, 5)), LOCO_MUJOCO_KEYS, 1.0, jm)


class TestSineGait:
    def test_periodicity(self, jm):
        g = SineGait(jm)
        t0, t1 = 1.3, 1.3 + g.duration
        assert g.sample_at(t0) == pytest.approx(g.sample_at(t1))

    def test_amplitudes_within_bounds(self, jm):
        g = SineGait(jm)
        # knee has a -0.35 rad offset; total range stays well inside +/-1
        for t in np.linspace(0.0, 2.0 * g.duration, 500):
            for v in g.sample_at(t).values():
                assert -1.0 <= v <= 1.0
        for _, amp, _ in SineGait.LEFT_GAIT + SineGait.RIGHT_GAIT:
            assert abs(amp) <= SineGait.AMP_MAX

    def test_legs_out_of_phase(self, jm):
        g = SineGait(jm)
        t = 0.25 * g.duration  # quarter cycle: left at +amp, right at -amp
        l = g.sample_at(t)["left_hip_pitch_joint"]
        r = g.sample_at(t)["right_hip_pitch_joint"]
        assert l > 0.05 and r < -0.05  # opposite phase

    def test_frequency_hz(self, jm):
        g = SineGait(jm, frequency_hz=1.6)
        assert g.duration == pytest.approx(1.0 / 1.6)
        assert g.sample_at(0.0)["left_hip_pitch_joint"] == pytest.approx(
            g.sample_at(1.0 / 1.6)["left_hip_pitch_joint"])

    def test_complete_17_joint_pose(self, jm):
        assert len(SineGait(jm).sample_at(0.1)) == N_JOINTS

    def test_speed_multiplier(self, jm):
        slow = SineGait(jm, speed_multiplier=0.5)
        assert slow.sample_at(2.0) == pytest.approx(
            SineGait(jm, speed_multiplier=1.0).sample_at(1.0))


class TestMakeMotionPlayer:
    def test_npz_preferred(self, jm):
        if not NPZ_PATH.is_file():
            pytest.skip("walk.npz not present")
        player, source = make_motion_player(str(NPZ_PATH), jm)
        assert isinstance(player, MotionReplay)
        assert source.startswith("npz:")

    def test_missing_npz_falls_back_to_sine(self, jm):
        player, source = make_motion_player("/nonexistent/walk.npz", jm)
        assert isinstance(player, SineGait)
        assert source == "sine"


# -------------------------------------------------------------- estop
class TestEstopGate:
    def test_allows_when_clear(self):
        assert EstopGate.allows(False) is True

    def test_blocks_when_active(self):
        assert EstopGate.allows(True) is False

    def test_abort_only_when_running(self):
        assert EstopGate.should_abort(True, True) is True
        assert EstopGate.should_abort(True, False) is False
        assert EstopGate.should_abort(False, True) is False
        assert EstopGate.should_abort(False, False) is False
