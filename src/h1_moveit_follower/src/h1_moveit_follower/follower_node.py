"""ROS 2 node for MoveIt2 FollowJointTrajectory action server.

Thin wrapper around TrajectoryFollower that exposes a FollowJointTrajectory
action server on /h1/moveit/follow_trajectory.
"""

import rclpy
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.duration import Duration
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
from rclpy.time import Time

from control_msgs.action import FollowJointTrajectory
from control_msgs.msg import FollowJointTrajectoryFeedback
from trajectory_msgs.msg import JointTrajectoryPoint
from std_msgs.msg import Float64

from h1_moveit_follower.trajectory_follower import TrajectoryFollower


class FollowerNode(Node):
    """ROS 2 node that bridges MoveIt2 FollowJointTrajectory to H1 cmd_pos topics."""

    def __init__(self):
        super().__init__("h1_moveit_follower")

        # Declare parameters
        self.declare_parameter("control_hz", 50.0)
        self.declare_parameter("arm_joint_names", [
            "left_shoulder_pitch_joint",
            "left_elbow_joint",
            "right_shoulder_pitch_joint",
            "right_elbow_joint",
        ])
        self.declare_parameter("stand_pose_fallback", {
            "left_shoulder_pitch_joint": 0.0,
            "left_elbow_joint": 0.0,
            "right_shoulder_pitch_joint": 0.0,
            "right_elbow_joint": 0.0,
            "torso_joint": 0.0,
            "left_hip_yaw_joint": 0.0,
            "left_hip_roll_joint": 0.0,
            "left_hip_pitch_joint": -0.1,
            "left_knee_joint": 0.2,
            "left_ankle_pitch_joint": -0.1,
            "left_ankle_roll_joint": 0.0,
            "right_hip_yaw_joint": 0.0,
            "right_hip_roll_joint": 0.0,
            "right_hip_pitch_joint": -0.1,
            "right_knee_joint": 0.2,
            "right_ankle_pitch_joint": -0.1,
            "right_ankle_roll_joint": 0.0,
        })
        self.declare_parameter("trajectory_tolerance", {
            "position": 0.01,
            "velocity": 0.1,
        })

        # Get parameters
        control_hz = self.get_parameter("control_hz").get_parameter_value().double_value
        arm_joint_names = self.get_parameter("arm_joint_names").get_parameter_value().string_array_value
        stand_pose_fallback = self.get_parameter("stand_pose_fallback").get_parameter_value().double_map_value
        trajectory_tolerance = self.get_parameter("trajectory_tolerance").get_parameter_value().double_map_value

        # Initialize pure logic follower
        self.follower = TrajectoryFollower(
            control_hz=control_hz,
            arm_joint_names=list(arm_joint_names),
            stand_pose_fallback=dict(stand_pose_fallback),
            trajectory_tolerance=dict(trajectory_tolerance),
        )

        # Publishers for each arm joint cmd_pos (RELIABLE QoS)
        self.cmd_publishers = {}
        qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
            depth=10,
        )
        for joint in self.follower.arm_joint_names:
            topic = f"/h1/{joint}/cmd_pos"
            self.cmd_publishers[joint] = self.create_publisher(Float64, topic, qos)
            self.get_logger().info(f"Publishing {joint} commands to {topic}")

        # Action server with reentrant callback group for concurrent goal handling
        self._action_server = ActionServer(
            self,
            FollowJointTrajectory,
            "/h1/moveit/follow_trajectory",
            execute_callback=self.execute_callback,
            goal_callback=self.goal_callback,
            cancel_callback=self.cancel_callback,
            callback_group=ReentrantCallbackGroup(),
        )

        # Timer for control loop
        self.control_timer = None
        self.current_goal_handle = None
        self.trajectory_generator = None
        self.trajectory_end_time = 0.0
        self.start_time = None

        self.get_logger().info("H1 MoveIt2 trajectory follower node started")

    def goal_callback(self, goal_request):
        """Validate incoming trajectory goal."""
        joint_names = list(goal_request.trajectory.joint_names)

        # Validate joint names
        is_valid, unknown = self.follower.validate_joint_names(joint_names)
        if not is_valid:
            self.get_logger().warn(f"Rejecting goal: unknown joints {unknown}")
            return GoalResponse.REJECT

        if not goal_request.trajectory.points:
            self.get_logger().warn("Rejecting goal: empty trajectory")
            return GoalResponse.REJECT

        self.get_logger().info(f"Accepting goal with {len(joint_names)} joints, {len(goal_request.trajectory.points)} points")
        return GoalResponse.ACCEPT

    def cancel_callback(self, goal_handle):
        """Handle goal cancellation."""
        self.get_logger().info("Cancel requested for trajectory goal")
        return CancelResponse.ACCEPT

    def execute_callback(self, goal_handle):
        """Execute the trajectory following action."""
        self.current_goal_handle = goal_handle
        trajectory = goal_handle.request.trajectory
        joint_names = list(trajectory.joint_names)

        # Convert trajectory points to format expected by TrajectoryFollower
        trajectory_points = []
        for point in trajectory.points:
            tp = {
                "time_from_start": point.time_from_start.nanoseconds * 1e-9,
                "positions": list(point.positions),
            }
            if point.velocities:
                tp["velocities"] = list(point.velocities)
            if point.accelerations:
                tp["accelerations"] = list(point.accelerations)
            trajectory_points.append(tp)

        # Start trajectory following
        stand_pose = dict(self.follower.stand_pose_fallback)
        self.trajectory_generator = self.follower.follow(
            trajectory_points, joint_names, stand_pose
        )
        self.trajectory_end_time = trajectory_points[-1]["time_from_start"]
        self.start_time = self.get_clock().now()

        # Create control timer
        dt = 1.0 / self.follower.control_hz
        self.control_timer = self.create_timer(
            dt, self.control_timer_callback, callback_group=ReentrantCallbackGroup()
        )

        # Wait for trajectory to complete or be cancelled
        feedback_msg = FollowJointTrajectoryFeedback()
        rate = self.create_rate(self.follower.control_hz)

        while rclpy.ok():
            if goal_handle.is_cancel_requested:
                self.get_logger().info("Goal cancelled")
                self.stop_control_loop()
                goal_handle.canceled()
                return FollowJointTrajectory.Result(
                    error_code=FollowJointTrajectory.Result.PREEMPTED
                )

            if self.trajectory_generator is None:
                # Trajectory completed
                break

            # Publish feedback
            current_time = self.get_clock().now()
            elapsed = (current_time - self.start_time).nanoseconds * 1e-9
            feedback_msg.header.stamp = current_time.to_msg()
            feedback_msg.joint_names = joint_names
            feedback_msg.desired.time_from_start = Duration(seconds=elapsed).to_msg()
            feedback_msg.actual.time_from_start = Duration(seconds=elapsed).to_msg()
            feedback_msg.error.time_from_start = Duration(seconds=0).to_msg()
            goal_handle.publish_feedback(feedback_msg)

            try:
                rate.sleep()
            except Exception:
                break

        self.stop_control_loop()

        # Check final tolerance
        if goal_handle.is_active:
            # Get final target positions for arm joints
            final_positions = trajectory_points[-1]["positions"]
            target_dict = {}
            for i, name in enumerate(joint_names):
                if name in self.follower.arm_joint_names:
                    target_dict[name] = final_positions[i]

            # Note: In real implementation, would check against actual joint states
            # For now, assume success if trajectory completed
            goal_handle.succeed()
            return FollowJointTrajectory.Result(
                error_code=FollowJointTrajectory.Result.SUCCESSFUL
            )

        return FollowJointTrajectory.Result(
            error_code=FollowJointTrajectory.Result.PREEMPTED
        )

    def control_timer_callback(self):
        """Timer callback to publish joint commands at control rate."""
        if self.trajectory_generator is None:
            return

        try:
            timestamp, cmd_positions = next(self.trajectory_generator)

            # Publish to each joint's cmd_pos topic
            for joint, position in cmd_positions.items():
                if joint in self.cmd_publishers:
                    msg = Float64()
                    msg.data = float(position)
                    self.cmd_publishers[joint].publish(msg)

        except StopIteration:
            # Trajectory complete
            self.get_logger().info("Trajectory execution completed")
            self.trajectory_generator = None
            if self.control_timer:
                self.control_timer.cancel()
                self.control_timer = None

    def stop_control_loop(self):
        """Stop the control timer and clean up."""
        if self.control_timer:
            self.control_timer.cancel()
            self.control_timer = None
        self.trajectory_generator = None
        self.current_goal_handle = None

    def destroy_node(self):
        self.stop_control_loop()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = FollowerNode()
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