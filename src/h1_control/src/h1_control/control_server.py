"""h1_control node: Stand/Walk/Stop action server driving /h1/<joint>/cmd_pos.

Thin ROS wrapper — all logic lives in the pure modules (stand, motion_player,
estop). Timer-driven publishing, no blocking callbacks.
"""

import os
import threading
import time

import rclpy
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy

from h1_interfaces.action import RobotCommand
from h1_interfaces.msg import ControlState
from std_msgs.msg import Bool, Float64
from nav_msgs.msg import Odometry
from sensor_msgs.msg import Imu

from .estop import EstopGate
from .imu_comp import ImuAnkleCompensation, quaternion_to_pitch_roll_deg
from .motion_player import JointMap, make_motion_player
from .stand import StandController

JOINT_LIMIT_GUARD = 5.0  # rad; refuse to publish garbage beyond this


class ControlServer(Node):
    def __init__(self):
        super().__init__("h1_control_server")
        self.set_parameters([Parameter("use_sim_time", Parameter.Type.BOOL, True)])
        self.declare_parameter("cmd_hz", 50.0)
        self.declare_parameter("state_hz", 10.0)
        self.declare_parameter("playback_rate", 100.0)
        self.declare_parameter("speed_multiplier", 0.5)
        self.declare_parameter("default_walk_cycles", 3)
        self.declare_parameter("npz_window_s", 30.0)
        self.declare_parameter("walk_npz", "")  # empty = auto-search pkg data
        self.declare_parameter("config_dir", "")
        # IMU ankle compensation
        self.declare_parameter("imu_comp_enabled", True)
        self.declare_parameter("imu_comp_kp_pitch_rad_per_deg", 0.02)
        self.declare_parameter("imu_comp_kp_roll_rad_per_deg", 0.02)
        self.declare_parameter("imu_comp_deadzone_deg", 1.0)
        self.declare_parameter("imu_comp_clamp_pitch_deg", 8.0)
        self.declare_parameter("imu_comp_clamp_roll_deg", 6.0)
        self.declare_parameter("imu_comp_ema_alpha", 0.1)

        cmd_hz = self.get_parameter("cmd_hz").value
        state_hz = self.get_parameter("state_hz").value
        self._playback_rate = float(self.get_parameter("playback_rate").value)
        self._speed_multiplier = float(self.get_parameter("speed_multiplier").value)
        self._default_cycles = float(self.get_parameter("default_walk_cycles").value)
        self._npz_window_s = float(self.get_parameter("npz_window_s").value)
        # IMU compensation params
        self._imu_comp_enabled = self.get_parameter("imu_comp_enabled").value
        self._imu_comp = None
        if self._imu_comp_enabled:
            self._imu_comp = ImuAnkleCompensation(
                kp_pitch_rad_per_deg=self.get_parameter("imu_comp_kp_pitch_rad_per_deg").value,
                kp_roll_rad_per_deg=self.get_parameter("imu_comp_kp_roll_rad_per_deg").value,
                deadzone_deg=self.get_parameter("imu_comp_deadzone_deg").value,
                clamp_pitch_deg=self.get_parameter("imu_comp_clamp_pitch_deg").value,
                clamp_roll_deg=self.get_parameter("imu_comp_clamp_roll_deg").value,
                ema_alpha=self.get_parameter("imu_comp_ema_alpha").value,
            )

        # --- config / data paths ---
        config_dir = self.get_parameter("config_dir").value or self._pkg_path("config")
        stand_path = os.path.join(config_dir, "stand.yaml")
        joint_map_path = os.path.join(config_dir, "joint_map.yaml")
        npz_path = self.get_parameter("walk_npz").value or self._pkg_path("data", "walk.npz")

        self._stand = StandController.from_yaml(stand_path)
        self._joints = self._stand.joints
        self._joint_map = JointMap.from_yaml(joint_map_path, target_joints=self._joints)
        self._npz_path = npz_path or ""

        # --- motion state ---
        self._mode = ControlState.MODE_STAND
        self._status = ControlState.STATUS_IDLE
        self._detail = "idle"
        self._goal_distance = 0.0
        self._distance_traveled = 0.0
        self._hold_pose = self._stand.target_pose()
        self._player = None
        self._player_source = "unset"
        self._walk_start = self.get_clock().now()
        self._goal_done = threading.Event()
        self._final_status = ControlState.STATUS_SUCCEEDED
        self._final_detail = ""
        self._estop_active = False
        self._odom_last = None
        self._odom_vx = 0.0

        # --- pub/sub (QoS per docs/contracts/topics.md) ---
        reliable = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE)
        best_effort = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT)
        self._pubs = {name: self.create_publisher(Float64, "/h1/%s/cmd_pos" % name,
                                                  reliable)
                      for name in self._joints}
        self._state_pub = self.create_publisher(ControlState, "/h1/control_state",
                                                reliable)
        self._estop_sub = self.create_subscription(Bool, "/estop", self._estop_cb,
                                                   reliable)
        self._odom_sub = self.create_subscription(Odometry, "/h1/odometry",
                                                  self._odom_cb, best_effort)
        if self._imu_comp_enabled:
            self._imu_sub = self.create_subscription(
                Imu, "/imu", self._imu_cb, best_effort)
        else:
            self._imu_sub = None

        self._action_server = ActionServer(
            self, RobotCommand, "/h1/command",
            goal_callback=self._goal_cb,
            execute_callback=self._execute,
            cancel_callback=self._cancel_cb)

        # --- timers ---
        self.create_timer(1.0 / cmd_hz, self._cmd_timer)
        self.create_timer(1.0 / state_hz, self._state_timer)
        self.get_logger().info("h1_control ready: %d joints, cmd %.0f Hz"
                               % (len(self._joints), cmd_hz))

    # ------------------------------------------------------------------ paths
    @staticmethod
    def _pkg_path(*parts):
        src_root = os.path.join(os.path.dirname(__file__), "..", "..")
        candidate = os.path.join(src_root, *parts)
        if os.path.exists(candidate):
            return candidate
        try:
            from ament_index_python.packages import get_package_share_directory
            share = get_package_share_directory("h1_control")
            candidate = os.path.join(share, *parts)
            if os.path.exists(candidate):
                return candidate
        except Exception:
            pass
        return None

    # ------------------------------------------------------------- callbacks
    def _goal_cb(self, goal_request):
        if self._estop_active:
            self.get_logger().warn("goal rejected: estop active")
            return GoalResponse.REJECT
        if self._status == ControlState.STATUS_RUNNING:
            self.get_logger().warn("goal rejected: busy (single-goal server)")
            return GoalResponse.REJECT
        return GoalResponse.ACCEPT

    def _cancel_cb(self, _goal_handle):
        return CancelResponse.REJECT  # estop is the safety path, not cancel

    def _execute(self, goal_handle):
        req = goal_handle.request
        try:
            self._begin_goal(req)
            while rclpy.ok() and not self._goal_done.is_set():
                goal_handle.publish_feedback(
                    RobotCommand.Feedback(status=self._status,
                                          detail=self._detail))
                time.sleep(0.05)
        except Exception as exc:
            self.get_logger().error("execute callback error: %s" % exc)
        if self._status == ControlState.STATUS_ESTOPPED:
            self._final_status = ControlState.STATUS_ESTOPPED
            self._final_detail = "ESTOPPED"
        result = RobotCommand.Result(
            success=(self._final_status == ControlState.STATUS_SUCCEEDED),
            message="motion goal finished",
            status=self._final_status,
            detail=self._final_detail)
        try:
            if self._final_status == ControlState.STATUS_SUCCEEDED:
                goal_handle.succeed()
            else:
                goal_handle.abort()
        except Exception as exc:
            self.get_logger().error("could not publish goal outcome: %s" % exc)
        return result

    def _begin_goal(self, req):
        self._goal_done.clear()
        self._distance_traveled = 0.0
        self._odom_last = None
        self._odom_vx = 0.0
        if req.mode == RobotCommand.Goal.STAND:
            self._mode = ControlState.MODE_STAND
            self._status = ControlState.STATUS_RUNNING
            self._detail = "standing"
            self._goal_distance = 0.0
            self._finish(ControlState.STATUS_SUCCEEDED, "stand complete")
        elif req.mode == RobotCommand.Goal.WALK:
            if self._player is None:
                self._player, self._player_source = make_motion_player(
                    self._npz_path, self._joint_map,
                    playback_rate=self._playback_rate,
                    speed_multiplier=self._speed_multiplier,
                    window_s=self._npz_window_s)
                self.get_logger().info("motion source: %s" % self._player_source)
            self._mode = ControlState.MODE_WALK
            self._status = ControlState.STATUS_RUNNING
            self._goal_distance = max(0.0, req.distance)
            self._walk_start = self.get_clock().now()
            if self._goal_distance > 0.0:
                self._detail = "walking %.2f m" % self._goal_distance
            else:
                self._detail = "walking %d cycles" % int(self._default_cycles)
            self.get_logger().info("WALK goal accepted: %s" % self._detail)
            # Reset IMU compensation for fresh walk
            if self._imu_comp_enabled and self._imu_comp is not None:
                self._imu_comp.reset()
        elif req.mode == RobotCommand.Goal.STOP:
            self._mode = ControlState.MODE_STOP
            self._status = ControlState.STATUS_RUNNING
            self._detail = "stopping"
            self._goal_distance = 0.0
            self._hold_pose = dict(self._hold_pose)  # freeze current pose
            self._finish(ControlState.STATUS_SUCCEEDED, "stopped")

    def _finish(self, status, detail):
        self._final_status = status
        self._final_detail = detail
        self._goal_done.set()
        if status == ControlState.STATUS_SUCCEEDED:
            self._detail = detail
            self._status = status

    def _estop_cb(self, msg):
        if bool(msg.data) == self._estop_active:
            return
        self._estop_active = bool(msg.data)
        if self._estop_active:
            self.get_logger().error("ESTOP ACTIVE - freezing commands")
            if self._status == ControlState.STATUS_RUNNING:
                self._status = ControlState.STATUS_ESTOPPED
                self._detail = "ESTOPPED"
                self._finish(ControlState.STATUS_ESTOPPED, "ESTOPPED")
            else:
                self._status = ControlState.STATUS_ESTOPPED
                self._detail = "ESTOPPED"
        else:
            self.get_logger().info("estop cleared")
            if self._status == ControlState.STATUS_ESTOPPED:
                self._status = ControlState.STATUS_IDLE
                self._detail = "estop cleared"

    def _odom_cb(self, msg):
        now = self.get_clock().now()
        if self._status == ControlState.STATUS_RUNNING and \
                self._mode == ControlState.MODE_WALK and \
                EstopGate.allows(self._estop_active):
            if self._odom_last is not None:
                dt = (now - self._odom_last).nanoseconds * 1e-9
                if dt > 0.0:
                    self._distance_traveled += abs(float(msg.twist.twist.linear.x)) * dt
            self._odom_last = now
            self._odom_vx = float(msg.twist.twist.linear.x)
        else:
            self._odom_last = None

    def _imu_cb(self, msg):
        if not self._imu_comp_enabled or self._imu_comp is None:
            return
        pitch_deg, roll_deg = quaternion_to_pitch_roll_deg(
            msg.orientation.x, msg.orientation.y,
            msg.orientation.z, msg.orientation.w)
        self._imu_comp.update(pitch_deg, roll_deg)

    def _cmd_timer(self):
        if not EstopGate.allows(self._estop_active):
            return  # frozen: sim holds last commanded pose
        try:
            pose = self._compute_pose()
            for name, val in pose.items():
                if not (-JOINT_LIMIT_GUARD <= val <= JOINT_LIMIT_GUARD):
                    self.get_logger().error("refusing out-of-bounds cmd %.2f for %s"
                                            % (val, name))
                    continue
                self._pubs[name].publish(Float64(data=float(val)))
            self._hold_pose = pose
            self._check_walk_complete()
        except Exception as exc:
            self.get_logger().error("cmd timer error: %s" % exc)

    def _compute_pose(self):
        if self._mode == ControlState.MODE_WALK and \
                self._status == ControlState.STATUS_RUNNING:
            if self._walk_start is None:
                return dict(self._hold_pose)
            elapsed = (self.get_clock().now() - self._walk_start).nanoseconds * 1e-9
            if self._player is None:
                return dict(self._hold_pose)
            pose = self._player.sample_at(elapsed)
            # Apply IMU ankle compensation on top of the walk pose
            if self._imu_comp_enabled and self._imu_comp is not None:
                compensation = self._imu_comp.update(0.0, 0.0)  # get latest smoothed correction
                for joint, corr in compensation.items():
                    if joint in pose:
                        pose[joint] += corr
            return pose
        if self._mode == ControlState.MODE_STAND:
            return self._stand.target_pose()
        return dict(self._hold_pose)  # STOP / finished / idle hold

    def _check_walk_complete(self):
        if self._mode != ControlState.MODE_WALK or \
                self._status != ControlState.STATUS_RUNNING:
            return
        elapsed = (self.get_clock().now() - self._walk_start).nanoseconds * 1e-9
        if self._goal_distance > 0.0:
            if self._distance_traveled >= self._goal_distance:
                self._mode = ControlState.MODE_STOP
                self._hold_pose = self._compute_pose()
                self._finish(ControlState.STATUS_SUCCEEDED,
                             "walked %.2f of %.2f m"
                             % (self._distance_traveled, self._goal_distance))
                self.get_logger().info("WALK goal succeeded: %s" % self._detail)
            elif elapsed > max(300.0, self._goal_distance / 0.3):
                self._finish(ControlState.STATUS_FAILED, "walk timeout")
                self.get_logger().error("WALK goal timed out")
        else:
            limit = self._default_cycles * self._player.realtime_duration
            if elapsed >= limit:
                self._mode = ControlState.MODE_STOP
                self._hold_pose = self._compute_pose()
                self._finish(ControlState.STATUS_SUCCEEDED,
                             "walked %d cycles" % int(self._default_cycles))
                self.get_logger().info("WALK goal succeeded: %s" % self._detail)
            elif elapsed > max(300.0, limit):
                self._finish(ControlState.STATUS_FAILED, "walk timeout")
                self.get_logger().error("WALK goal timed out")

    def _state_timer(self):
        msg = ControlState()
        msg.stamp = self.get_clock().now().to_msg()
        msg.mode = self._mode
        msg.status = self._status
        msg.goal_distance = self._goal_distance
        msg.distance_traveled = self._distance_traveled
        msg.detail = self._detail
        self._state_pub.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = ControlServer()
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
