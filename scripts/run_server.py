#!/usr/bin/env python3
import rclpy
from rclpy.executors import MultiThreadedExecutor
from h1_control.control_server import ControlServer

rclpy.init()
node = ControlServer()
executor = MultiThreadedExecutor()
executor.add_node(node)
try:
    executor.spin()
except KeyboardInterrupt:
    pass
finally:
    node.destroy_node()
    rclpy.shutdown()