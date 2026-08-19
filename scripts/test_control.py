#!/usr/bin/env python3
import rclpy
from h1_control.control_server import ControlServer

rclpy.init()
node = ControlServer()
print("Node created, spinning for 3s...")
rclpy.spin_once(node, timeout_sec=3.0)
print("Spin done")
node.destroy_node()
rclpy.shutdown()