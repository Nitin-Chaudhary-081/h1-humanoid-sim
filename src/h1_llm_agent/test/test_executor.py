"""Unit tests for RosActionExecutor (pure pytest, no ROS imports in test logic).

The executor's ROS dependencies are injected via a fake action client so tests
run without rclpy, FastDDS, or a running action server.
"""
import sys
import types
import pytest

# Mock ROS modules before importing the executor
mock_rclpy = types.ModuleType('rclpy')
mock_rclpy.action = types.ModuleType('rclpy.action')
mock_rclpy.callback_groups = types.ModuleType('rclpy.callback_groups')
mock_rclpy.spin_until_future_complete = lambda *a, **k: None

mock_interfaces = types.ModuleType('h1_interfaces')
mock_interfaces.action = types.ModuleType('h1_interfaces.action')

sys.modules['rclpy'] = mock_rclpy
sys.modules['rclpy.action'] = mock_rclpy.action
sys.modules['rclpy.callback_groups'] = mock_rclpy.callback_groups
sys.modules['h1_interfaces'] = mock_interfaces
sys.modules['h1_interfaces.action'] = mock_interfaces.action

from h1_llm_agent.executor import (
    MODES,
    TOOL_MODE_MAP,
    ExecutorInterface,
    MockExecutor,
    RosActionExecutor,
    build_executor,
)
from h1_llm_agent.tools import ACTUATION_TOOLS, ALLOWED_TOOLS


# ---------------------------------------------------------------------------
# Fake action client for testing (no ROS imports)
# ---------------------------------------------------------------------------

class FakeGoalHandle:
    def __init__(self, accepted=True, result=None):
        self.accepted = accepted
        self._result = result
        self.cancel_called = False

    def get_result_async(self):
        class FakeFuture:
            def __init__(self, result):
                self._result = result
                self.done_flag = True

            def result(self):
                return self._result

            def done(self):
                return self.done_flag

        return FakeFuture(self._result)

    def cancel_goal_async(self):
        self.cancel_called = True
        class FakeCancelFuture:
            def __init__(self):
                self.done_flag = True
            def done(self):
                return True
        return FakeCancelFuture()


class FakeActionClient:
    def __init__(self, server_available=True, goal_handle=None):
        self._server_available = server_available
        self._goal_handle = goal_handle or FakeGoalHandle()
        self.last_goal = None
        self.wait_called = False

    def wait_for_server(self, timeout_sec=5.0):
        self.wait_called = True
        return self._server_available

    def send_goal_async(self, goal_msg):
        self.last_goal = goal_msg
        class FakeSendGoalFuture:
            def __init__(self, goal_handle):
                self._goal_handle = goal_handle
                self.done_flag = True

            def result(self):
                return self._goal_handle

            def done(self):
                return self.done_flag

        return FakeSendGoalFuture(self._goal_handle)


class FakeRobotCommand:
    class Goal:
        def __init__(self):
            self.mode = 0
            self.distance = 0.0


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBuildExecutor:
    def test_mock_executor(self):
        ex = build_executor('mock')
        assert isinstance(ex, MockExecutor)

    def test_ros_executor_requires_node(self):
        with pytest.raises(ValueError, match="requires 'node' argument"):
            build_executor('ros')

    def test_ros_executor_with_node(self):
        fake_node = types.SimpleNamespace(
            get_logger=lambda: types.SimpleNamespace(
                info=lambda *a, **k: None,
                error=lambda *a, **k: None,
                warn=lambda *a, **k: None,
            )
        )
        ex = build_executor('ros', node=fake_node, timeout_s=10.0)
        assert isinstance(ex, RosActionExecutor)

    def test_unknown_kind_raises(self):
        with pytest.raises(ValueError, match="unknown executor kind"):
            build_executor('unknown')


class TestRosActionExecutor:
    def _make_executor(self, client, timeout_s=10.0):
        fake_node = types.SimpleNamespace(
            get_logger=lambda: types.SimpleNamespace(
                info=lambda *a, **k: None,
                error=lambda *a, **k: None,
                warn=lambda *a, **k: None,
            )
        )
        ex = RosActionExecutor.__new__(RosActionExecutor)
        ex._node = fake_node
        ex._timeout_s = timeout_s
        ex._client = client
        ex._initialized = True
        ex._RobotCommand = FakeRobotCommand
        ex._rclpy = types.SimpleNamespace(spin_until_future_complete=lambda *a, **k: None)
        return ex

    def test_execute_stand_success(self):
        result = types.SimpleNamespace(
            result=types.SimpleNamespace(success=True, message='standing')
        )
        goal_handle = FakeGoalHandle(accepted=True, result=result)
        client = FakeActionClient(server_available=True, goal_handle=goal_handle)
        ex = self._make_executor(client)

        outcome = ex.execute('stand')

        assert outcome['status'] == 'SUCCESS'
        assert outcome['data']['mode'] == 'STAND'
        assert outcome['data']['distance'] == 0.0
        assert client.last_goal is not None
        assert client.last_goal.mode == MODES['STAND']
        assert client.last_goal.distance == 0.0

    def test_execute_walk_success(self):
        result = types.SimpleNamespace(
            result=types.SimpleNamespace(success=True, message='walked 0.3 m')
        )
        goal_handle = FakeGoalHandle(accepted=True, result=result)
        client = FakeActionClient(server_available=True, goal_handle=goal_handle)
        ex = self._make_executor(client)

        outcome = ex.execute('walk', {'distance_m': 0.3})

        assert outcome['status'] == 'SUCCESS'
        assert outcome['data']['mode'] == 'WALK'
        assert outcome['data']['distance'] == 0.3
        assert client.last_goal.mode == MODES['WALK']
        assert client.last_goal.distance == 0.3

    def test_execute_stop_success(self):
        result = types.SimpleNamespace(
            result=types.SimpleNamespace(success=True, message='stopped')
        )
        goal_handle = FakeGoalHandle(accepted=True, result=result)
        client = FakeActionClient(server_available=True, goal_handle=goal_handle)
        ex = self._make_executor(client)

        outcome = ex.execute('stop')

        assert outcome['status'] == 'SUCCESS'
        assert outcome['data']['mode'] == 'STOP'
        assert client.last_goal.mode == MODES['STOP']

    def test_execute_stop_robot_success(self):
        result = types.SimpleNamespace(
            result=types.SimpleNamespace(success=True, message='halted')
        )
        goal_handle = FakeGoalHandle(accepted=True, result=result)
        client = FakeActionClient(server_available=True, goal_handle=goal_handle)
        ex = self._make_executor(client)

        outcome = ex.execute('stop_robot')

        assert outcome['status'] == 'SUCCESS'
        assert outcome['data']['mode'] == 'STOP'
        assert client.last_goal.mode == MODES['STOP']

    def test_execute_action_server_unavailable(self):
        client = FakeActionClient(server_available=False)
        ex = self._make_executor(client)

        outcome = ex.execute('stand')

        assert outcome['status'] == 'FAILED'
        assert outcome['detail'] == 'action server not available'
        assert client.wait_called

    def test_execute_goal_rejected(self):
        goal_handle = FakeGoalHandle(accepted=False)
        client = FakeActionClient(server_available=True, goal_handle=goal_handle)
        ex = self._make_executor(client)

        outcome = ex.execute('stand')

        assert outcome['status'] == 'FAILED'
        assert outcome['detail'] == 'goal rejected'

    def test_execute_action_failed(self):
        result = types.SimpleNamespace(
            result=types.SimpleNamespace(success=False, message='walk failed: balance lost')
        )
        goal_handle = FakeGoalHandle(accepted=True, result=result)
        client = FakeActionClient(server_available=True, goal_handle=goal_handle)
        ex = self._make_executor(client)

        outcome = ex.execute('walk', {'distance_m': 1.0})

        assert outcome['status'] == 'FAILED'
        assert outcome['detail'] == 'walk failed: balance lost'
        assert outcome['data']['mode'] == 'WALK'
        assert outcome['data']['distance'] == 1.0

    def test_execute_timeout(self):
        goal_handle = FakeGoalHandle(accepted=True, result=None)
        client = FakeActionClient(server_available=True, goal_handle=goal_handle)
        ex = self._make_executor(client, timeout_s=0.001)

        outcome = ex.execute('walk', {'distance_m': 1.0})

        assert outcome['status'] == 'TIMEOUT'
        assert 'timeout' in outcome['detail'].lower()
        assert outcome['data']['mode'] == 'WALK'
        assert outcome['data']['distance'] == 1.0
        assert goal_handle.cancel_called

    def test_execute_unknown_tool(self):
        client = FakeActionClient(server_available=True)
        ex = self._make_executor(client)

        outcome = ex.execute('dance')

        assert outcome['status'] == 'FAILED'
        assert "unknown tool" in outcome['detail']

    def test_execute_send_goal_exception(self):
        class BadClient(FakeActionClient):
            def send_goal_async(self, goal_msg):
                raise RuntimeError('DDS error')

        client = BadClient(server_available=True)
        ex = self._make_executor(client)

        outcome = ex.execute('stand')

        assert outcome['status'] == 'FAILED'
        assert 'send goal failed' in outcome['detail']

    def test_execute_wait_result_exception(self):
        class BadGoalHandle(FakeGoalHandle):
            def get_result_async(self):
                raise RuntimeError('spin error')

        client = FakeActionClient(server_available=True, goal_handle=BadGoalHandle(accepted=True))
        ex = self._make_executor(client)

        outcome = ex.execute('stand')

        assert outcome['status'] == 'FAILED'
        assert 'wait for result failed' in outcome['detail']

    def test_interface_compliance(self):
        fake_node = types.SimpleNamespace(
            get_logger=lambda: types.SimpleNamespace(
                info=lambda *a, **k: None,
                error=lambda *a, **k: None,
            )
        )
        client = FakeActionClient()
        ex = RosActionExecutor.__new__(RosActionExecutor)
        ex._node = fake_node
        ex._timeout_s = 10.0
        ex._client = client

        assert isinstance(ex, ExecutorInterface)
        assert set(ex.available_tools()) == set(ALLOWED_TOOLS)

    def test_modes_match_frozen_constants(self):
        assert MODES == {'STAND': 0, 'WALK': 1, 'STOP': 2}
        assert set(TOOL_MODE_MAP.keys()) == set(ACTUATION_TOOLS)
        for mode in TOOL_MODE_MAP.values():
            assert mode in MODES


class TestMockExecutor:
    def test_actuation_tools_return_mode(self):
        ex = MockExecutor()
        assert ex.execute('stand')['data']['mode'] == 'STAND'
        assert ex.execute('walk', {'distance_m': 2.5})['data']['mode'] == 'WALK'
        assert ex.execute('walk', {'distance_m': 2.5})['data']['distance'] == 2.5
        assert ex.execute('stop')['data']['mode'] == 'STOP'
        assert ex.execute('stop_robot')['data']['mode'] == 'STOP'

    def test_readonly_tools_return_data(self):
        ex = MockExecutor()
        pose = ex.execute('get_pose')
        assert pose['status'] == 'SUCCESS'
        assert pose['data']['z'] == 1.04
        joints = ex.execute('get_joint_states')
        assert joints['data']['actuated_joints'] == 21
        caps = ex.execute('list_capabilities')
        assert set(caps['data']['capabilities']) == ALLOWED_TOOLS

    def test_unknown_tool_failed(self):
        ex = MockExecutor()
        assert ex.execute('dance')['status'] == 'FAILED'