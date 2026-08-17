#!/usr/bin/env python3
"""Capture frames from /camera while the H1 waves its arms. Saves PNGs to out_dir."""
import os
import sys
import time
import math

import cv2
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from rcl_interfaces.msg import SetParameters

from std_msgs.msg import Float64
from sensor_msgs.msg import Image

FPS = 15
DURATION = 6.0

ARM_JOINTS = [
    ('left_shoulder_pitch_joint', 0.55),
    ('left_elbow_joint', 0.35),
    ('right_shoulder_pitch_joint', -0.55),
    ('right_elbow_joint', -0.35),
]


class Capture(Node):
    def __init__(self, out_dir):
        super().__init__('capture_node')
        self.out_dir = out_dir
        self.frames = 0
        self.target = int(FPS * DURATION)
        self.t0 = time.monotonic()
        self.sim_time = None
        qos = QoSProfile(depth=2, reliability=ReliabilityPolicy.BEST_EFFORT)
        self.sub = self.create_subscription(Image, '/camera', self.on_image, qos_profile=qos)
        self.cmd = {}
        for name, _ in ARM_JOINTS:
            self.cmd[name] = self.create_publisher(Float64, f'/h1/{name}/cmd_pos', 10)
        self.timer = self.create_timer(1.0 / 100.0, self.command_loop)

    def on_image(self, msg):
        if self.frames >= self.target:
            return
        if self.frames % (30 // FPS) == 0:
            img = cv2.cvtColor(cv2.cvtColor(
                msg.data.reshape(msg.height, msg.width, -1), cv2.COLOR_RGB2BGR), cv2.COLOR_BGR2GRAY)
            path = os.path.join(self.out_dir, f'frame_{self.frames:04d}.png')
            cv2.imwrite(path, img)
            self.frames += 1

    def command_loop(self):
        t = time.monotonic() - self.t0
        for name, amp in ARM_JOINTS:
            v = amp * math.sin(2 * math.pi * 0.8 * t)
            self.cmd[name].publish(Float64(data=float(v)))
        if self.frames >= self.target:
            self.get_logger().info(f'captured {self.frames} frames, done')
            rclpy.get_global_executor().shutdown()


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else '/tmp/opencode/frames'
    os.makedirs(out_dir, exist_ok=True)
    rclpy.init()
    node = Capture(out_dir)
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()
    print(f'DONE {node.frames} frames -> {out_dir}')


if __name__ == '__main__':
    main()
