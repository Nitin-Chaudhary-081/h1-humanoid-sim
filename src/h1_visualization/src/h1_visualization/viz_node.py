"""M2/M3 h1_visualization: publishes markers for /h1/control_state + goal poses.

Skeleton — to be implemented by the h1_visualization workstream.
Pure logic (layout JSON validation etc.) goes in modules without ROS imports.
"""
import rclpy
from rclpy.node import Node


class VizNode(Node):
    def __init__(self):
        super().__init__('h1_viz_node')
        self.get_logger().info('h1_visualization skeleton node started')


def main(args=None):
    rclpy.init(args=args)
    node = VizNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
