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
    GraspExecutor,
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
        # M5 integration params
        self.declare_parameter("planning_group", "left_arm")
        self.declare_parameter("use_moveit", False)
        self.declare_parameter("timeout_sec", 5.0)

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
        self.planning_group = self.get_parameter("planning_group").get_parameter_value().string_value
        self.use_moveit = self.get_parameter("use_moveit").get_parameter_value().bool_value
        self.timeout_sec = self.get_parameter("timeout_sec").get_parameter_value().double_value

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

        # Optional MoveIt2 planner (use_moveit=true; heuristic IK fallback default)
        moveit_planner = None
        if self.use_moveit:
            try:
                from h1_grasp_pipeline.grasp_pipeline import MoveIt2Planner

                moveit_planner = MoveIt2Planner(self)
                if not moveit_planner.is_available():
                    self.get_logger().warn(
                        "use_moveit=true but MoveIt2 is unavailable; falling back to heuristic IK"
                    )
                    moveit_planner = None
            except Exception as exc:
                self.get_logger().warn(f"Failed to initialize MoveIt2 planner: {exc}")
                moveit_planner = None

        # Initialize pipeline
        self.pipeline = GraspPipeline(
            camera_to_base=camera_to_base,
            arm_joint_names=list(self.arm_joint_names),
            grasp_offsets=grasp_offsets,
            target_marker_id=self.target_marker_id,
            moveit_planner=moveit_planner,
            planning_group=self.planning_group,
        )

        # Pure end-to-end executor (detections provider + follower sender injected)
        self._executor = GraspExecutor(
            pipeline=self.pipeline,
            send_trajectory=self._send_trajectory,
            timeout_sec=self.timeout_sec,
        )

        # Latest perception frame + cached MarkerDetection list
        self._latest_frame: Optional[PerceptionFrame] = None
        self._latest_detections: list = []

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
            f"approach={approach_distance}m, grasp_depth={grasp_depth}m, retreat={retreat_distance}m, "
            f"planning_group={self.planning_group}, use_moveit={self.use_moveit}, "
            f"timeout_sec={self.timeout_sec}"
        )

    def _perception_callback(self, msg: PerceptionFrame):
        """Store latest perception frame and cached MarkerDetection list."""
        self._latest_frame = msg
        detections = []
        for pd in msg.detections:
            det = MarkerDetection(
                marker_id=pd.marker_id,
                position=np.array([pd.pose.position.x, pd.pose.position.y, pd.pose.position.z]),
                orientation=np.array([
                    pd.pose.orientation.x, pd.pose.orientation.y,
                    pd.pose.orientation.z, pd.pose.orientation.w,
                ]),
                confidence=pd.confidence,
            )
            detections.append(det)
        self._latest_detections = detections

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
        """Execute the full grasp sequence via the pure GraspExecutor.

        Sequence: wait for PerceptionFrame with target marker -> GraspPipeline
        -> send JointTrajectory to /h1/moveit/follow_trajectory -> result.
        """
        goal = goal_handle.request

        self.get_logger().info(
            f"GraspExecute goal: marker={goal.target_marker_id}, "
            f"pregrasp_offset={goal.pregrasp_offset}, grasp_depth={goal.grasp_depth}"
        )

        try:
            outcome = self._executor.execute(
                detections_provider=lambda: list(self._latest_detections),
                target_marker_id=goal.target_marker_id,
                pregrasp_offset=goal.pregrasp_offset,
                grasp_depth=goal.grasp_depth,
            )
        except Exception as exc:
            self.get_logger().error(f"Grasp execution error: {exc}")
            goal_handle.abort()
            return GraspExecute.Result(
                success=False,
                trajectory=JointTrajectory(),
                message=f"Grasp execution error: {exc}",
            )

        traj_msg = self._dict_to_joint_trajectory_msg(outcome.trajectory)
        result = GraspExecute.Result(
            success=outcome.success,
            trajectory=traj_msg,
            message=outcome.message,
        )
        try:
            if outcome.success:
                goal_handle.succeed()
            else:
                goal_handle.abort()
        except Exception as exc:
            self.get_logger().error(f"Could not publish goal outcome: {exc}")
        return result

    def _send_trajectory(self, traj_dict: dict) -> tuple:
        """Send a JointTrajectory dict to the follower action and await result.

        Returns (success, message) per the GraspExecutor sender contract.
        """
        traj_msg = self._dict_to_joint_trajectory_msg(traj_dict)

        # Wait for action server
        if not self._follow_client.wait_for_server(timeout_sec=5.0):
            return False, "Follower server not available"

        follow_goal = FollowJointTrajectory.Goal()
        follow_goal.trajectory = traj_msg

        # Send goal (avoid nested spin_until_future_complete inside action callback)
        import time
        send_future = self._follow_client.send_goal_async(follow_goal)
        # Wait without nested spin — main MultiThreadedExecutor is already spinning.
        # Use follow_timeout (not a hardcoded 5 s): DDS discovery + goal response
        # can exceed 5 s wall when the full stack runs at RTF ~10 %.
        start = time.time()
        while not send_future.done() and time.time() - start < self.follow_timeout:
            time.sleep(0.05)
        if not send_future.done():
            return False, "Follow goal send timed out"
        try:
            goal_handle_follow = send_future.result()
        except Exception as exc:
            return False, f"Follow goal send failed: {exc}"
        if not goal_handle_follow or not goal_handle_follow.accepted:
            return False, "Follow goal rejected"

        # Wait for result (poll, no nested spin)
        result_future = goal_handle_follow.get_result_async()
        start = time.time()
        while not result_future.done() and time.time() - start < self.follow_timeout:
            time.sleep(0.05)
        if not result_future.done():
            return False, "Follow action timed out"

        follow_result = result_future.result().result
        success = follow_result.error_code == FollowJointTrajectory.Result.SUCCESSFUL
        if success:
            message = "Grasp executed successfully"
        else:
            err = getattr(follow_result, "error_string", "") or ""
            message = f"Follow failed: error_code={follow_result.error_code} {err}"
        self.get_logger().info(message)
        return success, message

    def _dict_to_joint_trajectory_msg(self, traj_dict: Optional[dict]) -> JointTrajectory:
        """Convert a JointTrajectory-compatible dict to trajectory_msgs/JointTrajectory."""
        traj = JointTrajectory()
        if not traj_dict:
            return traj
        traj.joint_names = traj_dict["joint_names"]
        traj.header = Header()
        traj.header.stamp = self.get_clock().now().to_msg()
        traj.header.frame_id = self.base_frame

        for wp in traj_dict["points"]:
            point = JointTrajectoryPoint()
            point.time_from_start = Duration(seconds=wp["time_from_start"]).to_msg()
            point.positions = wp["positions"]
            point.velocities = wp.get("velocities", [0.0] * len(traj.joint_names))
            point.accelerations = wp.get("accelerations", [0.0] * len(traj.joint_names))
            traj.points.append(point)

        return traj

    def _grasp_trajectory_to_msg(self, grasp_traj) -> JointTrajectory:
        """Convert GraspTrajectory to trajectory_msgs/JointTrajectory."""
        return self._dict_to_joint_trajectory_msg(
            self.pipeline.trajectory_to_joint_trajectory_msg(grasp_traj)
        )

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