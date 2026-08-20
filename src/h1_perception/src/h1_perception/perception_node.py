"""ROS 2 node for ArUco marker perception — thin wrapper around ArucoDetector.

Subscribes: /camera/image_raw (sensor_msgs/Image, BEST_EFFORT)
Publishes: /h1/perception/detections (h1_interfaces/PerceptionFrame)

``--spawn-marker`` demo mode: when ``demo_mode=true`` the node ignores the
camera and publishes a synthetic PerceptionFrame on a timer (simulating an
ArUco marker at a known position), so the grasp pipeline can be tested
end-to-end without a camera.

Parameters (declared via declare_parameter):
- camera_matrix (double[]): 9 elements, row-major 3x3
- dist_coeffs (double[]): 5 elements
- marker_length (double): marker side length in meters
- dictionary (string): ArUco dictionary name
- publish_rate_hz (double): timer rate for publishing
- demo_mode (bool): enable synthetic marker publishing (default false)
- demo_marker_id (int): marker ID used in demo mode
- demo_pose_xyz (double[]): synthetic marker position [x, y, z] in camera frame
- demo_publish_rate_hz (double): demo-mode publish rate
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
from .demo import build_demo_frame

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
        self.declare_parameter('camera_frame', 'camera_link')
        # Demo (--spawn-marker) mode
        self.declare_parameter('demo_mode', False)
        self.declare_parameter('demo_marker_id', 42)
        self.declare_parameter('demo_pose_xyz', [0.5, 0.0, 0.5])
        self.declare_parameter('demo_publish_rate_hz', 10.0)

        if self.has_parameter('use_sim_time'):
            self.set_parameters([rclpy.parameter.Parameter('use_sim_time', value=True)])

        # Load parameters
        cam_matrix_flat = self.get_parameter('camera_matrix').get_parameter_value().double_array_value
        dist_coeffs = self.get_parameter('dist_coeffs').get_parameter_value().double_array_value
        marker_length = self.get_parameter('marker_length').get_parameter_value().double_value
        dictionary = self.get_parameter('dictionary').get_parameter_value().string_value
        publish_rate_hz = self.get_parameter('publish_rate_hz').get_parameter_value().double_value
        self.camera_frame = self.get_parameter('camera_frame').get_parameter_value().string_value
        self._demo_mode = bool(self.get_parameter('demo_mode').get_parameter_value().bool_value)
        self._demo_marker_id = self.get_parameter('demo_marker_id').get_parameter_value().integer_value
        self._demo_pose_xyz = self.get_parameter('demo_pose_xyz').get_parameter_value().double_array_value
        demo_rate_hz = self.get_parameter('demo_publish_rate_hz').get_parameter_value().double_value

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

        # Validate demo pose
        if len(self._demo_pose_xyz) != 3:
            self.get_logger().error(f'demo_pose_xyz must have 3 elements, got {len(self._demo_pose_xyz)}')
            raise ValueError('demo_pose_xyz must have 3 elements')

        # Initialize detector (always validate camera params so a bad
        # calibration surfaces even in demo mode)
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

        # CV Bridge (only used in real-camera mode)
        self._bridge = CvBridge()

        # Publisher
        self._pub = self.create_publisher(
            PerceptionFrame,
            '/h1/perception/detections',
            10,
        )

        # Subscription (skipped in demo mode — no camera needed)
        self._sub = None
        if not self._demo_mode:
            self._sub = self.create_subscription(
                Image,
                '/camera/image_raw',
                self._image_callback,
                SENSOR_QOS,
            )

        # Timer for publishing (rate-limited)
        rate = 1.0 / (demo_rate_hz if self._demo_mode else publish_rate_hz)
        self._timer = self.create_timer(
            rate,
            self._publish_timer_callback,
        )

        # Latest detections buffer
        self._latest_detections = []
        self._latest_header = None

        mode = 'demo (--spawn-marker)' if self._demo_mode else 'camera'
        self.get_logger().info(
            f'h1_perception_node started: mode={mode}, dictionary={dictionary}, '
            f'marker_length={marker_length}m, publish_rate={publish_rate_hz}Hz'
        )
        if self._demo_mode:
            self.get_logger().info(
                f'demo mode: publishing synthetic marker id={self._demo_marker_id} '
                f'at {self._demo_pose_xyz} (camera frame)'
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

    def _build_perception_frame(self, detections, header) -> PerceptionFrame:
        """Convert detections to a PerceptionFrame message."""
        frame = PerceptionFrame()
        frame.header = header

        for det in detections:
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

        return frame

    def _publish_timer_callback(self):
        """Publish latest detections at configured rate."""
        if self._demo_mode:
            self._publish_demo_frame()
            return

        if self._latest_header is None:
            return

        frame = self._build_perception_frame(self._latest_detections, self._latest_header)
        self._pub.publish(frame)

    def _publish_demo_frame(self):
        """Publish a synthetic PerceptionFrame (--spawn-marker demo mode)."""
        try:
            demo = build_demo_frame(
                marker_id=self._demo_marker_id,
                pose_xyz=self._demo_pose_xyz,
                frame_id=self.camera_frame,
                stamp_nanosec=self.get_clock().now().nanoseconds,
            )
        except ValueError as exc:
            self.get_logger().error(f'demo frame build failed: {exc}')
            return

        header = Header()
        header.stamp = self.get_clock().now().to_msg()
        header.frame_id = demo.frame_id
        frame = self._build_perception_frame(self._demo_detections_as_aruco(demo), header)
        self._pub.publish(frame)

    def _demo_detections_as_aruco(self, demo):
        """Wrap demo detections in the minimal Pose containers used by the
        real detector so _build_perception_frame works unchanged."""
        from .aruco import ArucoDetection, Pose as APose, Point as APoint, Quaternion as AQuaternion

        out = []
        for d in demo.detections:
            pose = APose(
                position=APoint(*d.position),
                orientation=AQuaternion(*d.orientation),
            )
            out.append(ArucoDetection(
                marker_id=d.marker_id,
                rvec=np.zeros((3, 1)),
                tvec=np.array(d.position, dtype=np.float64).reshape(3, 1),
                corners=np.zeros((4, 2)),
                pose=pose,
            ))
        return out

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
        if self._sub is not None:
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