"""M3 h1_llm_agent: Gemini agent node (thin ROS wrapper).

Subscribes  /h1/llm/input_text (std_msgs/String) and /estop (std_msgs/Bool).
Publishes  /h1/llm/intent, /h1/llm/tool_calls, /h1/llm/events (JSON strings).

All logic lives in pure modules (validation, executor, audit, prompt,
tools, loop) with no ROS imports. Callbacks only enqueue/flip state; the
tool loop runs in a timer, never inside a subscription callback (AGENTS 6).

Graceful degradation: without GEMINI_API_KEY the node logs a warning once
and every model call yields a BLOCKED 'no api key' outcome — the node keeps
running and events/audit still record the turn.
"""
import json
import os
from collections import deque

import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter
from std_msgs.msg import Bool, String

from h1_llm_agent.audit import AuditWriter
from h1_llm_agent.executor import build_executor
from h1_llm_agent.loop import GeminiModel, canonicalize_intent, run_tool_loop
from h1_llm_agent.prompt import SYSTEM_PROMPT
from h1_llm_agent.validation import ToolValidator

QUEUE_PROCESS_PERIOD_S = 0.5


class AgentNode(Node):
    def __init__(self):
        super().__init__('h1_llm_agent')

        self._declare_params()
        executor_type = self.get_parameter('executor_type').value
        action_timeout = self.get_parameter('action_timeout_sec').value
        self._executor = build_executor(executor_type, node=self, timeout_s=action_timeout)
        self._validator = ToolValidator(
            max_same_rejection=self.get_parameter('max_same_rejection').value,
            rate_limit_per_min=self.get_parameter('rate_limit_per_min').value,
            walk_distance_min=self.get_parameter('walk_distance_min').value,
            walk_distance_max=self.get_parameter('walk_distance_max').value,
            allowed_tools=self.get_parameter('allowed_tools').value,
            audit_path=self.get_parameter('audit_log').value,
        )
        self._audit = AuditWriter(self.get_parameter('audit_log').value)
        self._model = GeminiModel(
            model=self.get_parameter('model').value,
            thinking_level=self.get_parameter('thinking_level').value,
            step_timeout_s=self.get_parameter('step_timeout_s').value,
            api_key=os.environ.get('GEMINI_API_KEY', ''),
            system_instruction=SYSTEM_PROMPT,
        )

        self._estop_active = False
        self._estop_logged = False
        self._api_key_warned = False
        self._input_queue = deque()

        self._sub_input = self.create_subscription(
            String, self.get_parameter('input_topic').value,
            self._on_input_text, 10)
        self._sub_estop = self.create_subscription(
            Bool, self.get_parameter('estop_topic').value,
            self._on_estop, 10)

        self._pub_intent = self.create_publisher(
            String, self.get_parameter('intent_topic').value, 10)
        self._pub_tool_calls = self.create_publisher(
            String, self.get_parameter('tool_calls_topic').value, 10)
        self._pub_events = self.create_publisher(
            String, self.get_parameter('events_topic').value, 10)

        self._timer = self.create_timer(QUEUE_PROCESS_PERIOD_S, self._process_queue)
        self.get_logger().info(
            'h1_llm_agent ready (executor={}, model={}, api_key={})'.format(
                executor_type,
                self.get_parameter('model').value,
                'set' if self._model.has_api_key() else 'MISSING'))

    def _declare_params(self):
        self.declare_parameter('model', 'gemini-3.6-flash')
        self.declare_parameter('thinking_level', 'low')
        self.declare_parameter('max_tool_steps', 15)
        self.declare_parameter('step_timeout_s', 20.0)
        self.declare_parameter('max_same_rejection', 2)
        self.declare_parameter('rate_limit_per_min', 10)
        self.declare_parameter('walk_distance_min', 0.05)
        self.declare_parameter('walk_distance_max', 1.0)
        self.declare_parameter('allowed_tools', ['stand', 'walk', 'stop', 'stop_robot'])
        self.declare_parameter('estop_topic', '/estop')
        self.declare_parameter('input_topic', '/h1/llm/input_text')
        self.declare_parameter('intent_topic', '/h1/llm/intent')
        self.declare_parameter('tool_calls_topic', '/h1/llm/tool_calls')
        self.declare_parameter('events_topic', '/h1/llm/events')
        self.declare_parameter('audit_log',
                               '/home/ubuntu/humanoid_sim_ws/data/llm_audit.jsonl')
        self.declare_parameter('executor_type', 'mock')
        self.declare_parameter('action_timeout_sec', 120.0)
        self.set_parameters([Parameter('use_sim_time', Parameter.Type.BOOL, True)])

    # -- callbacks (non-blocking: only enqueue / flip state) --------------

    def _on_input_text(self, msg):
        self._input_queue.append(msg.data)

    def _on_estop(self, msg):
        active = bool(msg.data)
        if active != self._estop_active:
            self._estop_active = active
            self._estop_logged = False
            self._publish_event({'event': 'estop', 'active': active})
            if active:
                self.get_logger().warn('ESTOP ACTIVE — actuation tools blocked')
            else:
                self.get_logger().info('estop cleared — actuation allowed')

    # -- queue processing (timer context, never a subscription callback) --

    def _process_queue(self):
        while self._input_queue:
            text = self._input_queue.popleft()
            try:
                self._handle_input(text)
            except Exception as exc:  # keep the node alive on any turn error
                self.get_logger().error('turn failed: {}'.format(exc))
                self._publish_event({'event': 'failed', 'detail': str(exc)})

    def _handle_input(self, text):
        intent = canonicalize_intent(text)
        self._publish(self._pub_intent, intent)

        if not self._model.has_api_key():
            if not self._api_key_warned:
                self.get_logger().warn(
                    'GEMINI_API_KEY not set — model calls will be BLOCKED '
                    '("no api key"); set env GEMINI_API_KEY to enable')
                self._api_key_warned = True
            event = {'event': 'blocked', 'detail': 'no api key'}
            self._publish_event(event)
            self._audit.write({
                'input_text': text,
                'intent': intent,
                'tool_calls': [],
                'results': [],
                'estop_active': self._estop_active,
                'outcome': 'BLOCKED',
            })
            return

        outcome = run_tool_loop(
            model=self._model,
            user_text=text,
            validator=self._validator,
            executor=self._executor,
            estop_active=lambda: self._estop_active,
            max_tool_steps=self.get_parameter('max_tool_steps').value,
            audit=self._audit,
            intent=intent,
        )

        for call in outcome['tool_calls']:
            self._publish(self._pub_tool_calls,
                          json.dumps({'input_text': text, **call}))
        for event in outcome['events']:
            self._publish_event(event)
        self.get_logger().info(
            'turn done: outcome={} steps={} tools_executed={}'.format(
                outcome['outcome'], outcome['steps'], len(outcome['tool_calls'])))

    # -- helpers -----------------------------------------------------------

    def _publish_event(self, event):
        self._publish(self._pub_events, json.dumps(event, default=str))

    @staticmethod
    def _publish(publisher, payload):
        msg = String()
        msg.data = payload
        publisher.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = AgentNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
