"""M2 h1_control: Stand/Walk/Stop action server driving /h1/<joint>/cmd_pos.

Skeleton — to be implemented by the h1_control workstream.
Pure logic lives in stand.py / motion_player.py (no ROS imports in unit tests).
"""
import rclpy
from rclpy.node import Node


class ControlServer(Node):
    def __init__(self):
        super().__init__('h1_control_server')
        self.get_logger().info('h1_control skeleton node started')


def main(args=None):
    rclpy.init(args=args)
    node = ControlServer()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
