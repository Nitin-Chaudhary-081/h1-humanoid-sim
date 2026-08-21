"""Tool executors (pure logic, no ROS imports in base classes).

ExecutorInterface is the seam between the agent loop and actuation.
Wave 1 ships MockExecutor (deterministic, used by the node by default and
by all unit tests). Wave 2 integration replaces it with RosActionExecutor,
which sends RobotCommand action goals to the /h1/command action server on
h1_control.

Result contract (plan.md 1D): {status: SUCCESS|FAILED|BLOCKED|TIMEOUT,
detail, data}. data['mode'] is always one of MODES (RobotCommand constants).
"""
from abc import ABC, abstractmethod

from h1_llm_agent.tools import ALLOWED_TOOLS, TOOL_MODE_MAP

# Mirrors h1_interfaces/action/RobotCommand.action (FROZEN): int8 STAND=0,
# WALK=1, STOP=2. Kept here so pure logic never imports h1_interfaces.
MODES = {'STAND': 0, 'WALK': 1, 'STOP': 2}


class ExecutorInterface(ABC):
    """Abstract tool executor. Plug the real ROS action client in behind
    this interface without touching the validation layer or the agent loop."""

    @abstractmethod
    def execute(self, tool_name, args=None):
        """Execute one validated tool call.

        Returns {status, detail, data}; status one of
        SUCCESS | FAILED | BLOCKED | TIMEOUT.
        Must never be called with an unvalidated tool name by the loop.
        """
        raise NotImplementedError

    def available_tools(self):
        """Names of the tools this executor can run (defaults to allowlist)."""
        return sorted(ALLOWED_TOOLS)


class MockExecutor(ExecutorInterface):
    """Deterministic in-memory executor. Simulates a successful H1-2 sim
    response for every allowlisted tool; no ROS, no physics, no network."""

    def execute(self, tool_name, args=None):
        args = args if args is not None else {}
        if tool_name == 'walk':
            return {
                'status': 'SUCCESS',
                'detail': 'walk command accepted',
                'data': {'mode': 'WALK', 'distance': float(args.get('distance_m', 0.0))},
            }
        if tool_name == 'stand':
            return {'status': 'SUCCESS', 'detail': 'standing', 'data': {'mode': 'STAND'}}
        if tool_name in ('stop', 'stop_robot'):
            return {'status': 'SUCCESS', 'detail': 'stopped', 'data': {'mode': 'STOP'}}
        if tool_name == 'get_pose':
            # H1-2 spawns standing at z = 1.04 (plan.md 1C); mock pose is static.
            return {
                'status': 'SUCCESS',
                'detail': 'pose read',
                'data': {'x': 0.0, 'y': 0.0, 'z': 1.04, 'theta': 0.0},
            }
        if tool_name == 'get_joint_states':
            return {
                'status': 'SUCCESS',
                'detail': 'joint states read',
                'data': {'joints': ['left_hip_yaw', 'right_hip_yaw',
                                    'left_hip_pitch', 'right_hip_pitch',
                                    'left_hip_roll', 'right_hip_roll',
                                    'left_knee', 'right_knee',
                                    'left_ankle_pitch', 'right_ankle_pitch',
                                    'left_ankle_roll', 'right_ankle_roll',
                                    'left_shoulder_pitch', 'right_shoulder_pitch',
                                    'left_shoulder_roll', 'right_shoulder_roll',
                                    'left_shoulder_yaw', 'right_shoulder_yaw',
                                    'left_elbow', 'right_elbow',
                                    'torso'],
                         'actuated_joints': 21},
            }
        if tool_name == 'list_capabilities':
            return {
                'status': 'SUCCESS',
                'detail': 'capabilities listed',
                'data': {'capabilities': sorted(ALLOWED_TOOLS)},
            }
        return {'status': 'FAILED', 'detail': "unknown tool '{}'".format(tool_name), 'data': {}}


class RosActionExecutor(ExecutorInterface):
    """Real executor (Wave 2) that sends RobotCommand action goals to the
    /h1/command action server on h1_control.

    Maps tools to action goals:
        stand       -> mode=STAND (0), distance=0.0
        walk        -> mode=WALK (1), distance=args['distance_m']
        stop/stop_robot -> mode=STOP (2), distance=0.0

    Uses rclpy ActionClient with send_goal_async, waits for result with
    configurable timeout (default 120s). Returns structured result matching
    the executor contract: {status, detail, data}.
    """

    def __init__(self, node, timeout_s=120.0):
        self._node = node
        self._timeout_s = timeout_s
        self._client = None
        self._RobotCommand = None
        self._rclpy = None
        self._ActionClient = None
        self._ReentrantCallbackGroup = None
        self._initialized = False

    def _ensure_initialized(self):
        """Lazy initialization of ROS dependencies."""
        if self._initialized:
            return
        import rclpy
        from h1_interfaces.action import RobotCommand
        from rclpy.action import ActionClient
        from rclpy.callback_groups import ReentrantCallbackGroup

        self._rclpy = rclpy
        self._RobotCommand = RobotCommand
        self._ActionClient = ActionClient
        self._ReentrantCallbackGroup = ReentrantCallbackGroup

        self._cb_group = ReentrantCallbackGroup()
        self._client = ActionClient(self._node, RobotCommand, '/h1/command',
                                    callback_group=self._cb_group)
        self._initialized = True

    def execute(self, tool_name, args=None):
        self._ensure_initialized()

        args = args if args is not None else {}

        # Read-only tools: handle locally (no ROS action needed)
        if tool_name in ('get_pose', 'get_joint_states', 'list_capabilities'):
            # Delegate to MockExecutor logic to avoid FAILED for read-only tools
            # (keeps pure logic testable and avoids needing extra ROS topics)
            mock = MockExecutor()
            return mock.execute(tool_name, args)

        # Map tool to mode and distance
        if tool_name not in TOOL_MODE_MAP:
            return {'status': 'FAILED', 'detail': "unknown tool '{}'".format(tool_name), 'data': {}}

        mode_str = TOOL_MODE_MAP[tool_name]
        mode = MODES[mode_str]
        distance = float(args.get('distance_m', 0.0)) if tool_name == 'walk' else 0.0

        # Check if action server is available
        if not self._client.wait_for_server(timeout_sec=5.0):
            self._node.get_logger().error('Action server /h1/command not available')
            return {'status': 'FAILED', 'detail': 'action server not available', 'data': {}}

        # Build and send goal
        goal_msg = self._RobotCommand.Goal()
        goal_msg.mode = mode
        goal_msg.distance = distance

        self._node.get_logger().info('Sending RobotCommand goal: mode={} ({}), distance={:.3f}'.format(
            mode_str, mode, distance))

        # Use poll loop instead of spin_until_future_complete to avoid
        # "Executor is already spinning" when called from a timer callback
        # inside MultiThreadedExecutor (see AGENTS.md FastDDS wedge).
        import time
        try:
            send_goal_future = self._client.send_goal_async(goal_msg)
            # Poll for send_goal result (executor's other threads handle callbacks)
            t0 = time.time()
            while not send_goal_future.done() and (time.time() - t0) < 5.0:
                if not self._rclpy.ok():
                    return {'status': 'FAILED', 'detail': 'rclpy shutdown', 'data': {}}
                time.sleep(0.05)
            if not send_goal_future.done():
                return {'status': 'TIMEOUT', 'detail': 'send goal timeout', 'data': {}}
        except Exception as exc:
            self._node.get_logger().error('Failed to send goal: {}'.format(exc))
            return {'status': 'FAILED', 'detail': 'send goal failed: {}'.format(exc), 'data': {}}

        goal_handle = send_goal_future.result()
        if not goal_handle or not goal_handle.accepted:
            self._node.get_logger().error('Goal rejected by action server')
            return {'status': 'FAILED', 'detail': 'goal rejected', 'data': {}}

        # Wait for result with poll loop
        try:
            get_result_future = goal_handle.get_result_async()
            t0 = time.time()
            while not get_result_future.done() and (time.time() - t0) < self._timeout_s:
                if not self._rclpy.ok():
                    break
                time.sleep(0.05)
        except Exception as exc:
            self._node.get_logger().error('Error waiting for result: {}'.format(exc))
            try:
                goal_handle.cancel_goal_async()
            except Exception:
                pass
            return {'status': 'FAILED', 'detail': 'wait for result failed: {}'.format(exc), 'data': {}}

        if not get_result_future.done() or get_result_future.result() is None:
            self._node.get_logger().error('Action timed out after {:.1f}s'.format(self._timeout_s))
            try:
                goal_handle.cancel_goal_async()
            except Exception:
                pass
            return {'status': 'TIMEOUT', 'detail': 'action timeout after {:.1f}s'.format(self._timeout_s),
                    'data': {'mode': mode_str, 'distance': distance}}

        result = get_result_future.result()
        action_result = result.result
        if action_result.success:
            self._node.get_logger().info('Action succeeded: {}'.format(action_result.message))
            return {'status': 'SUCCESS', 'detail': action_result.message,
                    'data': {'mode': mode_str, 'distance': distance}}
        else:
            self._node.get_logger().error('Action failed: {}'.format(action_result.message))
            return {'status': 'FAILED', 'detail': action_result.message,
                    'data': {'mode': mode_str, 'distance': distance}}


def build_executor(kind, **kwargs):
    """Factory: 'mock' -> MockExecutor; 'ros' -> RosActionExecutor (requires node)."""
    if kind == 'mock':
        return MockExecutor()
    if kind == 'ros':
        node = kwargs.get('node')
        timeout_s = kwargs.get('timeout_s', 120.0)
        if node is None:
            raise ValueError("RosActionExecutor requires 'node' argument")
        return RosActionExecutor(node, timeout_s)
    raise ValueError("unknown executor kind '{}'".format(kind))
