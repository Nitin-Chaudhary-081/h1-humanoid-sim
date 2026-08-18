#!/usr/bin/env python3
"""Direct M2 verification - send action goals without CLI."""
import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from h1_interfaces.action import RobotCommand
import time

class M2Verifier(Node):
    def __init__(self):
        super().__init__('m2_verifier')
        self._client = ActionClient(self, RobotCommand, '/h1/command')
        self._results = {}

    def send_goal(self, mode, distance=0.0, timeout=30.0):
        self.get_logger().info(f'Sending goal: mode={mode}, distance={distance}')
        if not self._client.wait_for_server(timeout_sec=10.0):
            self.get_logger().error('Action server not available')
            return False

        goal_msg = RobotCommand.Goal()
        goal_msg.mode = mode
        goal_msg.distance = distance

        future = self._client.send_goal_async(goal_msg)
        rclpy.spin_until_future_complete(self, future, timeout_sec=10.0)
        goal_handle = future.result()
        if not goal_handle.accepted:
            self.get_logger().error('Goal rejected')
            return False

        self.get_logger().info('Goal accepted, waiting for result...')
        result_future = goal_handle.get_result_async()
        rclpy.spin_until_future_complete(self, result_future, timeout_sec=timeout)
        result = result_future.result()
        if result:
            self.get_logger().info(f'Result: success={result.result.success}, message={result.result.message}')
            return result.result.success
        else:
            self.get_logger().error('Result timeout')
            return False

def main():
    rclpy.init()
    verifier = M2Verifier()
    
    # Test 1: Stand
    print('\n=== TEST 1: STAND ===')
    success = verifier.send_goal(RobotCommand.Goal.STAND, 0.0)
    print(f'Stand: {"PASS" if success else "FAIL"}')
    time.sleep(2)
    
    # Test 2: Walk
    print('\n=== TEST 2: WALK ===')
    success = verifier.send_goal(RobotCommand.Goal.WALK, 1.0)
    print(f'Walk: {"PASS" if success else "FAIL"}')
    time.sleep(2)
    
    # Test 3: Stop
    print('\n=== TEST 3: STOP ===')
    success = verifier.send_goal(RobotCommand.Goal.STOP, 0.0)
    print(f'Stop: {"PASS" if success else "FAIL"}')
    
    verifier.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()