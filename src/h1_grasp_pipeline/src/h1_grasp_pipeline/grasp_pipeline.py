"""Pure logic for grasp pipeline — perception to trajectory generation.

This module contains the GraspPipeline class which converts ArUco marker detections
into arm joint trajectories for grasping. No ROS dependencies in core logic.

MoveIt2 integration is provided via MoveIt2Planner class (optional ROS dependency).
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple, Callable, Any
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

    Optional MoveIt2 integration: pass a moveit_planner callable that takes
    (planning_group, target_pose, current_joint_state) and returns trajectory points.
    """

    def __init__(
        self,
        camera_to_base: CameraToBaseTransform,
        arm_joint_names: List[str],
        grasp_offsets: Optional[GraspOffsets] = None,
        target_marker_id: int = 0,
        moveit_planner: Optional[Callable] = None,
        planning_group: str = "left_arm",
    ):
        """Initialize the grasp pipeline.

        Args:
            camera_to_base: Fixed transform from camera to base frame
            arm_joint_names: List of 4 arm joint names (left_shoulder_pitch, left_elbow, right_shoulder_pitch, right_elbow)
            grasp_offsets: Approach/grasp/retreat offsets
            target_marker_id: Marker ID to grasp
            moveit_planner: Optional callable for MoveIt2 planning.
                Signature: (planning_group: str, target_pose: np.ndarray, current_js: dict) -> List[dict]
                Each returned dict: {"time_from_start": float, "positions": List[float]}
            planning_group: MoveIt2 planning group name ("left_arm", "right_arm", "both_arms")
        """
        self.camera_to_base = camera_to_base
        self.arm_joint_names = arm_joint_names
        self.grasp_offsets = grasp_offsets or GraspOffsets()
        self.target_marker_id = target_marker_id
        self.moveit_planner = moveit_planner
        self.planning_group = planning_group

        if len(arm_joint_names) != 4:
            raise ValueError(f"Expected 4 arm joint names, got {len(arm_joint_names)}")

        valid_groups = ["left_arm", "right_arm", "both_arms"]
        if planning_group not in valid_groups:
            raise ValueError(f"planning_group must be one of {valid_groups}, got {planning_group}")

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

    def _solve_ik_for_group(self, target_T: np.ndarray, group: str) -> np.ndarray:
        """Solve IK for a specific planning group.

        Args:
            target_T: 4x4 target transform in base frame
            group: Planning group ("left_arm", "right_arm", "both_arms")

        Returns:
            Array of joint positions matching the group's joint count
        """
        if group == "left_arm":
            # Return 7 joints for left arm
            pos = target_T[:3, 3]
            x, y, z = pos
            # Simplified 7-DOF IK for left arm
            q = np.zeros(7)
            q[0] = math.atan2(-y, z + 0.5) * 0.5  # shoulder_pitch
            q[1] = 0.0  # shoulder_roll
            q[2] = 0.0  # shoulder_yaw
            q[3] = math.atan2(z, 0.3) * 0.5       # elbow
            q[4] = 0.0  # wrist_roll
            q[5] = 0.0  # wrist_pitch
            q[6] = 0.0  # wrist_yaw
            return np.clip(q, -3.14, 3.14)
        elif group == "right_arm":
            # Return 7 joints for right arm
            pos = target_T[:3, 3]
            x, y, z = pos
            q = np.zeros(7)
            q[0] = math.atan2(y, z + 0.5) * 0.5   # shoulder_pitch
            q[1] = 0.0  # shoulder_roll
            q[2] = 0.0  # shoulder_yaw
            q[3] = math.atan2(z, 0.3) * 0.5       # elbow
            q[4] = 0.0  # wrist_roll
            q[5] = 0.0  # wrist_pitch
            q[6] = 0.0  # wrist_yaw
            return np.clip(q, -3.14, 3.14)
        else:  # both_arms
            # Return 14 joints for both arms
            left_q = self._solve_ik_for_group(target_T, "left_arm")
            right_q = self._solve_ik_for_group(target_T, "right_arm")
            return np.concatenate([left_q, right_q])

    def generate_trajectory(
        self,
        detections: List[MarkerDetection],
        stand_pose: Optional[dict] = None,
        current_joint_state: Optional[dict] = None,
    ) -> Optional[GraspTrajectory]:
        """Generate grasp trajectory from detections.

        Args:
            detections: List of marker detections in camera frame
            stand_pose: Optional dict of joint_name -> position for non-arm joints
            current_joint_state: Optional dict of joint_name -> position for MoveIt2 start state

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

        # Step 4: Solve IK for each pose
        if self.moveit_planner is not None:
            # Use MoveIt2 planner
            try:
                waypoints = self._plan_with_moveit(T_pre, T_grasp, T_post, current_joint_state)
            except Exception as e:
                # Fallback to heuristic IK
                print(f"MoveIt2 planning failed, falling back to heuristic IK: {e}")
                waypoints = self._plan_with_heuristic(T_pre, T_grasp, T_post)
        else:
            # Use heuristic IK
            waypoints = self._plan_with_heuristic(T_pre, T_grasp, T_post)

        return GraspTrajectory(
            joint_names=self.arm_joint_names.copy(),
            waypoints=waypoints,
            pre_grasp_pose=T_pre,
            grasp_pose=T_grasp,
            post_grasp_pose=T_post,
        )

    def _plan_with_heuristic(
        self,
        T_pre: np.ndarray,
        T_grasp: np.ndarray,
        T_post: np.ndarray
    ) -> List[dict]:
        """Plan trajectory using heuristic IK (fallback)."""
        q_pre = self.solve_ik_simplified(T_pre)
        q_grasp = self.solve_ik_simplified(T_grasp)
        q_post = self.solve_ik_simplified(T_post)

        t_pre = 0.0
        t_grasp = 2.0
        t_post = 4.0

        return [
            {"time_from_start": t_pre, "positions": q_pre.tolist()},
            {"time_from_start": t_grasp, "positions": q_grasp.tolist()},
            {"time_from_start": t_post, "positions": q_post.tolist()},
        ]

    def _plan_with_moveit(
        self,
        T_pre: np.ndarray,
        T_grasp: np.ndarray,
        T_post: np.ndarray,
        current_joint_state: Optional[dict] = None,
    ) -> List[dict]:
        """Plan trajectory using MoveIt2 planner callable.

        Args:
            T_pre: Pre-grasp pose (4x4)
            T_grasp: Grasp pose (4x4)
            T_post: Post-grasp pose (4x4)
            current_joint_state: Current joint positions dict for start state

        Returns:
            List of waypoint dicts with time_from_start and positions
        """
        if self.moveit_planner is None:
            raise RuntimeError("MoveIt2 planner not configured")

        # Call the planner for each pose
        # The planner should return a full trajectory from current state to target
        # For simplicity, we plan to grasp pose and extract waypoints
        target_pose = T_grasp
        current_js = current_joint_state or {}

        trajectory = self.moveit_planner(
            planning_group=self.planning_group,
            target_pose=target_pose,
            current_joint_state=current_js,
        )

        if not trajectory:
            raise RuntimeError("MoveIt2 planner returned empty trajectory")

        # Ensure we have pre-grasp, grasp, post-grasp waypoints
        # If planner returns full trajectory, use it directly
        # Otherwise, interpolate
        if len(trajectory) >= 3:
            # Use first, middle, last as pre, grasp, post
            t_pre = 0.0
            t_grasp = trajectory[-1]["time_from_start"] * 0.5
            t_post = trajectory[-1]["time_from_start"]
            return [
                {"time_from_start": t_pre, "positions": trajectory[0]["positions"]},
                {"time_from_start": t_grasp, "positions": trajectory[len(trajectory)//2]["positions"]},
                {"time_from_start": t_post, "positions": trajectory[-1]["positions"]},
            ]
        else:
            # Use what we have and interpolate
            return trajectory

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


class MoveIt2Planner:
    """MoveIt2 planner wrapper for ROS 2 node integration.

    This class provides a callable that can be passed to GraspPipeline.moveit_planner.
    It uses moveit_msgs/srv/GetMotionPlan service to plan trajectories.

    Usage in ROS node:
        planner = MoveIt2Planner(node)
        pipeline = GraspPipeline(..., moveit_planner=planner, planning_group="left_arm")
    """

    def __init__(self, node, planning_timeout: float = 5.0):
        """Initialize MoveIt2 planner.

        Args:
            node: ROS 2 node (for service clients, logger)
            planning_timeout: Timeout for planning service calls in seconds
        """
        self.node = node
        self.planning_timeout = planning_timeout
        self._moveit_available = False
        self._service_client = None
        self._action_client = None
        self._init_moveit_clients()

    def _init_moveit_clients(self):
        """Initialize MoveIt2 service and action clients."""
        try:
            from moveit_msgs.srv import GetMotionPlan
            from moveit_msgs.action import MoveGroup
            import rclpy
            from rclpy.action import ActionClient

            # Try service first
            self._service_client = self.node.create_client(
                GetMotionPlan,
                "/plan_kinematic_path"
            )

            # Also try action client for MoveGroup
            self._action_client = ActionClient(
                self.node,
                MoveGroup,
                "/move_action"
            )

            self._moveit_available = True
            self.node.get_logger().info("MoveIt2 planning clients initialized")
        except ImportError as e:
            self.node.get_logger().warn(f"MoveIt2 messages not available: {e}")
            self._moveit_available = False
        except Exception as e:
            self.node.get_logger().warn(f"Failed to initialize MoveIt2 clients: {e}")
            self._moveit_available = False

    def is_available(self) -> bool:
        """Check if MoveIt2 is available."""
        return self._moveit_available

    def __call__(
        self,
        planning_group: str,
        target_pose: np.ndarray,
        current_joint_state: dict,
    ) -> List[dict]:
        """Plan trajectory using MoveIt2.

        Args:
            planning_group: MoveIt2 planning group name
            target_pose: 4x4 target transform in base frame
            current_joint_state: Dict of joint_name -> position

        Returns:
            List of waypoint dicts with time_from_start and positions
        """
        if not self._moveit_available:
            raise RuntimeError("MoveIt2 not available")

        # Try service first
        if self._service_client and self._service_client.service_is_ready():
            return self._plan_via_service(planning_group, target_pose, current_joint_state)

        # Fallback to action
        if self._action_client:
            return self._plan_via_action(planning_group, target_pose, current_joint_state)

        raise RuntimeError("No MoveIt2 planning interface available")

    def _plan_via_service(
        self,
        planning_group: str,
        target_pose: np.ndarray,
        current_joint_state: dict,
    ) -> List[dict]:
        """Plan via GetMotionPlan service."""
        from moveit_msgs.srv import GetMotionPlan
        from moveit_msgs.msg import MotionPlanRequest, Constraints, PositionConstraint, OrientationConstraint
        from shape_msgs.msg import SolidPrimitive
        from geometry_msgs.msg import Pose
        import rclpy

        request = GetMotionPlan.Request()
        request.motion_plan_request = MotionPlanRequest()
        request.motion_plan_request.group_name = planning_group
        request.motion_plan_request.num_planning_attempts = 3
        request.motion_plan_request.allowed_planning_time = self.planning_timeout
        request.motion_plan_request.max_velocity_scaling_factor = 0.5
        request.motion_plan_request.max_acceleration_scaling_factor = 0.5

        # Set start state from current_joint_state
        if current_joint_state:
            from moveit_msgs.msg import RobotState
            from sensor_msgs.msg import JointState
            start_state = RobotState()
            start_state.joint_state = JointState()
            start_state.joint_state.name = list(current_joint_state.keys())
            start_state.joint_state.position = list(current_joint_state.values())
            request.motion_plan_request.start_state = start_state

        # Set goal constraints from target_pose
        constraints = Constraints()
        pos_constraint = PositionConstraint()
        pos_constraint.header.frame_id = "h1_ign"
        pos_constraint.link_name = self._get_end_effector_link(planning_group)
        pos_constraint.constraint_region.primitives.append(SolidPrimitive(
            type=SolidPrimitive.SPHERE,
            dimensions=[0.01]  # 1cm tolerance
        ))
        pos_constraint.constraint_region.primitive_poses.append(self._transform_to_pose(target_pose))
        pos_constraint.weight = 1.0
        constraints.position_constraints.append(pos_constraint)

        orient_constraint = OrientationConstraint()
        orient_constraint.header.frame_id = "h1_ign"
        orient_constraint.link_name = self._get_end_effector_link(planning_group)
        orient_constraint.orientation = self._transform_to_pose(target_pose).orientation
        orient_constraint.absolute_x_axis_tolerance = 0.1
        orient_constraint.absolute_y_axis_tolerance = 0.1
        orient_constraint.absolute_z_axis_tolerance = 0.1
        orient_constraint.weight = 1.0
        constraints.orientation_constraints.append(orient_constraint)

        request.motion_plan_request.goal_constraints.append(constraints)

        # Call service
        future = self._service_client.call_async(request)
        rclpy.spin_until_future_complete(self.node, future, timeout_sec=self.planning_timeout)

        if future.result() is None:
            raise RuntimeError("MoveIt2 planning service call failed or timed out")

        response = future.result()
        if response.motion_plan_response.error_code.val != 1:  # SUCCESS
            raise RuntimeError(f"MoveIt2 planning failed with error code: {response.motion_plan_response.error_code.val}")

        # Extract trajectory
        trajectory = response.motion_plan_response.trajectory
        return self._extract_waypoints(trajectory)

    def _plan_via_action(
        self,
        planning_group: str,
        target_pose: np.ndarray,
        current_joint_state: dict,
    ) -> List[dict]:
        """Plan via MoveGroup action."""
        from moveit_msgs.action import MoveGroup
        from moveit_msgs.msg import MotionPlanRequest, Constraints, PositionConstraint, OrientationConstraint
        from shape_msgs.msg import SolidPrimitive
        import rclpy
        from rclpy.action import ActionClient

        goal_msg = MoveGroup.Goal()
        goal_msg.request = MotionPlanRequest()
        goal_msg.request.group_name = planning_group
        goal_msg.request.num_planning_attempts = 3
        goal_msg.request.allowed_planning_time = self.planning_timeout
        goal_msg.request.max_velocity_scaling_factor = 0.5
        goal_msg.request.max_acceleration_scaling_factor = 0.5

        # Set start state
        if current_joint_state:
            from moveit_msgs.msg import RobotState
            from sensor_msgs.msg import JointState
            start_state = RobotState()
            start_state.joint_state = JointState()
            start_state.joint_state.name = list(current_joint_state.keys())
            start_state.joint_state.position = list(current_joint_state.values())
            goal_msg.request.start_state = start_state

        # Set goal constraints
        constraints = Constraints()
        pos_constraint = PositionConstraint()
        pos_constraint.header.frame_id = "h1_ign"
        pos_constraint.link_name = self._get_end_effector_link(planning_group)
        pos_constraint.constraint_region.primitives.append(SolidPrimitive(
            type=SolidPrimitive.SPHERE,
            dimensions=[0.01]
        ))
        pos_constraint.constraint_region.primitive_poses.append(self._transform_to_pose(target_pose))
        pos_constraint.weight = 1.0
        constraints.position_constraints.append(pos_constraint)

        orient_constraint = OrientationConstraint()
        orient_constraint.header.frame_id = "h1_ign"
        orient_constraint.link_name = self._get_end_effector_link(planning_group)
        orient_constraint.orientation = self._transform_to_pose(target_pose).orientation
        orient_constraint.absolute_x_axis_tolerance = 0.1
        orient_constraint.absolute_y_axis_tolerance = 0.1
        orient_constraint.absolute_z_axis_tolerance = 0.1
        orient_constraint.weight = 1.0
        constraints.orientation_constraints.append(orient_constraint)

        goal_msg.request.goal_constraints.append(constraints)

        # Send goal
        send_goal_future = self._action_client.send_goal_async(goal_msg)
        rclpy.spin_until_future_complete(self.node, send_goal_future, timeout_sec=self.planning_timeout)

        goal_handle = send_goal_future.result()
        if not goal_handle.accepted:
            raise RuntimeError("MoveIt2 action goal rejected")

        # Get result
        get_result_future = goal_handle.get_result_async()
        rclpy.spin_until_future_complete(self.node, get_result_future, timeout_sec=self.planning_timeout)

        result = get_result_future.result()
        if result.result.error_code.val != 1:
            raise RuntimeError(f"MoveIt2 action planning failed: {result.result.error_code.val}")

        return self._extract_waypoints(result.result.planned_trajectory)

    def _get_end_effector_link(self, planning_group: str) -> str:
        """Get end effector link name for planning group."""
        if planning_group == "left_arm":
            return "left_wrist_yaw_link"
        elif planning_group == "right_arm":
            return "right_wrist_yaw_link"
        else:
            return "left_wrist_yaw_link"  # Default for both_arms

    def _transform_to_pose(self, T: np.ndarray) -> "Pose":
        """Convert 4x4 transform to geometry_msgs/Pose."""
        from geometry_msgs.msg import Pose, Quaternion
        pos = T[:3, 3]
        R_mat = T[:3, :3]
        quat = R.from_matrix(R_mat).as_quat()  # (x, y, z, w)
        pose = Pose()
        pose.position.x = float(pos[0])
        pose.position.y = float(pos[1])
        pose.position.z = float(pos[2])
        pose.orientation = Quaternion(x=float(quat[0]), y=float(quat[1]), z=float(quat[2]), w=float(quat[3]))
        return pose

    def _extract_waypoints(self, trajectory) -> List[dict]:
        """Extract waypoints from moveit_msgs/RobotTrajectory."""
        waypoints = []
        joint_trajectory = trajectory.joint_trajectory
        joint_names = list(joint_trajectory.joint_names)

        for point in joint_trajectory.points:
            wp = {
                "time_from_start": point.time_from_start.sec + point.time_from_start.nanosec * 1e-9,
                "positions": list(point.positions),
            }
            waypoints.append(wp)

        return waypoints


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
    """Default arm joint names from H1 URDF (4-DOF simplified)."""
    return [
        "left_shoulder_pitch_joint",
        "left_elbow_joint",
        "right_shoulder_pitch_joint",
        "right_elbow_joint",
    ]


def create_full_arm_joint_names(group: str = "both_arms") -> List[str]:
    """Full arm joint names from H1 URDF (7-DOF per arm).

    Args:
        group: "left_arm", "right_arm", or "both_arms"

    Returns:
        List of joint names for the specified group
    """
    left_arm = [
        "left_shoulder_pitch_joint",
        "left_shoulder_roll_joint",
        "left_shoulder_yaw_joint",
        "left_elbow_joint",
        "left_wrist_roll_joint",
        "left_wrist_pitch_joint",
        "left_wrist_yaw_joint",
    ]
    right_arm = [
        "right_shoulder_pitch_joint",
        "right_shoulder_roll_joint",
        "right_shoulder_yaw_joint",
        "right_elbow_joint",
        "right_wrist_roll_joint",
        "right_wrist_pitch_joint",
        "right_wrist_yaw_joint",
    ]

    if group == "left_arm":
        return left_arm
    elif group == "right_arm":
        return right_arm
    else:
        return left_arm + right_arm


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