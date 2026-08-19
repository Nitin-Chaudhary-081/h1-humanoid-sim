"""ROS 2 node for ArUco marker perception — thin wrapper around ArucoDetector.

Subscribes: /camera/image_raw (sensor_msgs/Image, BEST_EFFORT)
Publishes: /h1/perception/detections (h1_interfaces/PerceptionFrame)

Parameters (declared via declare_parameter):
- camera_matrix (double[]): 9 elements, row-major 3x3
- dist_coeffs (double[]): 5 elements
- marker_length (double): marker side length in meters
- dictionary (string): ArUco dictionary name
- publish_rate_hz (double): timer rate for publishing
"""

import numpy as np

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from cv_bridge import CvBridge

from h1_interfaces.msg import PerceptionFrame, PerceptionDetection
from geometry_msgs.msg import Pose, Point, Quaternion
from std_msgs.msg import Header
from sensor_msgs.msg import Image

from .aruco import ArucoDetector, CV2_AVAILABLE

SENSOR_QOS = QoSProfile(
    depth=10,
    reliability=ReliabilityPolicy.BEST_EFFORT,
    history=HistoryPolicy.KEEP_LAST,
)


class PerceptionNode(Node):
    def __init__(self):
        super().__init__('h1_perception_node')

        # Declare parameters
        self.declare_parameter('camera_matrix', [640.0, 0.0, 320.0, 0.0, 640.0, 240.0, 0.0, 0.0, 1.0])
        self.declare_parameter('dist_coeffs', [0.0, 0.0, 0.0, 0.0, 0.0])
        self.declare_parameter('marker_length', 0.1)
        self.declare_parameter('dictionary', 'DICT_6X6_250')
        self.declare_parameter('publish_rate_hz', 10.0)

        if self.has_parameter('use_sim_time'):
            self.set_parameters([rclpy.parameter.Parameter('use_sim_time', value=True)])

        # Load parameters
        cam_matrix_flat = self.get_parameter('camera_matrix').get_parameter_value().double_array_value
        dist_coeffs = self.get_parameter('dist_coeffs').get_parameter_value().double_array_value
        marker_length = self.get_parameter('marker_length').get_parameter_value().double_value
        dictionary = self.get_parameter('dictionary').get_parameter_value().string_value
        publish_rate_hz = self.get_parameter('publish_rate_hz').get_parameter_value().double_value

        # Validate and reshape camera matrix
        if len(cam_matrix_flat) != 9:
            self.get_logger().error(f'camera_matrix must have 9 elements, got {len(cam_matrix_flat)}')
            raise ValueError('camera_matrix must have 9 elements')
        camera_matrix = np.array(cam_matrix_flat, dtype=np.float64).reshape(3, 3)

        # Validate dist coeffs
        if len(dist_coeffs) != 5:
            self.get_logger().error(f'dist_coeffs must have 5 elements, got {len(dist_coeffs)}')
            raise ValueError('dist_coeffs must have 5 elements')
        dist_coeffs = np.array(dist_coeffs, dtype=np.float64)

        # Initialize detector
        try:
            self._detector = ArucoDetector(
                camera_matrix=camera_matrix,
                dist_coeffs=dist_coeffs,
                marker_length=marker_length,
                dictionary_id=dictionary,
            )
        except Exception as exc:
            self.get_logger().error(f'Failed to initialize ArucoDetector: {exc}')
            raise

        # CV Bridge
        self._bridge = CvBridge()

        # Publisher
        self._pub = self.create_publisher(
            PerceptionFrame,
            '/h1/perception/detections',
            10,
        )

        # Subscription
        self._sub = self.create_subscription(
            Image,
            '/camera/image_raw',
            self._image_callback,
            SENSOR_QOS,
        )

        # Timer for publishing (rate-limited)
        self._timer = self.create_timer(
            1.0 / publish_rate_hz,
            self._publish_timer_callback,
        )

        # Latest detections buffer
        self._latest_detections = []
        self._latest_header = None

        self.get_logger().info(
            f'h1_perception_node started: dictionary={dictionary}, '
            f'marker_length={marker_length}m, publish_rate={publish_rate_hz}Hz'
        )

    def _image_callback(self, msg: Image):
        """Process incoming image and run detection."""
        try:
            cv_image = self._bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
        except Exception as exc:
            self.get_logger().warn(f'cv_bridge conversion failed: {exc}')
            return

        try:
            detections = self._detector.detect(cv_image)
        except Exception as exc:
            self.get_logger().warn(f'ArUco detection failed: {exc}')
            detections = []

        self._latest_detections = detections
        self._latest_header = msg.header

    def _publish_timer_callback(self):
        """Publish latest detections at configured rate."""
        if self._latest_header is None:
            return

        frame = PerceptionFrame()
        frame.header = self._latest_header

        for det in self._latest_detections:
            pd = PerceptionDetection()
            pd.marker_id = det.marker_id

            # Convert our Pose to geometry_msgs/Pose
            pose = Pose()
            pose.position = Point(
                x=det.pose.position.x,
                y=det.pose.position.y,
                z=det.pose.position.z,
            )
            pose.orientation = Quaternion(
                x=det.pose.orientation.x,
                y=det.pose.orientation.y,
                z=det.pose.orientation.z,
                w=det.pose.orientation.w,
            )
            pd.pose = pose
            pd.confidence = 1.0  # ArUco detection is deterministic

            frame.detections.append(pd)

        self._pub.publish(frame)

    def destroy_node(self):
        self._pub.destroy()
        self._sub.destroy()
        self._timer.destroy()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = PerceptionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()