"""M3 h1_llm_agent: Gemini agent node (google-genai, gemini-3.6-flash).

Skeleton — to be implemented by the h1_llm_agent workstream.
Pure logic (validation layer, tool schema, loop-breaker, audit writer)
lives in modules WITHOUT ROS imports for unit-testability.
API key comes from env GEMINI_API_KEY (never from config files).
"""
import rclpy
from rclpy.node import Node


class AgentNode(Node):
    def __init__(self):
        super().__init__('h1_llm_agent_node')
        self.get_logger().info('h1_llm_agent skeleton node started')


def main(args=None):
    rclpy.init(args=args)
    node = AgentNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
