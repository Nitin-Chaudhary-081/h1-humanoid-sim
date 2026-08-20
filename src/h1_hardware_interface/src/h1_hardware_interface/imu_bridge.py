"""IMU bridge: body IMU -> /h1/imu/data.

Republishes the raw IMU sample published by the Unitree SDK companion process
on ``/h1/hardware/imu_raw`` to the contract topic ``/h1/imu/data``.
"""

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy
from sensor_msgs.msg import Imu

SENSOR_QOS = QoSProfile(
    depth=10,
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
)


class ImuBridge(Node):
    def __init__(self):
        super().__init__("h1_imu_bridge")
        self.declare_parameter("input_topic", "/h1/hardware/imu_raw")
        self.declare_parameter("output_topic", "/h1/imu/data")
        self.declare_parameter("frame_id", "imu_link")

        in_topic = self.get_parameter("input_topic").value
        out_topic = self.get_parameter("output_topic").value
        self._frame_id = str(self.get_parameter("frame_id").value) or None

        self._pub = self.create_publisher(Imu, out_topic, SENSOR_QOS)
        self.create_subscription(Imu, in_topic, self._cb, SENSOR_QOS)
        self.get_logger().info("imu_bridge: %s -> %s" % (in_topic, out_topic))

    def _cb(self, msg):
        if self._frame_id:
            msg.header.frame_id = self._frame_id
        self._pub.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = ImuBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()