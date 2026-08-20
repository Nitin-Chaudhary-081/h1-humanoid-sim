"""Command bridge: /h1/<joint>/cmd_pos -> aggregated motor command topic.

Subscribes one std_msgs/Float64 command topic per actuated joint, aggregates
them in a fixed joint order and publishes a std_msgs/Float64MultiArray on
``/h1/hardware/commands`` at a fixed rate. The Unitree SDK companion process
subscribes to that topic (or a service adapter) to write the motor controllers.

Safety: only joints that have received at least one command are forwarded
unless ``zero_uncommanded`` is true. Commands use RELIABLE QoS.
"""

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy
from std_msgs.msg import Float64, Float64MultiArray, MultiArrayDimension

RELIABLE_QOS = QoSProfile(
    depth=10,
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
)

DEFAULT_JOINTS = [
    "left_hip_yaw_joint", "left_hip_roll_joint", "left_hip_pitch_joint",
    "left_knee_joint", "left_ankle_pitch_joint", "left_ankle_roll_joint",
    "right_hip_yaw_joint", "right_hip_roll_joint", "right_hip_pitch_joint",
    "right_knee_joint", "right_ankle_pitch_joint", "right_ankle_roll_joint",
    "torso_joint",
    "left_shoulder_pitch_joint", "left_shoulder_roll_joint",
    "left_shoulder_yaw_joint", "left_elbow_joint",
    "right_shoulder_pitch_joint", "right_shoulder_roll_joint",
    "right_shoulder_yaw_joint", "right_elbow_joint",
]


class CommandBridge(Node):
    def __init__(self):
        super().__init__("h1_command_bridge")
        self.declare_parameter("joint_names", DEFAULT_JOINTS)
        self.declare_parameter("cmd_topic_prefix", "/h1")
        self.declare_parameter("cmd_topic_suffix", "/cmd_pos")
        self.declare_parameter("output_topic", "/h1/hardware/commands")
        self.declare_parameter("publish_hz", 100.0)
        self.declare_parameter("zero_uncommanded", False)

        self._joints = list(self.get_parameter("joint_names").value)
        prefix = str(self.get_parameter("cmd_topic_prefix").value)
        suffix = str(self.get_parameter("cmd_topic_suffix").value)
        out_topic = self.get_parameter("output_topic").value
        hz = float(self.get_parameter("publish_hz").value)
        self._zero_uncommanded = bool(self.get_parameter("zero_uncommanded").value)

        self._values = {}
        self._received = set()
        for name in self._joints:
            topic = "%s/%s%s" % (prefix, name, suffix)
            self.create_subscription(
                Float64, topic, self._make_cb(name), RELIABLE_QOS)
            self.get_logger().info("command_bridge subscribing %s" % topic)

        self._pub = self.create_publisher(Float64MultiArray, out_topic, RELIABLE_QOS)
        self.create_timer(1.0 / hz, self._publish)
        self.get_logger().info(
            "command_bridge: %d joints -> %s @ %.0f Hz"
            % (len(self._joints), out_topic, hz))

    def _make_cb(self, name):
        def _cb(msg):
            if name not in self._received:
                self._received.add(name)
                self.get_logger().info("command_bridge: first cmd for %s" % name)
            self._values[name] = msg.data
        return _cb

    def _publish(self):
        active = self._joints if self._zero_uncommanded else sorted(self._received)
        msg = Float64MultiArray()
        dim = MultiArrayDimension()
        dim.label = "joint_cmd"
        dim.size = len(active)
        dim.stride = len(active)
        msg.layout.dim.append(dim)
        msg.data = [self._values.get(j, 0.0) for j in active]
        self._pub.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = CommandBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()