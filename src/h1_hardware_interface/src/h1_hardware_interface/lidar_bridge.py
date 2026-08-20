"""Lidar bridge: L1/L2 -> /h1/lidar/scan.

Republishes the raw 2D scan published by the Unitree lidar driver on
``/h1/hardware/lidar_raw`` to the contract topic ``/h1/lidar/scan``.
"""

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy
from sensor_msgs.msg import LaserScan

SENSOR_QOS = QoSProfile(
    depth=10,
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
)


class LidarBridge(Node):
    def __init__(self):
        super().__init__("h1_lidar_bridge")
        self.declare_parameter("input_topic", "/h1/hardware/lidar_raw")
        self.declare_parameter("output_topic", "/h1/lidar/scan")
        self.declare_parameter("frame_id", "lidar_link")

        in_topic = self.get_parameter("input_topic").value
        out_topic = self.get_parameter("output_topic").value
        self._frame_id = str(self.get_parameter("frame_id").value) or None

        self._pub = self.create_publisher(LaserScan, out_topic, SENSOR_QOS)
        self.create_subscription(LaserScan, in_topic, self._cb, SENSOR_QOS)
        self.get_logger().info("lidar_bridge: %s -> %s" % (in_topic, out_topic))

    def _cb(self, msg):
        if self._frame_id:
            msg.header.frame_id = self._frame_id
        self._pub.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = LidarBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()