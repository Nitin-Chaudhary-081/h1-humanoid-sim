#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from lifecycle_msgs.srv import ChangeState
from lifecycle_msgs.msg import Transition

def main():
    rclpy.init()
    node = Node('telemetry_lifecycle_driver')
    cli = node.create_client(ChangeState, '/h1_telemetry_node/change_state')
    if not cli.wait_for_service(timeout_sec=10):
        print('change_state service not available')
        rclpy.shutdown()
        return
    for trans, label in [(Transition.TRANSITION_CONFIGURE, 'configure'),
                         (Transition.TRANSITION_ACTIVATE, 'activate')]:
        req = ChangeState.Request()
        req.transition.id = trans
        fut = cli.call_async(req)
        rclpy.spin_until_future_complete(node, fut, timeout_sec=10)
        if fut.result() is None:
            print(label, 'failed')
        else:
            print(label, 'ok')
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()