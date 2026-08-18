"""M4 h1_telemetry: lifecycle node logging telemetry + anomaly flags.

Skeleton — to be implemented by the h1_telemetry workstream.
Pure logic (ring buffer, CSV/JSONL writer, thresholds, IsolationForest)
lives in modules WITHOUT ROS imports for unit-testability.
"""
import rclpy
from rclpy.node import Node


class TelemetryNode(Node):
    def __init__(self):
        super().__init__('h1_telemetry_node')
        self.get_logger().info('h1_telemetry skeleton node started')


def main(args=None):
    rclpy.init(args=args)
    node = TelemetryNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
