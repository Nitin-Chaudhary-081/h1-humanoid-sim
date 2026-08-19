"""ROS 2 node for grasp execution — action server + perception subscriber + trajectory follower client."""

import numpy as np
from typing import Optional

import rclpy
from rclpy.action import ActionClient, ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.duration import Duration
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from rclpy.time import Time

from control_msgs.action import FollowJointTrajectory
from h1_interfaces.action import GraspExecute
from h1_interfaces.msg import PerceptionFrame
from geometry_msgs.msg import Pose, Point, Quaternion
from std_msgs.msg import Header
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint

from h1_grasp_pipeline.grasp_pipeline import (
    GraspPipeline,
    GraspOffsets,
    CameraToBaseTransform,
    MarkerDetection,
    create_default_camera_to_base,
    create_default_arm_joint_names,
)


SENSOR_QOS = QoSProfile(
    depth=10,
    reliability=ReliabilityPolicy.BEST_EFFORT,
    history=HistoryPolicy.KEEP_LAST,
)


class GraspNode(Node):
    """ROS 2 node for grasp pipeline execution.

    Subscribes: /h1/perception/detections (PerceptionFrame)
    Action Server: /h1/grasp/execute (GraspExecute)
    Action Client: /h1/moveit/follow_trajectory (FollowJointTrajectory)
    """

    def __init__(self):
        super().__init__("h1_grasp_node")

        # Declare parameters
        self.declare_parameter("camera_frame", "camera_link")
        self.declare_parameter("base_frame", "base_link")
        self.declare_parameter("target_marker_id", 42)
        self.declare_parameter("grasp_offset_xyz", [0.0, 0.0, 0.0])  # Additional offset from marker origin
        self.declare_parameter("approach_distance", 0.15)
        self.declare_parameter("grasp_depth", 0.02)
        self.declare_parameter("retreat_distance", 0.10)
        self.declare_parameter("camera_to_base_translation", [0.1, 0.0, 0.3])
        self.declare_parameter("camera_to_base_rotation", [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0])  # 3x3 row-major
        self.declare_parameter("arm_joint_names", create_default_arm_joint_names())
        self.declare_parameter("follow_trajectory_timeout", 30.0)

        if self.has_parameter("use_sim_time"):
            self.set_parameters([rclpy.parameter.Parameter("use_sim_time", value=True)])

        # Load parameters
        self.camera_frame = self.get_parameter("camera_frame").get_parameter_value().string_value
        self.base_frame = self.get_parameter("base_frame").get_parameter_value().string_value
        self.target_marker_id = self.get_parameter("target_marker_id").get_parameter_value().integer_value
        grasp_offset_xyz = self.get_parameter("grasp_offset_xyz").get_parameter_value().double_array_value
        approach_distance = self.get_parameter("approach_distance").get_parameter_value().double_value
        grasp_depth = self.get_parameter("grasp_depth").get_parameter_value().double_value
        retreat_distance = self.get_parameter("retreat_distance").get_parameter_value().double_value
        cam_trans = self.get_parameter("camera_to_base_translation").get_parameter_value().double_array_value
        cam_rot = self.get_parameter("camera_to_base_rotation").get_parameter_value().double_array_value
        self.arm_joint_names = self.get_parameter("arm_joint_names").get_parameter_value().string_array_value
        self.follow_timeout = self.get_parameter("follow_trajectory_timeout").get_parameter_value().double_value

        # Build camera-to-base transform
        if len(cam_trans) != 3:
            raise ValueError("camera_to_base_translation must have 3 elements")
        if len(cam_rot) != 9:
            raise ValueError("camera_to_base_rotation must have 9 elements (3x3 row-major)")

        camera_to_base = CameraToBaseTransform(
            translation=np.array(cam_trans, dtype=np.float64),
            rotation=np.array(cam_rot, dtype=np.float64).reshape(3, 3),
        )

        # Grasp offsets
        grasp_offsets = GraspOffsets(
            approach_distance=approach_distance,
            grasp_depth=grasp_depth,
            retreat_distance=retreat_distance,
        )

        # Initialize pipeline
        self.pipeline = GraspPipeline(
            camera_to_base=camera_to_base,
            arm_joint_names=list(self.arm_joint_names),
            grasp_offsets=grasp_offsets,
            target_marker_id=self.target_marker_id,
        )

        # Latest perception frame
        self._latest_frame: Optional[PerceptionFrame] = None

        # Perception subscriber
        self._perception_sub = self.create_subscription(
            PerceptionFrame,
            "/h1/perception/detections",
            self._perception_callback,
            SENSOR_QOS,
        )

        # FollowJointTrajectory action client
        self._follow_client = ActionClient(
            self,
            FollowJointTrajectory,
            "/h1/moveit/follow_trajectory",
            callback_group=ReentrantCallbackGroup(),
        )

        # GraspExecute action server
        self._grasp_server = ActionServer(
            self,
            GraspExecute,
            "/h1/grasp/execute",
            execute_callback=self._execute_grasp_callback,
            goal_callback=self._goal_callback,
            cancel_callback=self._cancel_callback,
            callback_group=ReentrantCallbackGroup(),
        )

        self.get_logger().info(
            f"h1_grasp_node started: target_marker_id={self.target_marker_id}, "
            f"approach={approach_distance}m, grasp_depth={grasp_depth}m, retreat={retreat_distance}m"
        )

    def _perception_callback(self, msg: PerceptionFrame):
        """Store latest perception frame."""
        self._latest_frame = msg

    def _goal_callback(self, goal_request):
        """Validate grasp goal."""
        if goal_request.target_marker_id < 0:
            self.get_logger().warn(f"Rejecting goal: invalid marker_id {goal_request.target_marker_id}")
            return GoalResponse.REJECT

        if goal_request.pregrasp_offset < 0.0 or goal_request.grasp_depth < 0.0:
            self.get_logger().warn(f"Rejecting goal: negative offsets")
            return GoalResponse.REJECT

        self.get_logger().info(f"Accepting grasp goal for marker {goal_request.target_marker_id}")
        return GoalResponse.ACCEPT

    def _cancel_callback(self, goal_handle):
        """Handle goal cancellation."""
        self.get_logger().info("Cancel requested for grasp goal")
        return CancelResponse.ACCEPT

    def _execute_grasp_callback(self, goal_handle):
        """Execute the grasp action."""
        goal = goal_handle.request

        # Override pipeline params for this goal
        self.pipeline.target_marker_id = goal.target_marker_id
        self.pipeline.grasp_offsets.approach_distance = goal.pregrasp_offset
        self.pipeline.grasp_offsets.grasp_depth = goal.grasp_depth
        # Note: retreat_distance not in goal, use default

        # Check for latest perception
        if self._latest_frame is None:
            self.get_logger().error("No perception data received yet")
            goal_handle.abort()
            return GraspExecute.Result(success=False, trajectory=JointTrajectory(), message="No perception data")

        # Convert PerceptionFrame to MarkerDetection list
        detections = []
        for pd in self._latest_frame.detections:
            det = MarkerDetection(
                marker_id=pd.marker_id,
                position=np.array([pd.pose.position.x, pd.pose.position.y, pd.pose.position.z]),
                orientation=np.array([pd.pose.orientation.x, pd.pose.orientation.y, pd.pose.orientation.z, pd.pose.orientation.w]),
                confidence=pd.confidence,
            )
            detections.append(det)

        # Generate trajectory
        grasp_traj = self.pipeline.generate_trajectory(detections)
        if grasp_traj is None:
            self.get_logger().error(f"Target marker {goal.target_marker_id} not found in detections")
            goal_handle.abort()
            return GraspExecute.Result(success=False, trajectory=JointTrajectory(), message=f"Marker {goal.target_marker_id} not found")

        # Convert to JointTrajectory message
        traj_msg = self._grasp_trajectory_to_msg(grasp_traj)

        # Send to FollowJointTrajectory action server
        self.get_logger().info("Sending trajectory to follower...")
        follow_goal = FollowJointTrajectory.Goal()
        follow_goal.trajectory = traj_msg

        # Wait for action server
        if not self._follow_client.wait_for_server(timeout_sec=5.0):
            self.get_logger().error("FollowJointTrajectory action server not available")
            goal_handle.abort()
            return GraspExecute.Result(success=False, trajectory=traj_msg, message="Follower server not available")

        # Send goal
        send_future = self._follow_client.send_goal_async(follow_goal)
        rclpy.spin_until_future_complete(self, send_future, timeout_sec=5.0)

        goal_handle_follow = send_future.result()
        if not goal_handle_follow.accepted:
            self.get_logger().error("Follow goal rejected")
            goal_handle.abort()
            return GraspExecute.Result(success=False, trajectory=traj_msg, message="Follow goal rejected")

        # Wait for result
        result_future = goal_handle_follow.get_result_async()
        rclpy.spin_until_future_complete(self, result_future, timeout_sec=self.follow_timeout)

        if result_future.done():
            follow_result = result_future.result().result
            success = follow_result.error_code == FollowJointTrajectory.Result.SUCCESSFUL
            msg = "Grasp executed successfully" if success else f"Follow failed: error_code={follow_result.error_code}"
            self.get_logger().info(msg)

            if success:
                goal_handle.succeed()
            else:
                goal_handle.abort()

            return GraspExecute.Result(success=success, trajectory=traj_msg, message=msg)
        else:
            self.get_logger().error("Follow action timed out")
            goal_handle.abort()
            return GraspExecute.Result(success=False, trajectory=traj_msg, message="Follow action timed out")

    def _grasp_trajectory_to_msg(self, grasp_traj) -> JointTrajectory:
        """Convert GraspTrajectory to trajectory_msgs/JointTrajectory."""
        traj = JointTrajectory()
        traj.joint_names = grasp_traj.joint_names
        traj.header = Header()
        traj.header.stamp = self.get_clock().now().to_msg()
        traj.header.frame_id = self.base_frame

        for wp in grasp_traj.waypoints:
            point = JointTrajectoryPoint()
            point.time_from_start = Duration(seconds=wp["time_from_start"]).to_msg()
            point.positions = wp["positions"]
            point.velocities = [0.0] * len(grasp_traj.joint_names)
            point.accelerations = [0.0] * len(grasp_traj.joint_names)
            traj.points.append(point)

        return traj

    def destroy_node(self):
        self._perception_sub.destroy()
        self._follow_client.destroy()
        self._grasp_server.destroy()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = GraspNode()
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()