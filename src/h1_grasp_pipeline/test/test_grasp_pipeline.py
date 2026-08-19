"""Pure logic unit tests for h1_grasp_pipeline (no ROS dependencies).

Run: cd /home/ubuntu/humanoid_sim_ws/src/h1_grasp_pipeline && PYTHONPATH=src python3 -m pytest test/ -q
"""
import numpy as np
import pytest
import math

from h1_grasp_pipeline.grasp_pipeline import (
    GraspPipeline,
    GraspOffsets,
    CameraToBaseTransform,
    MarkerDetection,
    GraspTrajectory,
    create_default_camera_to_base,
    create_default_arm_joint_names,
)


@pytest.fixture
def default_camera_to_base():
    """Default camera-to-base transform for testing."""
    return CameraToBaseTransform(
        translation=np.array([0.1, 0.0, 0.3], dtype=np.float64),
        rotation=np.eye(3, dtype=np.float64),
    )


@pytest.fixture
def default_arm_joint_names():
    """Default arm joint names."""
    return create_default_arm_joint_names()


@pytest.fixture
def default_grasp_offsets():
    """Default grasp offsets."""
    return GraspOffsets(
        approach_distance=0.15,
        grasp_depth=0.02,
        retreat_distance=0.10,
    )


@pytest.fixture
def pipeline(default_camera_to_base, default_arm_joint_names, default_grasp_offsets):
    """Create a GraspPipeline with default settings."""
    return GraspPipeline(
        camera_to_base=default_camera_to_base,
        arm_joint_names=default_arm_joint_names,
        grasp_offsets=default_grasp_offsets,
        target_marker_id=42,
    )


@pytest.fixture
def sample_detection():
    """A sample marker detection in camera frame."""
    return MarkerDetection(
        marker_id=42,
        position=np.array([0.5, 0.0, 0.5], dtype=np.float64),  # 0.5m forward, 0.5m up
        orientation=np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float64),  # Identity quaternion
        confidence=1.0,
    )


class TestGraspPipelineInitialization:
    """Tests for GraspPipeline initialization."""

    def test_default_initialization(self, default_camera_to_base, default_arm_joint_names):
        """Test default parameter initialization."""
        pipeline = GraspPipeline(
            camera_to_base=default_camera_to_base,
            arm_joint_names=default_arm_joint_names,
        )
        assert pipeline.target_marker_id == 0
        assert pipeline.grasp_offsets.approach_distance == 0.15
        assert pipeline.grasp_offsets.grasp_depth == 0.02
        assert pipeline.grasp_offsets.retreat_distance == 0.10
        assert len(pipeline.arm_joint_names) == 4

    def test_custom_initialization(self, default_camera_to_base, default_arm_joint_names, default_grasp_offsets):
        """Test custom parameter initialization."""
        pipeline = GraspPipeline(
            camera_to_base=default_camera_to_base,
            arm_joint_names=default_arm_joint_names,
            grasp_offsets=default_grasp_offsets,
            target_marker_id=100,
        )
        assert pipeline.target_marker_id == 100
        assert pipeline.grasp_offsets.approach_distance == 0.15
        assert pipeline.grasp_offsets.grasp_depth == 0.02
        assert pipeline.grasp_offsets.retreat_distance == 0.10

    def test_invalid_arm_joint_names_raises(self, default_camera_to_base):
        """Test that wrong number of arm joint names raises ValueError."""
        with pytest.raises(ValueError, match="Expected 4 arm joint names"):
            GraspPipeline(
                camera_to_base=default_camera_to_base,
                arm_joint_names=["joint1", "joint2"],  # Only 2 joints
            )


class TestMarkerFiltering:
    """Tests for marker detection filtering."""

    def test_filter_single_target(self, pipeline, sample_detection):
        """Test filtering returns target marker."""
        detections = [
            MarkerDetection(marker_id=1, position=np.zeros(3), orientation=np.array([0,0,0,1.0])),
            sample_detection,  # marker_id=42
            MarkerDetection(marker_id=99, position=np.zeros(3), orientation=np.array([0,0,0,1.0])),
        ]
        filtered = pipeline.filter_detections(detections)
        assert len(filtered) == 1
        assert filtered[0].marker_id == 42

    def test_filter_multiple_targets(self, pipeline):
        """Test filtering returns all target markers."""
        detections = [
            MarkerDetection(marker_id=42, position=np.array([0.5, 0.0, 0.5]), orientation=np.array([0,0,0,1.0])),
            MarkerDetection(marker_id=42, position=np.array([0.6, 0.0, 0.5]), orientation=np.array([0,0,0,1.0])),
            MarkerDetection(marker_id=1, position=np.zeros(3), orientation=np.array([0,0,0,1.0])),
        ]
        filtered = pipeline.filter_detections(detections)
        assert len(filtered) == 2
        assert all(d.marker_id == 42 for d in filtered)

    def test_filter_no_target(self, pipeline):
        """Test filtering returns empty when target not present."""
        detections = [
            MarkerDetection(marker_id=1, position=np.zeros(3), orientation=np.array([0,0,0,1.0])),
            MarkerDetection(marker_id=2, position=np.zeros(3), orientation=np.array([0,0,0,1.0])),
        ]
        filtered = pipeline.filter_detections(detections)
        assert filtered == []

    def test_filter_empty_list(self, pipeline):
        """Test filtering empty list returns empty."""
        filtered = pipeline.filter_detections([])
        assert filtered == []


class TestPoseTransform:
    """Tests for camera-to-base pose transformation."""

    def test_identity_transform(self, pipeline):
        """Test identity camera-to-base transform."""
        # Camera at origin, aligned with base
        cam_to_base = CameraToBaseTransform(
            translation=np.zeros(3),
            rotation=np.eye(3),
        )
        pipeline.camera_to_base = cam_to_base

        pos_cam = np.array([1.0, 2.0, 3.0])
        orient_cam = np.array([0.0, 0.0, 0.0, 1.0])  # Identity quaternion

        pos_base, orient_base = pipeline.transform_pose_camera_to_base(pos_cam, orient_cam)

        np.testing.assert_allclose(pos_base, pos_cam)
        np.testing.assert_allclose(orient_base, orient_cam)

    def test_translation_only(self, pipeline):
        """Test translation-only camera-to-base transform."""
        # Camera offset by (0.1, 0.0, 0.3) from base
        cam_to_base = CameraToBaseTransform(
            translation=np.array([0.1, 0.0, 0.3]),
            rotation=np.eye(3),
        )
        pipeline.camera_to_base = cam_to_base

        pos_cam = np.array([0.5, 0.0, 0.5])
        orient_cam = np.array([0.0, 0.0, 0.0, 1.0])

        pos_base, orient_base = pipeline.transform_pose_camera_to_base(pos_cam, orient_cam)

        # Base position = camera translation + camera position
        expected_pos = np.array([0.6, 0.0, 0.8])
        np.testing.assert_allclose(pos_base, expected_pos)
        np.testing.assert_allclose(orient_base, orient_cam)

    def test_rotation_90deg_z(self, pipeline):
        """Test 90-degree Z rotation in camera-to-base transform."""
        # Camera rotated 90 deg around Z relative to base
        R_z90 = np.array([
            [0, -1, 0],
            [1, 0, 0],
            [0, 0, 1],
        ], dtype=np.float64)
        cam_to_base = CameraToBaseTransform(
            translation=np.zeros(3),
            rotation=R_z90,
        )
        pipeline.camera_to_base = cam_to_base

        # Marker at (1, 0, 0) in camera frame (along camera X)
        pos_cam = np.array([1.0, 0.0, 0.0])
        orient_cam = np.array([0.0, 0.0, 0.0, 1.0])

        pos_base, orient_base = pipeline.transform_pose_camera_to_base(pos_cam, orient_cam)

        # In base frame, should be at (0, 1, 0) (along base Y)
        np.testing.assert_allclose(pos_base, np.array([0.0, 1.0, 0.0]), atol=1e-6)
        # Orientation should also be rotated 90 deg around Z
        expected_orient = np.array([0.0, 0.0, 0.7071, 0.7071])  # 90 deg around Z
        np.testing.assert_allclose(np.abs(orient_base), np.abs(expected_orient), atol=1e-3)

    def test_marker_orientation_transform(self, pipeline):
        """Test marker orientation is properly transformed."""
        # Camera rotated 90 deg around Z
        R_z90 = np.array([
            [0, -1, 0],
            [1, 0, 0],
            [0, 0, 1],
        ], dtype=np.float64)
        cam_to_base = CameraToBaseTransform(
            translation=np.zeros(3),
            rotation=R_z90,
        )
        pipeline.camera_to_base = cam_to_base

        # Marker rotated 90 deg around Y in camera frame
        pos_cam = np.array([0.5, 0.0, 0.5])
        orient_cam = np.array([0.0, 0.7071, 0.0, 0.7071])  # 90 deg around Y

        pos_base, orient_base = pipeline.transform_pose_camera_to_base(pos_cam, orient_cam)

        # Combined rotation: 90 deg Z (cam->base) * 90 deg Y (marker->cam)
        # Result should be a valid quaternion
        assert np.abs(np.linalg.norm(orient_base) - 1.0) < 1e-6


class TestGraspPoseComputation:
    """Tests for pre-grasp, grasp, post-grasp pose computation."""

    def test_grasp_poses_along_z_axis(self, pipeline):
        """Test grasp poses are offset along marker Z-axis."""
        # Marker at origin, no rotation (Z points up)
        marker_pos = np.array([0.5, 0.0, 0.5])
        marker_orient = np.array([0.0, 0.0, 0.0, 1.0])  # Identity

        T_pre, T_grasp, T_post = pipeline.compute_grasp_poses(marker_pos, marker_orient)

        # Grasp at marker position
        np.testing.assert_allclose(T_grasp[:3, 3], marker_pos)

        # Pre-grasp: back along -Z by approach_distance (0.15)
        expected_pre = marker_pos - np.array([0.0, 0.0, 0.15])
        np.testing.assert_allclose(T_pre[:3, 3], expected_pre)

        # Post-grasp: forward along +Z by retreat_distance (0.10)
        expected_post = marker_pos + np.array([0.0, 0.0, 0.10])
        np.testing.assert_allclose(T_post[:3, 3], expected_post)

    def test_grasp_poses_rotated_marker(self, pipeline):
        """Test grasp poses with rotated marker (Z points forward)."""
        # Marker rotated 90 deg around Y: Z points along +X
        marker_pos = np.array([0.5, 0.0, 0.5])
        marker_orient = np.array([0.0, 0.7071, 0.0, 0.7071])  # 90 deg around Y

        T_pre, T_grasp, T_post = pipeline.compute_grasp_poses(marker_pos, marker_orient)

        # Z-axis of marker in base frame
        R_marker = np.array([
            [0, 0, 1],
            [0, 1, 0],
            [-1, 0, 0],
        ], dtype=np.float64)
        z_axis = R_marker[:, 2]  # Should be [1, 0, 0] (points along +X)

        # Pre-grasp: back along -Z (i.e., -X direction)
        expected_pre = marker_pos - z_axis * 0.15
        np.testing.assert_allclose(T_pre[:3, 3], expected_pre, atol=1e-3)

        # Post-grasp: forward along +Z (i.e., +X direction)
        expected_post = marker_pos + z_axis * 0.10
        np.testing.assert_allclose(T_post[:3, 3], expected_post, atol=1e-3)

    def test_grasp_pose_orientation_preserved(self, pipeline):
        """Test that grasp poses preserve marker orientation."""
        marker_pos = np.array([0.5, 0.0, 0.5])
        marker_orient = np.array([0.0, 0.7071, 0.0, 0.7071])  # 90 deg around Y

        T_pre, T_grasp, T_post = pipeline.compute_grasp_poses(marker_pos, marker_orient)

        # All poses should have same orientation as marker
        np.testing.assert_allclose(T_pre[:3, :3], T_grasp[:3, :3])
        np.testing.assert_allclose(T_grasp[:3, :3], T_post[:3, :3])


class TestIKSimplified:
    """Tests for simplified IK solver."""

    def test_ik_returns_four_joints(self, pipeline):
        """Test IK returns 4 joint values."""
        T = np.eye(4)
        T[:3, 3] = [0.5, 0.0, 0.5]
        q = pipeline.solve_ik_simplified(T)
        assert len(q) == 4

    def test_ik_joints_within_limits(self, pipeline):
        """Test IK returns joints within reasonable limits."""
        T = np.eye(4)
        T[:3, 3] = [0.5, 0.0, 0.5]
        q = pipeline.solve_ik_simplified(T)
        for joint_val in q:
            assert -2.0 <= joint_val <= 2.0

    def test_ik_different_positions_different_joints(self, pipeline):
        """Test different target positions produce different joint values."""
        T1 = np.eye(4)
        T1[:3, 3] = [0.5, 0.0, 0.5]
        T2 = np.eye(4)
        T2[:3, 3] = [0.6, 0.1, 0.4]

        q1 = pipeline.solve_ik_simplified(T1)
        q2 = pipeline.solve_ik_simplified(T2)

        # At least some joints should differ
        assert not np.allclose(q1, q2)


class TestTrajectoryGeneration:
    """Tests for full trajectory generation."""

    def test_generate_trajectory_returns_trajectory(self, pipeline, sample_detection):
        """Test generate_trajectory returns a GraspTrajectory."""
        traj = pipeline.generate_trajectory([sample_detection])
        assert traj is not None
        assert isinstance(traj, GraspTrajectory)
        assert len(traj.joint_names) == 4
        assert len(traj.waypoints) == 3  # pre, grasp, post

    def test_generate_trajectory_joint_names_match(self, pipeline, sample_detection, default_arm_joint_names):
        """Test trajectory joint names match arm joint names."""
        traj = pipeline.generate_trajectory([sample_detection])
        assert traj.joint_names == default_arm_joint_names

    def test_generate_trajectory_waypoint_structure(self, pipeline, sample_detection):
        """Test waypoint structure has required fields."""
        traj = pipeline.generate_trajectory([sample_detection])
        for wp in traj.waypoints:
            assert "time_from_start" in wp
            assert "positions" in wp
            assert len(wp["positions"]) == 4
            assert wp["time_from_start"] >= 0

    def test_generate_trajectory_timing(self, pipeline, sample_detection):
        """Test waypoint timing is monotonically increasing."""
        traj = pipeline.generate_trajectory([sample_detection])
        times = [wp["time_from_start"] for wp in traj.waypoints]
        assert times[0] == 0.0
        assert times[1] == 2.0
        assert times[2] == 4.0

    def test_generate_trajectory_marker_not_found(self, pipeline):
        """Test generate_trajectory returns None when marker not found."""
        detections = [
            MarkerDetection(marker_id=1, position=np.zeros(3), orientation=np.array([0,0,0,1.0])),
            MarkerDetection(marker_id=2, position=np.zeros(3), orientation=np.array([0,0,0,1.0])),
        ]
        traj = pipeline.generate_trajectory(detections)
        assert traj is None

    def test_generate_trajectory_empty_detections(self, pipeline):
        """Test generate_trajectory returns None for empty detections."""
        traj = pipeline.generate_trajectory([])
        assert traj is None

    def test_generate_trajectory_uses_first_detection(self, pipeline):
        """Test generate_trajectory uses first detection of target marker."""
        det1 = MarkerDetection(marker_id=42, position=np.array([0.5, 0.0, 0.5]), orientation=np.array([0,0,0,1.0]))
        det2 = MarkerDetection(marker_id=42, position=np.array([1.0, 0.0, 1.0]), orientation=np.array([0,0,0,1.0]))

        traj = pipeline.generate_trajectory([det1, det2])

        # Should use first detection (det1)
        # Check that pre-grasp pose matches det1's position transformed to base frame
        # camera_to_base translation is [0.1, 0.0, 0.3], so base_pos = cam_pos + cam_trans
        expected_pre_base = np.array([0.5, 0.0, 0.5]) + np.array([0.1, 0.0, 0.3]) - np.array([0.0, 0.0, 0.15])
        np.testing.assert_allclose(traj.pre_grasp_pose[:3, 3], expected_pre_base, atol=1e-3)


class TestTrajectoryToMsg:
    """Tests for trajectory to JointTrajectory message conversion."""

    def test_trajectory_to_msg_structure(self, pipeline, sample_detection):
        """Test conversion produces correct message structure."""
        traj = pipeline.generate_trajectory([sample_detection])
        msg_dict = pipeline.trajectory_to_joint_trajectory_msg(traj)

        assert "joint_names" in msg_dict
        assert "points" in msg_dict
        assert len(msg_dict["joint_names"]) == 4
        assert len(msg_dict["points"]) == 3

    def test_trajectory_to_msg_points_have_required_fields(self, pipeline, sample_detection):
        """Test each point has time_from_start, positions, velocities, accelerations."""
        traj = pipeline.generate_trajectory([sample_detection])
        msg_dict = pipeline.trajectory_to_joint_trajectory_msg(traj)

        for point in msg_dict["points"]:
            assert "time_from_start" in point
            assert "positions" in point
            assert "velocities" in point
            assert "accelerations" in point
            assert len(point["positions"]) == 4
            assert len(point["velocities"]) == 4
            assert len(point["accelerations"]) == 4
            # Velocities and accelerations should be zero (simplified)
            assert all(v == 0.0 for v in point["velocities"])
            assert all(a == 0.0 for a in point["accelerations"])


class TestDefaultHelpers:
    """Tests for default helper functions."""

    def test_create_default_camera_to_base(self):
        """Test default camera-to-base creation."""
        cam_to_base = create_default_camera_to_base()
        assert isinstance(cam_to_base, CameraToBaseTransform)
        assert cam_to_base.translation.shape == (3,)
        assert cam_to_base.rotation.shape == (3, 3)
        np.testing.assert_allclose(cam_to_base.translation, [0.1, 0.0, 0.3])
        np.testing.assert_allclose(cam_to_base.rotation, np.eye(3))

    def test_create_default_arm_joint_names(self):
        """Test default arm joint names."""
        names = create_default_arm_joint_names()
        assert len(names) == 4
        assert names == [
            "left_shoulder_pitch_joint",
            "left_elbow_joint",
            "right_shoulder_pitch_joint",
            "right_elbow_joint",
        ]


class TestGraspOffsets:
    """Tests for GraspOffsets dataclass."""

    def test_default_values(self):
        """Test default offset values."""
        offsets = GraspOffsets()
        assert offsets.approach_distance == 0.15
        assert offsets.grasp_depth == 0.02
        assert offsets.retreat_distance == 0.10

    def test_custom_values(self):
        """Test custom offset values."""
        offsets = GraspOffsets(
            approach_distance=0.2,
            grasp_depth=0.05,
            retreat_distance=0.15,
        )
        assert offsets.approach_distance == 0.2
        assert offsets.grasp_depth == 0.05
        assert offsets.retreat_distance == 0.15


class TestCameraToBaseTransform:
    """Tests for CameraToBaseTransform dataclass."""

    def test_creation(self):
        """Test transform creation."""
        trans = np.array([1.0, 2.0, 3.0])
        rot = np.eye(3)
        transform = CameraToBaseTransform(translation=trans, rotation=rot)
        np.testing.assert_allclose(transform.translation, trans)
        np.testing.assert_allclose(transform.rotation, rot)


class TestMarkerDetection:
    """Tests for MarkerDetection dataclass."""

    def test_creation(self):
        """Test detection creation."""
        det = MarkerDetection(
            marker_id=42,
            position=np.array([1.0, 2.0, 3.0]),
            orientation=np.array([0.0, 0.0, 0.7071, 0.7071]),
            confidence=0.95,
        )
        assert det.marker_id == 42
        np.testing.assert_allclose(det.position, [1.0, 2.0, 3.0])
        np.testing.assert_allclose(det.orientation, [0.0, 0.0, 0.7071, 0.7071])
        assert det.confidence == 0.95

    def test_default_confidence(self):
        """Test default confidence is 1.0."""
        det = MarkerDetection(
            marker_id=42,
            position=np.zeros(3),
            orientation=np.array([0.0, 0.0, 0.0, 1.0]),
        )
        assert det.confidence == 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])