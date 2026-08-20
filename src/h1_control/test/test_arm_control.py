"""Pure-logic unit tests for the M5 arm-control blend (no ROS imports).

Run: PYTHONPATH=src python3 -m pytest test/ -q   (from the package root)
"""

import math

import pytest

from h1_control.arm_control import (ARM_CMD_FRESH_WINDOW_S, ARM_JOINT_NAMES,
                                    DEFAULT_ARM_LIMITS, blend_arm_joint,
                                    clamp_arm_joint, is_arm_cmd_recent)

N_ARM_JOINTS = 4  # 2 shoulder_pitch + 2 elbow; wrists are un-actuated
SHOULDER_LIMITS = (-2.5, 2.5)  # H1-2 URDF default for the four arm joints


class TestDefaults:
    def test_arm_joint_names_are_four_actuated(self):
        assert len(ARM_JOINT_NAMES) == N_ARM_JOINTS
        assert "left_shoulder_pitch_joint" in ARM_JOINT_NAMES
        assert "left_elbow_joint" in ARM_JOINT_NAMES
        assert "right_shoulder_pitch_joint" in ARM_JOINT_NAMES
        assert "right_elbow_joint" in ARM_JOINT_NAMES
        # wrists are un-actuated and must NOT be blend candidates
        assert not any("wrist" in j for j in ARM_JOINT_NAMES)

    def test_default_limits_cover_all_arm_joints(self):
        assert set(DEFAULT_ARM_LIMITS.keys()) == set(ARM_JOINT_NAMES)
        for joint in ARM_JOINT_NAMES:
            lo, hi = DEFAULT_ARM_LIMITS[joint]
            assert (lo, hi) == SHOULDER_LIMITS

    def test_fresh_window_is_half_second(self):
        assert ARM_CMD_FRESH_WINDOW_S == pytest.approx(0.5)


class TestBlendArmJoint:
    def test_enabled_recent_cmd_uses_cmd(self):
        assert blend_arm_joint(0.0, 1.2, enabled=True, recent=True) == 1.2

    def test_disabled_uses_plan(self):
        assert blend_arm_joint(0.0, 1.2, enabled=False, recent=True) == 0.0

    def test_stale_uses_plan(self):
        assert blend_arm_joint(-0.4, 1.2, enabled=True, recent=False) == -0.4

    def test_no_cmd_uses_plan(self):
        assert blend_arm_joint(0.3, None, enabled=True, recent=True) == 0.3

    def test_disabled_and_stale_uses_plan(self):
        assert blend_arm_joint(0.5, 1.2, enabled=False, recent=False) == 0.5

    def test_disabled_without_cmd_uses_plan(self):
        assert blend_arm_joint(0.1, None, enabled=False, recent=False) == 0.1

    def test_cmd_passes_through_unchanged(self):
        assert blend_arm_joint(2.0, -1.75, enabled=True, recent=True) == -1.75

    def test_plan_passes_through_unchanged(self):
        assert blend_arm_joint(-1.25, None, enabled=True, recent=False) == -1.25


class TestClampArmJoint:
    def test_within_limits_unchanged(self):
        assert clamp_arm_joint(1.0, (-2.5, 2.5)) == 1.0
        assert clamp_arm_joint(-2.5, (-2.5, 2.5)) == -2.5
        assert clamp_arm_joint(2.5, (-2.5, 2.5)) == 2.5

    def test_above_max_clamped(self):
        assert clamp_arm_joint(3.0, (-2.5, 2.5)) == 2.5
        assert clamp_arm_joint(99.9, SHOULDER_LIMITS) == 2.5

    def test_below_min_clamped(self):
        assert clamp_arm_joint(-3.0, (-2.5, 2.5)) == -2.5
        assert clamp_arm_joint(-99.9, SHOULDER_LIMITS) == -2.5

    def test_non_standard_limits(self):
        assert clamp_arm_joint(1.0, (0.0, 0.5)) == 0.5
        assert clamp_arm_joint(-1.0, (0.0, 0.5)) == 0.0

    def test_nan_rejected(self):
        assert clamp_arm_joint(float("nan"), SHOULDER_LIMITS) is None

    def test_inf_rejected(self):
        assert clamp_arm_joint(float("inf"), SHOULDER_LIMITS) is None
        assert clamp_arm_joint(float("-inf"), SHOULDER_LIMITS) is None

    def test_unconvertible_rejected(self):
        assert clamp_arm_joint("not-a-number", SHOULDER_LIMITS) is None

    def test_lists_as_limits_work(self):
        # config/control_server.yaml uses YAML lists, not tuples
        assert clamp_arm_joint(9.0, [-2.5, 2.5]) == 2.5


class TestIsArmCmdRecent:
    def test_no_stamp_never_recent(self):
        assert is_arm_cmd_recent(10.0, None) is False

    def test_just_received_recent(self):
        assert is_arm_cmd_recent(10.0, 10.0) is True

    def test_within_window_recent(self):
        assert is_arm_cmd_recent(10.4, 10.0) is True

    def test_at_boundary_recent(self):
        assert is_arm_cmd_recent(10.5, 10.0) is True

    def test_just_past_window_stale(self):
        assert is_arm_cmd_recent(10.5 + 1e-9, 10.0) is False

    def test_far_past_stale(self):
        assert is_arm_cmd_recent(100.0, 10.0) is False

    def test_future_stamp_is_recent(self):
        # clock edge: a stamp slightly ahead of now is not rejected
        assert is_arm_cmd_recent(10.0, 10.2) is True

    def test_custom_window(self):
        assert is_arm_cmd_recent(2.0, 1.0, window_s=1.0) is True
        assert is_arm_cmd_recent(2.1, 1.0, window_s=1.0) is False

    def test_zero_window(self):
        assert is_arm_cmd_recent(5.0, 5.0, window_s=0.0) is True
        assert is_arm_cmd_recent(5.0, 4.9, window_s=0.0) is False