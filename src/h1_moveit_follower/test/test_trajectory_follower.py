"""Unit tests for TrajectoryFollower pure logic module.

Tests cover interpolation correctness, joint name mapping, arm-only filtering,
preempt handling, and tolerance checking. No ROS dependencies.
"""

import pytest
import math
from h1_moveit_follower.trajectory_follower import (
    TrajectoryFollower,
    create_trajectory_point,
)


@pytest.fixture
def default_follower():
    """Create a TrajectoryFollower with default settings."""
    return TrajectoryFollower(
        control_hz=50.0,
        arm_joint_names=[
            "left_shoulder_pitch_joint",
            "left_elbow_joint",
            "right_shoulder_pitch_joint",
            "right_elbow_joint",
        ],
        stand_pose_fallback={
            "left_shoulder_pitch_joint": 0.0,
            "left_elbow_joint": 0.0,
            "right_shoulder_pitch_joint": 0.0,
            "right_elbow_joint": 0.0,
            "torso_joint": 0.0,
            "left_hip_yaw_joint": 0.0,
        },
        trajectory_tolerance={"position": 0.01, "velocity": 0.1},
    )


@pytest.fixture
def simple_trajectory():
    """Create a simple 2-point trajectory for testing."""
    return [
        create_trajectory_point(
            time_from_start=0.0,
            positions=[0.0, 0.0, 0.0, 0.0],
        ),
        create_trajectory_point(
            time_from_start=1.0,
            positions=[0.5, 0.3, -0.5, -0.3],
        ),
    ]


@pytest.fixture
def arm_joint_names():
    """Standard arm joint names."""
    return [
        "left_shoulder_pitch_joint",
        "left_elbow_joint",
        "right_shoulder_pitch_joint",
        "right_elbow_joint",
    ]


class TestTrajectoryFollowerInitialization:
    """Tests for TrajectoryFollower initialization."""

    def test_default_initialization(self):
        """Test default parameter initialization."""
        follower = TrajectoryFollower()
        assert follower.control_hz == 50.0
        assert follower.dt == 0.02
        assert len(follower.arm_joint_names) == 4

    def test_custom_initialization(self):
        """Test custom parameter initialization."""
        follower = TrajectoryFollower(
            control_hz=100.0,
            arm_joint_names=["joint1", "joint2"],
            stand_pose_fallback={"joint1": 1.0, "joint2": 2.0},
            trajectory_tolerance={"position": 0.05, "velocity": 0.2},
        )
        assert follower.control_hz == 100.0
        assert follower.dt == 0.01
        assert follower.arm_joint_names == ["joint1", "joint2"]
        assert follower.stand_pose_fallback["joint1"] == 1.0
        assert follower.trajectory_tolerance["position"] == 0.05

    def test_missing_stand_pose_raises(self):
        """Test that missing stand pose for arm joint raises ValueError."""
        with pytest.raises(ValueError, match="not in stand_pose_fallback"):
            TrajectoryFollower(
                arm_joint_names=["joint1", "joint2"],
                stand_pose_fallback={"joint1": 0.0},  # missing joint2
            )


class TestInterpolationCorrectness:
    """Tests for trajectory interpolation correctness."""

    def test_linear_interpolation_midpoint(self, default_follower, simple_trajectory, arm_joint_names):
        """Test linear interpolation at trajectory midpoint."""
        results = list(default_follower.follow(simple_trajectory, arm_joint_names))

        # At 50 Hz over 1 second = 51 steps (0 to 50 inclusive)
        assert len(results) == 51

        # Check midpoint (t=0.5, step 25)
        t_mid, positions_mid = results[25]
        assert abs(t_mid - 0.5) < 0.001

        # Linear interpolation: 0.5 * target
        assert abs(positions_mid["left_shoulder_pitch_joint"] - 0.25) < 0.001
        assert abs(positions_mid["left_elbow_joint"] - 0.15) < 0.001
        assert abs(positions_mid["right_shoulder_pitch_joint"] - (-0.25)) < 0.001
        assert abs(positions_mid["right_elbow_joint"] - (-0.15)) < 0.001

    def test_start_position(self, default_follower, simple_trajectory, arm_joint_names):
        """Test that trajectory starts at initial positions."""
        results = list(default_follower.follow(simple_trajectory, arm_joint_names))
        t_start, positions_start = results[0]
        assert t_start == 0.0
        for joint in arm_joint_names:
            assert positions_start[joint] == 0.0

    def test_end_position(self, default_follower, simple_trajectory, arm_joint_names):
        """Test that trajectory ends at target positions."""
        results = list(default_follower.follow(simple_trajectory, arm_joint_names))
        t_end, positions_end = results[-1]
        assert abs(t_end - 1.0) < 0.001
        assert abs(positions_end["left_shoulder_pitch_joint"] - 0.5) < 0.001
        assert abs(positions_end["left_elbow_joint"] - 0.3) < 0.001
        assert abs(positions_end["right_shoulder_pitch_joint"] - (-0.5)) < 0.001
        assert abs(positions_end["right_elbow_joint"] - (-0.3)) < 0.001

    def test_multi_segment_trajectory(self, default_follower, arm_joint_names):
        """Test interpolation with multiple trajectory segments."""
        trajectory = [
            create_trajectory_point(0.0, [0.0, 0.0, 0.0, 0.0]),
            create_trajectory_point(0.5, [0.5, 0.0, 0.0, 0.0]),
            create_trajectory_point(1.0, [0.5, 0.5, 0.0, 0.0]),
        ]
        results = list(default_follower.follow(trajectory, arm_joint_names))

        # At t=0.24 (step 12, first segment ~halfway)
        t_24, pos_24 = results[12]
        assert abs(pos_24["left_shoulder_pitch_joint"] - 0.24) < 0.01

        # At t=0.74 (step 37, second segment ~halfway)
        t_74, pos_74 = results[37]
        assert abs(pos_74["left_shoulder_pitch_joint"] - 0.5) < 0.01
        assert abs(pos_74["left_elbow_joint"] - 0.24) < 0.01

    def test_control_hz_affects_step_count(self, simple_trajectory, arm_joint_names):
        """Test that control_hz affects number of interpolation steps."""
        follower_10hz = TrajectoryFollower(control_hz=10.0)
        follower_100hz = TrajectoryFollower(control_hz=100.0)

        results_10 = list(follower_10hz.follow(simple_trajectory, arm_joint_names))
        results_100 = list(follower_100hz.follow(simple_trajectory, arm_joint_names))

        # 10 Hz: 11 steps (0 to 10), 100 Hz: 101 steps (0 to 100)
        assert len(results_10) == 11
        assert len(results_100) == 101


class TestJointNameMapping:
    """Tests for joint name mapping and filtering."""

    def test_arm_only_filtering(self, default_follower):
        """Test that only arm joints are extracted from full trajectory."""
        full_joint_names = [
            "torso_joint",
            "left_hip_yaw_joint",
            "left_shoulder_pitch_joint",
            "left_elbow_joint",
            "right_shoulder_pitch_joint",
            "right_elbow_joint",
        ]
        trajectory = [
            create_trajectory_point(0.0, [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
            create_trajectory_point(1.0, [0.1, 0.2, 0.5, 0.3, -0.5, -0.3]),
        ]

        results = list(default_follower.follow(trajectory, full_joint_names))

        # Only arm joints should be in cmd_positions, others from stand_pose
        t_end, positions_end = results[-1]
        assert abs(positions_end["left_shoulder_pitch_joint"] - 0.5) < 0.001
        assert abs(positions_end["left_elbow_joint"] - 0.3) < 0.001
        assert abs(positions_end["right_shoulder_pitch_joint"] - (-0.5)) < 0.001
        assert abs(positions_end["right_elbow_joint"] - (-0.3)) < 0.001

        # Non-arm joints should be at stand pose
        assert positions_end["torso_joint"] == 0.0
        assert positions_end["left_hip_yaw_joint"] == 0.0

    def test_partial_arm_trajectory(self, default_follower):
        """Test trajectory with only left arm joints."""
        joint_names = ["left_shoulder_pitch_joint", "left_elbow_joint"]
        trajectory = [
            create_trajectory_point(0.0, [0.0, 0.0]),
            create_trajectory_point(1.0, [0.5, 0.3]),
        ]

        results = list(default_follower.follow(trajectory, joint_names))
        t_end, positions_end = results[-1]

        assert abs(positions_end["left_shoulder_pitch_joint"] - 0.5) < 0.001
        assert abs(positions_end["left_elbow_joint"] - 0.3) < 0.001
        # Right arm should be at stand pose (0.0)
        assert positions_end["right_shoulder_pitch_joint"] == 0.0
        assert positions_end["right_elbow_joint"] == 0.0

    def test_joint_name_order_independence(self, default_follower):
        """Test that joint order in trajectory doesn't matter."""
        joint_names_a = ["left_shoulder_pitch_joint", "left_elbow_joint"]
        joint_names_b = ["left_elbow_joint", "left_shoulder_pitch_joint"]

        trajectory_a = [
            create_trajectory_point(0.0, [0.0, 0.0]),
            create_trajectory_point(1.0, [0.5, 0.3]),
        ]
        trajectory_b = [
            create_trajectory_point(0.0, [0.0, 0.0]),
            create_trajectory_point(1.0, [0.3, 0.5]),
        ]

        results_a = list(default_follower.follow(trajectory_a, joint_names_a))
        results_b = list(default_follower.follow(trajectory_b, joint_names_b))

        _, pos_a = results_a[-1]
        _, pos_b = results_b[-1]

        assert abs(pos_a["left_shoulder_pitch_joint"] - pos_b["left_shoulder_pitch_joint"]) < 0.001
        assert abs(pos_a["left_elbow_joint"] - pos_b["left_elbow_joint"]) < 0.001

    def test_validate_joint_names_success(self, default_follower):
        """Test joint name validation with valid names."""
        joint_names = ["left_shoulder_pitch_joint", "left_elbow_joint", "torso_joint"]
        is_valid, unknown = default_follower.validate_joint_names(joint_names)
        assert is_valid is True
        assert unknown == []

    def test_validate_joint_names_unknown(self, default_follower):
        """Test joint name validation with unknown joints."""
        joint_names = ["left_shoulder_pitch_joint", "unknown_joint"]
        is_valid, unknown = default_follower.validate_joint_names(joint_names)
        assert is_valid is False
        assert "unknown_joint" in unknown

    def test_validate_joint_names_no_arm_joints(self, default_follower):
        """Test validation fails when no arm joints in trajectory."""
        joint_names = ["torso_joint", "left_hip_yaw_joint"]
        is_valid, unknown = default_follower.validate_joint_names(joint_names)
        assert is_valid is False


class TestStandPoseFallback:
    """Tests for stand pose fallback behavior."""

    def test_stand_pose_for_frozen_joints(self, default_follower, arm_joint_names):
        """Test that non-trajectory joints use stand pose."""
        custom_stand = {
            "left_shoulder_pitch_joint": 0.0,
            "left_elbow_joint": 0.0,
            "right_shoulder_pitch_joint": 0.0,
            "right_elbow_joint": 0.0,
            "torso_joint": 0.5,
            "left_hip_pitch_joint": -0.2,
        }
        follower = TrajectoryFollower(stand_pose_fallback=custom_stand)

        trajectory = [
            create_trajectory_point(0.0, [0.0, 0.0, 0.0, 0.0]),
            create_trajectory_point(1.0, [0.5, 0.3, -0.5, -0.3]),
        ]

        results = list(follower.follow(trajectory, arm_joint_names))
        _, positions = results[-1]

        assert positions["torso_joint"] == 0.5
        assert positions["left_hip_pitch_joint"] == -0.2

    def test_stand_pose_override(self, default_follower, simple_trajectory, arm_joint_names):
        """Test that stand_pose_dict overrides fallback."""
        override_stand = {
            "torso_joint": 1.0,
            "left_hip_pitch_joint": -0.5,
        }

        results = list(default_follower.follow(
            simple_trajectory, arm_joint_names, stand_pose_dict=override_stand
        ))
        _, positions = results[-1]

        assert positions["torso_joint"] == 1.0
        assert positions["left_hip_pitch_joint"] == -0.5

    def test_arm_joints_not_overridden_by_stand_pose(self, default_follower, simple_trajectory, arm_joint_names):
        """Test that arm joint targets are not overridden by stand pose."""
        # Try to override arm joint via stand_pose_dict - should be ignored
        override_stand = {
            "left_shoulder_pitch_joint": 999.0,  # Should not affect trajectory
        }

        results = list(default_follower.follow(
            simple_trajectory, arm_joint_names, stand_pose_dict=override_stand
        ))
        _, positions = results[-1]

        # Should follow trajectory, not stand pose
        assert abs(positions["left_shoulder_pitch_joint"] - 0.5) < 0.001


class TestToleranceChecking:
    """Tests for trajectory tolerance checking."""

    def test_position_tolerance_pass(self, default_follower):
        """Test tolerance check passes when within position tolerance."""
        current = {"joint1": 0.5, "joint2": 0.3}
        target = {"joint1": 0.505, "joint2": 0.295}  # Within 0.01

        assert default_follower.check_trajectory_tolerance(current, target) is True

    def test_position_tolerance_fail(self, default_follower):
        """Test tolerance check fails when outside position tolerance."""
        current = {"joint1": 0.5, "joint2": 0.3}
        target = {"joint1": 0.52, "joint2": 0.3}  # 0.02 > 0.01

        assert default_follower.check_trajectory_tolerance(current, target) is False

    def test_velocity_tolerance_pass(self, default_follower):
        """Test tolerance check passes when within velocity tolerance."""
        current = {"joint1": 0.5, "joint2": 0.3}
        target = {"joint1": 0.5, "joint2": 0.3}
        velocities = {"joint1": 0.05, "joint2": 0.0}  # Within 0.1

        assert default_follower.check_trajectory_tolerance(current, target, velocities) is True

    def test_velocity_tolerance_fail(self, default_follower):
        """Test tolerance check fails when outside velocity tolerance."""
        current = {"joint1": 0.5, "joint2": 0.3}
        target = {"joint1": 0.5, "joint2": 0.3}
        velocities = {"joint1": 0.2, "joint2": 0.0}  # 0.2 > 0.1

        assert default_follower.check_trajectory_tolerance(current, target, velocities) is False

    def test_missing_joint_in_current_fails(self, default_follower):
        """Test tolerance check fails when joint missing from current."""
        current = {"joint1": 0.5}
        target = {"joint1": 0.5, "joint2": 0.3}

        assert default_follower.check_trajectory_tolerance(current, target) is False


class TestFilterArmJoints:
    """Tests for filter_arm_joints helper method."""

    def test_filter_arm_joints(self, default_follower):
        """Test filtering arm joints from full joint list."""
        joint_names = [
            "torso_joint",
            "left_shoulder_pitch_joint",
            "left_elbow_joint",
            "right_shoulder_pitch_joint",
            "right_elbow_joint",
            "left_hip_yaw_joint",
        ]
        positions = [0.0, 0.5, 0.3, -0.5, -0.3, 0.1]

        filtered = default_follower.filter_arm_joints(joint_names, positions)

        assert filtered == {
            "left_shoulder_pitch_joint": 0.5,
            "left_elbow_joint": 0.3,
            "right_shoulder_pitch_joint": -0.5,
            "right_elbow_joint": -0.3,
        }

    def test_filter_arm_joints_empty(self, default_follower):
        """Test filtering with no arm joints."""
        joint_names = ["torso_joint", "left_hip_yaw_joint"]
        positions = [0.0, 0.1]

        filtered = default_follower.filter_arm_joints(joint_names, positions)
        assert filtered == {}


class TestEdgeCases:
    """Tests for edge cases and error conditions."""

    def test_empty_trajectory_returns_empty(self, default_follower, arm_joint_names):
        """Test that empty trajectory returns empty generator."""
        results = list(default_follower.follow([], arm_joint_names))
        assert results == []

    def test_single_point_trajectory(self, default_follower, arm_joint_names):
        """Test trajectory with single point (no interpolation)."""
        trajectory = [create_trajectory_point(0.0, [0.5, 0.3, -0.5, -0.3])]

        results = list(default_follower.follow(trajectory, arm_joint_names))

        # Should have at least one point
        assert len(results) >= 1
        _, positions = results[0]
        assert abs(positions["left_shoulder_pitch_joint"] - 0.5) < 0.001

    def test_zero_duration_trajectory(self, default_follower, arm_joint_names):
        """Test trajectory with zero duration."""
        trajectory = [
            create_trajectory_point(0.0, [0.0, 0.0, 0.0, 0.0]),
            create_trajectory_point(0.0, [0.5, 0.3, -0.5, -0.3]),
        ]

        results = list(default_follower.follow(trajectory, arm_joint_names))
        # Should handle gracefully
        assert len(results) >= 1

    def test_preempt_handling_via_generator_stop(self, default_follower, arm_joint_names):
        """Test that stopping generator early simulates preempt."""
        trajectory = [
            create_trajectory_point(0.0, [0.0, 0.0, 0.0, 0.0]),
            create_trajectory_point(10.0, [0.5, 0.3, -0.5, -0.3]),  # Long trajectory
        ]

        gen = default_follower.follow(trajectory, arm_joint_names)

        # Consume first 10 steps then stop (simulating preempt at 0.2s)
        for _ in range(10):
            next(gen)

        # Generator should be closable without error
        gen.close()

    def test_velocities_in_trajectory_points(self, default_follower, arm_joint_names):
        """Test that velocities in trajectory points are accepted (though not used for interpolation)."""
        trajectory = [
            create_trajectory_point(0.0, [0.0, 0.0, 0.0, 0.0], velocities=[0.1, 0.1, 0.1, 0.1]),
            create_trajectory_point(1.0, [0.5, 0.3, -0.5, -0.3], velocities=[0.0, 0.0, 0.0, 0.0]),
        ]

        results = list(default_follower.follow(trajectory, arm_joint_names))
        assert len(results) == 51


class TestCreateTrajectoryPointHelper:
    """Tests for the create_trajectory_point helper function."""

    def test_basic_creation(self):
        """Test basic trajectory point creation."""
        point = create_trajectory_point(1.0, [0.1, 0.2])
        assert point["time_from_start"] == 1.0
        assert point["positions"] == [0.1, 0.2]
        assert "velocities" not in point

    def test_with_velocities(self):
        """Test creation with velocities."""
        point = create_trajectory_point(1.0, [0.1, 0.2], velocities=[0.01, 0.02])
        assert point["velocities"] == [0.01, 0.02]

    def test_with_accelerations(self):
        """Test creation with accelerations."""
        point = create_trajectory_point(1.0, [0.1, 0.2], accelerations=[0.001, 0.002])
        assert point["accelerations"] == [0.001, 0.002]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])