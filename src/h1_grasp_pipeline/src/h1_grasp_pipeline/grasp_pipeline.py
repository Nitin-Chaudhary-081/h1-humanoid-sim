"""Pure logic for grasp pipeline — perception to trajectory generation.

This module contains the GraspPipeline class which converts ArUco marker detections
into arm joint trajectories for grasping. No ROS dependencies.
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple
import math

import numpy as np
from scipy.spatial.transform import Rotation as R


@dataclass
class GraspOffsets:
    """Offsets for pre-grasp, grasp, and post-grasp poses relative to marker."""
    approach_distance: float = 0.15   # Distance to approach from (along -Z of marker)
    grasp_depth: float = 0.02         # How far to move from pre-grasp to grasp (along +Z)
    retreat_distance: float = 0.10    # Distance to retreat after grasp (along +Z)


@dataclass
class CameraToBaseTransform:
    """Fixed transform from camera frame to robot base frame (h1_ign)."""
    translation: np.ndarray      # shape (3,) - x, y, z in meters
    rotation: np.ndarray         # shape (3, 3) - rotation matrix


@dataclass
class MarkerDetection:
    """Single marker detection with pose in camera frame."""
    marker_id: int
    position: np.ndarray         # shape (3,) - x, y, z in camera frame
    orientation: np.ndarray      # shape (4,) - quaternion (x, y, z, w) in camera frame
    confidence: float = 1.0


@dataclass
class GraspTrajectory:
    """Generated trajectory for grasping."""
    joint_names: List[str]
    waypoints: List[dict]        # Each: {"time_from_start": float, "positions": List[float]}
    pre_grasp_pose: np.ndarray   # 4x4 transform matrix in base frame
    grasp_pose: np.ndarray       # 4x4 transform matrix in base frame
    post_grasp_pose: np.ndarray  # 4x4 transform matrix in base frame


class GraspPipeline:
    """Pure logic pipeline: PerceptionFrame -> grasp trajectory.

    Steps:
    1. Filter detections for target marker_id
    2. Transform marker pose from camera_frame -> base_frame
    3. Compute pre-grasp, grasp, post-grasp poses
    4. Generate Cartesian waypoints (simplified: direct joint space interpolation)
    5. Output trajectory_msgs/JointTrajectory compatible structure
    """

    def __init__(
        self,
        camera_to_base: CameraToBaseTransform,
        arm_joint_names: List[str],
        grasp_offsets: Optional[GraspOffsets] = None,
        target_marker_id: int = 0,
    ):
        """Initialize the grasp pipeline.

        Args:
            camera_to_base: Fixed transform from camera to base frame
            arm_joint_names: List of 4 arm joint names (left_shoulder_pitch, left_elbow, right_shoulder_pitch, right_elbow)
            grasp_offsets: Approach/grasp/retreat offsets
            target_marker_id: Marker ID to grasp
        """
        self.camera_to_base = camera_to_base
        self.arm_joint_names = arm_joint_names
        self.grasp_offsets = grasp_offsets or GraspOffsets()
        self.target_marker_id = target_marker_id

        if len(arm_joint_names) != 4:
            raise ValueError(f"Expected 4 arm joint names, got {len(arm_joint_names)}")

    def filter_detections(self, detections: List[MarkerDetection]) -> List[MarkerDetection]:
        """Filter detections for target marker ID."""
        return [d for d in detections if d.marker_id == self.target_marker_id]

    def transform_pose_camera_to_base(
        self,
        position_cam: np.ndarray,
        orientation_cam: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Transform pose from camera frame to base frame.

        Args:
            position_cam: Position in camera frame (3,)
            orientation_cam: Quaternion in camera frame (x, y, z, w)

        Returns:
            Tuple of (position_base, orientation_base) in base frame
        """
        # Camera to base transform
        T_cb = np.eye(4)
        T_cb[:3, :3] = self.camera_to_base.rotation
        T_cb[:3, 3] = self.camera_to_base.translation

        # Marker pose in camera frame
        T_cm = np.eye(4)
        T_cm[:3, :3] = R.from_quat(orientation_cam).as_matrix()
        T_cm[:3, 3] = position_cam

        # Marker pose in base frame: T_bm = T_bc * T_cm = T_cb * T_cm
        T_bm = T_cb @ T_cm

        position_base = T_bm[:3, 3]
        orientation_base = R.from_matrix(T_bm[:3, :3]).as_quat()  # (x, y, z, w)

        return position_base, orientation_base

    def compute_grasp_poses(
        self,
        marker_position_base: np.ndarray,
        marker_orientation_base: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Compute pre-grasp, grasp, and post-grasp poses in base frame.

        The marker's Z-axis points outward from the marker surface.
        - Pre-grasp: approach_distance along -Z (back from marker)
        - Grasp: at marker origin (grasp_depth along +Z from pre-grasp)
        - Post-grasp: retreat_distance along +Z from grasp

        Args:
            marker_position_base: Marker position in base frame (3,)
            marker_orientation_base: Marker quaternion in base frame (x, y, z, w)

        Returns:
            Tuple of (pre_grasp_T, grasp_T, post_grasp_T) as 4x4 transform matrices
        """
        R_marker = R.from_quat(marker_orientation_base).as_matrix()
        z_axis = R_marker[:, 2]  # Z-axis of marker in base frame

        # Grasp pose = marker pose
        T_grasp = np.eye(4)
        T_grasp[:3, :3] = R_marker
        T_grasp[:3, 3] = marker_position_base

        # Pre-grasp: back along -Z by approach_distance
        T_pre = T_grasp.copy()
        T_pre[:3, 3] = marker_position_base - z_axis * self.grasp_offsets.approach_distance

        # Post-grasp: forward along +Z by retreat_distance from grasp
        T_post = T_grasp.copy()
        T_post[:3, 3] = marker_position_base + z_axis * self.grasp_offsets.retreat_distance

        return T_pre, T_grasp, T_post

    def solve_ik_simplified(self, target_T: np.ndarray) -> np.ndarray:
        """Simplified IK for 4-DOF arm (returns joint positions for a target pose).

        This is a PLACEHOLDER IK - in reality would use MoveIt2 or analytical IK.
        For testing, we map the target position to joint angles using a simple heuristic:
        - Use X/Y/Z to determine shoulder/elbow angles for left and right arms
        - This is purely for generating testable trajectory structure

        Args:
            target_T: 4x4 target transform in base frame

        Returns:
            Array of 4 joint positions [left_shoulder_pitch, left_elbow, right_shoulder_pitch, right_elbow]
        """
        pos = target_T[:3, 3]
        x, y, z = pos

        # Heuristic: map position to joint angles
        # Left arm: positive Y -> left shoulder pitch, Z -> elbow
        # Right arm: negative Y -> right shoulder pitch, Z -> elbow
        # This is a simplified geometric approximation for testing

        left_shoulder_pitch = math.atan2(-y, z + 0.5) * 0.5  # Simplified
        left_elbow = math.atan2(z, 0.3) * 0.5                # Simplified
        right_shoulder_pitch = math.atan2(y, z + 0.5) * 0.5  # Simplified
        right_elbow = math.atan2(z, 0.3) * 0.5               # Simplified

        # Clamp to reasonable joint limits
        left_shoulder_pitch = np.clip(left_shoulder_pitch, -2.0, 2.0)
        left_elbow = np.clip(left_elbow, -2.0, 2.0)
        right_shoulder_pitch = np.clip(right_shoulder_pitch, -2.0, 2.0)
        right_elbow = np.clip(right_elbow, -2.0, 2.0)

        return np.array([left_shoulder_pitch, left_elbow, right_shoulder_pitch, right_elbow])

    def generate_trajectory(
        self,
        detections: List[MarkerDetection],
        stand_pose: Optional[dict] = None
    ) -> Optional[GraspTrajectory]:
        """Generate grasp trajectory from detections.

        Args:
            detections: List of marker detections in camera frame
            stand_pose: Optional dict of joint_name -> position for non-arm joints

        Returns:
            GraspTrajectory or None if target marker not found
        """
        # Step 1: Filter for target marker
        filtered = self.filter_detections(detections)
        if not filtered:
            return None

        # Use first detection of target marker
        det = filtered[0]

        # Step 2: Transform to base frame
        pos_base, orient_base = self.transform_pose_camera_to_base(
            det.position, det.orientation
        )

        # Step 3: Compute grasp poses
        T_pre, T_grasp, T_post = self.compute_grasp_poses(pos_base, orient_base)

        # Step 4: Solve IK for each pose (simplified)
        q_pre = self.solve_ik_simplified(T_pre)
        q_grasp = self.solve_ik_simplified(T_grasp)
        q_post = self.solve_ik_simplified(T_post)

        # Step 5: Generate waypoints with timing
        # Pre-grasp -> Grasp -> Post-grasp
        t_pre = 0.0
        t_grasp = 2.0   # 2 seconds to approach and grasp
        t_post = 4.0    # 2 seconds to retreat

        waypoints = [
            {
                "time_from_start": t_pre,
                "positions": q_pre.tolist(),
            },
            {
                "time_from_start": t_grasp,
                "positions": q_grasp.tolist(),
            },
            {
                "time_from_start": t_post,
                "positions": q_post.tolist(),
            },
        ]

        return GraspTrajectory(
            joint_names=self.arm_joint_names.copy(),
            waypoints=waypoints,
            pre_grasp_pose=T_pre,
            grasp_pose=T_grasp,
            post_grasp_pose=T_post,
        )

    def trajectory_to_joint_trajectory_msg(self, traj: GraspTrajectory) -> dict:
        """Convert GraspTrajectory to a dict compatible with trajectory_msgs/JointTrajectory.

        Returns dict with keys: joint_names, points (list of dicts with time_from_start, positions)
        """
        points = []
        for wp in traj.waypoints:
            points.append({
                "time_from_start": wp["time_from_start"],
                "positions": wp["positions"],
                "velocities": [0.0] * len(self.arm_joint_names),
                "accelerations": [0.0] * len(self.arm_joint_names),
            })

        return {
            "joint_names": traj.joint_names,
            "points": points,
        }


def create_default_camera_to_base() -> CameraToBaseTransform:
    """Create default camera-to-base transform (placeholder values).

    In reality, this comes from URDF / TF. Typical H1 head camera:
    - Camera mounted on head, ~0.3m above base, 0.1m forward
    - Looking forward and slightly down
    """
    # Identity rotation (camera aligned with base) - placeholder
    rotation = np.eye(3)
    # Translation: camera at (0.1, 0, 0.3) in base frame
    translation = np.array([0.1, 0.0, 0.3])

    return CameraToBaseTransform(translation=translation, rotation=rotation)


def create_default_arm_joint_names() -> List[str]:
    """Default arm joint names from H1 URDF."""
    return [
        "left_shoulder_pitch_joint",
        "left_elbow_joint",
        "right_shoulder_pitch_joint",
        "right_elbow_joint",
    ]


if __name__ == "__main__":
    # Quick self-test
    cam_to_base = create_default_camera_to_base()
    pipeline = GraspPipeline(
        camera_to_base=cam_to_base,
        arm_joint_names=create_default_arm_joint_names(),
        target_marker_id=42,
    )

    # Mock detection: marker at (0.5, 0, 0.5) in camera frame, no rotation
    det = MarkerDetection(
        marker_id=42,
        position=np.array([0.5, 0.0, 0.5]),
        orientation=np.array([0.0, 0.0, 0.0, 1.0]),
    )

    traj = pipeline.generate_trajectory([det])
    if traj:
        print("Generated trajectory:")
        print(f"  Joint names: {traj.joint_names}")
        print(f"  Waypoints: {len(traj.waypoints)}")
        for i, wp in enumerate(traj.waypoints):
            print(f"    t={wp['time_from_start']:.1f}s: {wp['positions']}")
    else:
        print("No trajectory generated (marker not found)")