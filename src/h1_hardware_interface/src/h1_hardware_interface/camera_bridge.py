"""Camera bridge: RGB-D driver -> /camera/image_raw + camera_info.

Republishes the RGB frames and camera_info published by the camera driver
(RGB-D camera such as RealSense/Orbbec) on the ``/h1/hardware/camera/*``
topics to the contract topics consumed by h1_perception and Foxglove.
"""

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy
from sensor_msgs.msg import CameraInfo, Image

SENSOR_QOS = QoSProfile(
    depth=10,
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
)
INFO_QOS = QoSProfile(
    depth=10,
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
)


class CameraBridge(Node):
    def __init__(self):
        super().__init__("h1_camera_bridge")
        self.declare_parameter("input_image_topic", "/h1/hardware/camera/image_raw")
        self.declare_parameter("input_info_topic", "/h1/hardware/camera/info_raw")
        self.declare_parameter("output_image_topic", "/camera/image_raw")
        self.declare_parameter("output_info_topic", "/camera/color/camera_info")

        in_img = self.get_parameter("input_image_topic").value
        in_info = self.get_parameter("input_info_topic").value
        out_img = self.get_parameter("output_image_topic").value
        out_info = self.get_parameter("output_info_topic").value

        self._pub_img = self.create_publisher(Image, out_img, SENSOR_QOS)
        self._pub_info = self.create_publisher(CameraInfo, out_info, INFO_QOS)
        self.create_subscription(Image, in_img, self._cb_img, SENSOR_QOS)
        self.create_subscription(CameraInfo, in_info, self._cb_info, INFO_QOS)
        self.get_logger().info(
            "camera_bridge: %s -> %s, %s -> %s" % (in_img, out_img, in_info, out_info))

    def _cb_img(self, msg):
        self._pub_img.publish(msg)

    def _cb_info(self, msg):
        self._pub_info.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = CameraBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()