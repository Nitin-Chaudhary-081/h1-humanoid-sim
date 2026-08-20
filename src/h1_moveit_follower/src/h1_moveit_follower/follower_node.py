"""ROS 2 node for MoveIt2 FollowJointTrajectory action server.

Thin wrapper around TrajectoryFollower that exposes a FollowJointTrajectory
action server on /h1/moveit/follow_trajectory. After trajectory execution the
final joint positions are verified against the joint state topic; violations
mark the goal FAILED (GOAL_TOLERANCE_VIOLATED) with per-joint details.
"""

from typing import Optional
import os
import yaml

import rclpy
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.duration import Duration
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
from rclpy.time import Time

from control_msgs.action import FollowJointTrajectory
from sensor_msgs.msg import JointState
from trajectory_msgs.msg import JointTrajectoryPoint
from std_msgs.msg import Float64

from h1_moveit_follower.trajectory_follower import TrajectoryFollower, evaluate_tolerance


class FollowerNode(Node):
    """ROS 2 node that bridges MoveIt2 FollowJointTrajectory to H1 cmd_pos topics."""

    def __init__(self):
        super().__init__("h1_moveit_follower")

        # Declare parameters
        self.declare_parameter("control_hz", 50.0)
        self.declare_parameter("joint_state_topic", "/h1/joint_states")
        self.declare_parameter("arm_joint_names", [
            "left_shoulder_pitch_joint",
            "left_elbow_joint",
            "right_shoulder_pitch_joint",
            "right_elbow_joint",
        ])
        self.declare_parameter("params_file", "src/h1_moveit_follower/config/follower.yaml")

        # Get parameters
        control_hz = self.get_parameter("control_hz").get_parameter_value().double_value
        joint_state_topic = self.get_parameter("joint_state_topic").get_parameter_value().string_value
        arm_joint_names = self.get_parameter("arm_joint_names").get_parameter_value().string_array_value
        params_file = self.get_parameter("params_file").get_parameter_value().string_value

        # Load complex parameters from YAML file
        if os.path.isabs(params_file):
            yaml_path = params_file
        else:
            yaml_path = os.path.join(os.getcwd(), params_file)
        
        with open(yaml_path, 'r') as f:
            config = yaml.safe_load(f)
        
        node_config = config.get('h1_moveit_follower', {}).get('ros__parameters', {})
        stand_pose_fallback = node_config.get('stand_pose_fallback', {})
        trajectory_tolerance = node_config.get('trajectory_tolerance', {})

        # Initialize pure logic follower
        self.follower = TrajectoryFollower(
            control_hz=control_hz,
            arm_joint_names=list(arm_joint_names),
            stand_pose_fallback=dict(stand_pose_fallback),
            trajectory_tolerance=dict(trajectory_tolerance),
        )

        # Latest joint state for final tolerance verification (BEST_EFFORT,
        # matches /h1/joint_states contract in docs/contracts/topics.md)
        self._latest_joint_state: Optional[JointState] = None
        joint_state_qos = QoSProfile(
            depth=10,
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
        )
        self._joint_state_sub = self.create_subscription(
            JointState, joint_state_topic, self._joint_state_callback, joint_state_qos
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

    def _joint_state_callback(self, msg: JointState):
        """Store the latest joint state for final tolerance verification."""
        self._latest_joint_state = msg

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
            feedback_msg = FollowJointTrajectory.Feedback()
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

        # Verify the final state against trajectory end-point tolerance
        if goal_handle.is_active:
            # Get final target positions for arm joints
            final_positions = trajectory_points[-1]["positions"]
            target_dict = {}
            for i, name in enumerate(joint_names):
                if name in self.follower.arm_joint_names:
                    target_dict[name] = final_positions[i]

            ok, detail = self._verify_final_tolerance(target_dict)
            if not ok:
                self.get_logger().error(f"Tolerance check FAILED: {detail}")
                goal_handle.abort()
                return FollowJointTrajectory.Result(
                    error_code=FollowJointTrajectory.Result.GOAL_TOLERANCE_VIOLATED,
                    error_string=detail,
                )

            goal_handle.succeed()
            return FollowJointTrajectory.Result(
                error_code=FollowJointTrajectory.Result.SUCCESSFUL
            )

        return FollowJointTrajectory.Result(
            error_code=FollowJointTrajectory.Result.PREEMPTED
        )

    def _verify_final_tolerance(self, target_dict: dict) -> tuple:
        """Check each arm joint's final position against the trajectory end.

        Uses the latest /h1/joint_states sample. Returns (ok, detail_string).
        """
        if self._latest_joint_state is None:
            self.get_logger().warn(
                "No joint state received; skipping tolerance check"
            )
            return True, "no joint state received"

        names = list(self._latest_joint_state.name)
        positions = list(self._latest_joint_state.position)
        velocities = (
            list(self._latest_joint_state.velocity)
            if self._latest_joint_state.velocity
            else None
        )

        actual_positions = {}
        actual_velocities = {}
        for i, name in enumerate(names):
            if name in target_dict:
                actual_positions[name] = positions[i]
                if velocities:
                    actual_velocities[name] = velocities[i]

        violations = evaluate_tolerance(
            target_positions=target_dict,
            actual_positions=actual_positions,
            position_tolerance=self.follower.trajectory_tolerance.get("position", 0.01),
            velocity_tolerance=self.follower.trajectory_tolerance.get("velocity", 0.1),
            actual_velocities=actual_velocities if velocities else None,
        )
        if violations:
            return False, "tolerance violations: " + "; ".join(violations)
        return True, "all joints within tolerance"

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
        if self._joint_state_sub is not None:
            self._joint_state_sub.destroy()
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