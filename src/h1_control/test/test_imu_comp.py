"""Pure-logic unit tests for the IMU ankle compensation (no ROS imports).

Run: PYTHONPATH=src python3 -m pytest test/ -q   (from the package root)
"""

import math

import pytest

from h1_control.imu_comp import (DEFAULT_ANKLE_PITCH_JOINTS,
                                 DEFAULT_ANKLE_ROLL_JOINTS,
                                 ImuAnkleCompensation,
                                 quaternion_to_pitch_roll_deg)

ALL_ANGLES = 4  # 2 pitch + 2 roll ankle joints
KP = 0.02       # rad correction per degree of drift


def quat_from_axis_angle(axis, deg):
    """Rotation quaternion (x, y, z, w) for a rotation of `deg` about `axis`."""
    rad = math.radians(deg)
    half = 0.5 * rad
    s = math.sin(half)
    c = math.cos(half)
    return axis[0] * s, axis[1] * s, axis[2] * s, c


class TestQuaternionConversion:
    def test_identity_is_zero(self):
        assert quaternion_to_pitch_roll_deg(0.0, 0.0, 0.0, 1.0) == (0.0, 0.0)

    def test_forward_lean_positive_pitch(self):
        # +10 deg about +Y (lean forward) -> pitch ~ +10, roll ~ 0
        q = quat_from_axis_angle((0.0, 1.0, 0.0), 10.0)
        pitch, roll = quaternion_to_pitch_roll_deg(*q)
        assert pitch == pytest.approx(10.0, abs=1e-6)
        assert roll == pytest.approx(0.0, abs=1e-6)

    def test_lean_left_positive_roll(self):
        # +10 deg about +X (torso tilts toward +Y) -> roll ~ +10, pitch ~ 0
        q = quat_from_axis_angle((1.0, 0.0, 0.0), 10.0)
        pitch, roll = quaternion_to_pitch_roll_deg(*q)
        assert roll == pytest.approx(10.0, abs=1e-6)
        assert pitch == pytest.approx(0.0, abs=1e-6)

    def test_zero_norm_is_zero(self):
        assert quaternion_to_pitch_roll_deg(0.0, 0.0, 0.0, 0.0) == (0.0, 0.0)


class TestImuAnkleCompensation:
    def test_zero_drift_gives_zero_correction(self):
        comp = ImuAnkleCompensation(kp_pitch_rad_per_deg=KP)
        corr = comp.update(0.0, 0.0)
        assert set(corr.keys()) == set(DEFAULT_ANKLE_PITCH_JOINTS) | \
            set(DEFAULT_ANKLE_ROLL_JOINTS)
        assert all(v == 0.0 for v in corr.values())

    def test_positive_pitch_corrects_ankle_pitch_same_sign(self):
        comp = ImuAnkleCompensation(kp_pitch_rad_per_deg=KP, deadzone_deg=0.0, ema_alpha=1.0)
        corr = comp.update(5.0, 0.0)
        # forward lean -> plantarflexion (positive) on BOTH ankles
        for j in DEFAULT_ANKLE_PITCH_JOINTS:
            assert corr[j] == pytest.approx(KP * 5.0)
            assert corr[j] > 0.0
        for j in DEFAULT_ANKLE_ROLL_JOINTS:
            assert corr[j] == 0.0

    def test_negative_pitch_corrects_negative(self):
        comp = ImuAnkleCompensation(kp_pitch_rad_per_deg=KP, deadzone_deg=0.0, ema_alpha=1.0)
        corr = comp.update(-5.0, 0.0)
        for j in DEFAULT_ANKLE_PITCH_JOINTS:
            assert corr[j] == pytest.approx(-KP * 5.0)
            assert corr[j] < 0.0

    def test_roll_maps_to_ankle_roll_same_sign(self):
        comp = ImuAnkleCompensation(kp_roll_rad_per_deg=KP, deadzone_deg=0.0, ema_alpha=1.0)
        corr = comp.update(0.0, 4.0)
        # lean toward +Y -> CoP toward +Y -> positive roll on BOTH ankles
        for j in DEFAULT_ANKLE_ROLL_JOINTS:
            assert corr[j] == pytest.approx(KP * 4.0)
            assert corr[j] > 0.0
        for j in DEFAULT_ANKLE_PITCH_JOINTS:
            assert corr[j] == 0.0

    def test_deadzone_suppresses_small_drift(self):
        comp = ImuAnkleCompensation(kp_pitch_rad_per_deg=KP, deadzone_deg=1.0, ema_alpha=1.0)
        corr = comp.update(0.5, 0.0)
        assert all(v == 0.0 for v in corr.values())
        corr2 = comp.update(2.0, 0.0)  # above deadzone -> active
        assert any(v != 0.0 for v in corr2.values())

    def test_clamp_limits_correction(self):
        comp = ImuAnkleCompensation(kp_pitch_rad_per_deg=KP, deadzone_deg=0.0,
                                    clamp_pitch_deg=8.0, ema_alpha=1.0)
        corr = comp.update(60.0, 0.0)  # huge drift
        expected = KP * 8.0
        for j in DEFAULT_ANKLE_PITCH_JOINTS:
            assert corr[j] == pytest.approx(expected)
            assert abs(corr[j]) <= expected + 1e-12

    def test_roll_clamp_independent_of_pitch(self):
        comp = ImuAnkleCompensation(kp_pitch_rad_per_deg=KP,
                                    kp_roll_rad_per_deg=KP, deadzone_deg=0.0,
                                    clamp_pitch_deg=8.0, clamp_roll_deg=6.0, ema_alpha=1.0)
        corr = comp.update(60.0, 90.0)
        assert corr[DEFAULT_ANKLE_PITCH_JOINTS[0]] == pytest.approx(KP * 8.0)
        assert corr[DEFAULT_ANKLE_ROLL_JOINTS[0]] == pytest.approx(KP * 6.0)

    def test_ema_smooths_step(self):
        alpha = 0.2
        comp = ImuAnkleCompensation(kp_pitch_rad_per_deg=KP, deadzone_deg=0.0,
                                    ema_alpha=alpha)
        corr1 = comp.update(10.0, 0.0)
        assert corr1[DEFAULT_ANKLE_PITCH_JOINTS[0]] == pytest.approx(KP * 10.0 * alpha)
        corr2 = comp.update(10.0, 0.0)
        # second sample converges further toward the target (monotonic up)
        v2 = corr2[DEFAULT_ANKLE_PITCH_JOINTS[0]]
        v1 = corr1[DEFAULT_ANKLE_PITCH_JOINTS[0]]
        assert 0.0 < v1 < v2 < KP * 10.0

    def test_ema_alpha_one_is_instantaneous(self):
        comp = ImuAnkleCompensation(kp_pitch_rad_per_deg=KP, deadzone_deg=0.0,
                                    ema_alpha=1.0)
        corr = comp.update(7.0, 0.0)
        assert corr[DEFAULT_ANKLE_PITCH_JOINTS[0]] == pytest.approx(KP * 7.0)

    def test_reset_forgets_ema(self):
        comp = ImuAnkleCompensation(kp_pitch_rad_per_deg=KP, deadzone_deg=0.0,
                                    ema_alpha=0.2)
        comp.update(10.0, 0.0)
        comp.reset()
        corr = comp.update(10.0, 0.0)
        assert corr[DEFAULT_ANKLE_PITCH_JOINTS[0]] == pytest.approx(KP * 10.0 * 0.2)

    def test_returns_exactly_ankle_joints(self):
        comp = ImuAnkleCompensation()
        corr = comp.update(3.0, -2.0)
        assert len(corr) == ALL_ANGLES
        assert all("ankle" in k for k in corr.keys())

    def test_rejects_bad_args(self):
        with pytest.raises(ValueError):
            ImuAnkleCompensation(ema_alpha=0.0)
        with pytest.raises(ValueError):
            ImuAnkleCompensation(ema_alpha=1.5)
        with pytest.raises(ValueError):
            ImuAnkleCompensation(kp_pitch_rad_per_deg=-1.0)
        with pytest.raises(ValueError):
            ImuAnkleCompensation(deadzone_deg=-1.0)
        with pytest.raises(ValueError):
            ImuAnkleCompensation(pitch_joints=("a", "a"), roll_joints=("b",))
        with pytest.raises(ValueError):
            ImuAnkleCompensation(pitch_joints=("a",), roll_joints=("a",))