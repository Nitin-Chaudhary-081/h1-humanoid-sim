"""Joint-state bridge: motor encoder data -> /h1/joint_states.

Thin republisher. The Unitree SDK companion process publishes the raw encoder
state on ``/h1/hardware/joint_states_raw`` (sensor_msgs/JointState); this node
re-exposes it on the contract topic ``/h1/joint_states`` with the configured
sensor frame id.

QoS: sensors are BEST_EFFORT/volatile per AGENTS.md.
"""

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy
from sensor_msgs.msg import JointState

SENSOR_QOS = QoSProfile(
    depth=10,
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
)


class JointStateBridge(Node):
    def __init__(self):
        super().__init__("h1_joint_state_bridge")
        self.declare_parameter("input_topic", "/h1/hardware/joint_states_raw")
        self.declare_parameter("output_topic", "/h1/joint_states")
        self.declare_parameter("frame_id", "pelvis")  # override if encoder msg lacks a frame

        in_topic = self.get_parameter("input_topic").value
        out_topic = self.get_parameter("output_topic").value
        self._frame_id = str(self.get_parameter("frame_id").value) or None

        self._pub = self.create_publisher(JointState, out_topic, SENSOR_QOS)
        self._sub = self.create_subscription(
            JointState, in_topic, self._cb, SENSOR_QOS)
        self.get_logger().info(
            "joint_state_bridge: %s -> %s" % (in_topic, out_topic))

    def _cb(self, msg):
        if self._frame_id and not msg.header.frame_id:
            msg.header.frame_id = self._frame_id
        self._pub.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = JointStateBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()