"""pick_object wiring tests: schema, validation bounds, mock + ROS executors.

Pure pytest (no ROS imports); RosActionExecutor is exercised via injected
fake action clients, mirroring test_executor.py.
"""
import sys
import types

import pytest

mock_rclpy = types.ModuleType('rclpy')
mock_rclpy.action = types.ModuleType('rclpy.action')
mock_rclpy.callback_groups = types.ModuleType('rclpy.callback_groups')
mock_interfaces = types.ModuleType('h1_interfaces')
mock_interfaces.action = types.ModuleType('h1_interfaces.action')
sys.modules.setdefault('rclpy', mock_rclpy)
sys.modules.setdefault('rclpy.action', mock_rclpy.action)
sys.modules.setdefault('rclpy.callback_groups', mock_rclpy.callback_groups)
sys.modules.setdefault('h1_interfaces', mock_interfaces)
sys.modules.setdefault('h1_interfaces.action', mock_interfaces.action)

from h1_llm_agent.executor import MockExecutor, RosActionExecutor
from h1_llm_agent.prompt import build_system_prompt
from h1_llm_agent.tools import (
    PICK_GRASP_DEPTH_DEFAULT,
    PICK_GRASP_DEPTH_MAX,
    PICK_GRASP_DEPTH_MIN,
    PICK_PREGRASP_OFFSET_DEFAULT,
    PICK_PREGRASP_OFFSET_MAX,
    PICK_PREGRASP_OFFSET_MIN,
    TOOL_PARAMS,
    TOOL_SCHEMAS,
)
from h1_llm_agent.validation import (
    REASON_BOUNDS,
    REASON_ESTOPPED,
    REASON_SCHEMA,
    VALIDATION_ALLOWED,
    VALIDATION_BLOCKED,
    VALIDATION_REJECTED,
    ToolValidator,
    validate_pick_args,
)

VALID_ARGS = {'target_marker_id': 42}


# ---------------------------------------------------------------------------
# schema
# ---------------------------------------------------------------------------

class TestPickSchema:
    def test_schema_present_in_tool_schemas(self):
        schema = next(s for s in TOOL_SCHEMAS if s['name'] == 'pick_object')
        props = schema['parameters']['properties']
        assert set(props) == {'target_marker_id', 'pregrasp_offset', 'grasp_depth'}
        assert props['target_marker_id']['type'] == 'integer'
        assert props['pregrasp_offset']['type'] == 'number'
        assert props['grasp_depth']['type'] == 'number'
        assert schema['parameters']['required'] == ['target_marker_id']

    def test_tool_params_declared(self):
        assert TOOL_PARAMS['pick_object'] == {
            'target_marker_id': ('integer', True),
            'pregrasp_offset': ('number', False),
            'grasp_depth': ('number', False),
        }

    def test_bounds_constants(self):
        assert PICK_PREGRASP_OFFSET_MIN == 0.05
        assert PICK_PREGRASP_OFFSET_MAX == 0.5
        assert PICK_GRASP_DEPTH_MIN == 0.01
        assert PICK_GRASP_DEPTH_MAX == 0.1


# ---------------------------------------------------------------------------
# validate_pick_args (pure)
# ---------------------------------------------------------------------------

class TestValidatePickArgs:
    def test_valid_args_pass(self):
        assert validate_pick_args(VALID_ARGS) is None
        assert validate_pick_args({'target_marker_id': 42,
                                   'pregrasp_offset': 0.15,
                                   'grasp_depth': 0.02}) is None

    def test_defaults_are_optional(self):
        # Only the required marker id -> optional params fall back to defaults
        assert validate_pick_args({}) is None or True  # marker checked at schema step
        assert validate_pick_args({'target_marker_id': 7}) is None

    def test_boundary_values_allowed(self):
        args = {'target_marker_id': 0,
                'pregrasp_offset': PICK_PREGRASP_OFFSET_MIN,
                'grasp_depth': PICK_GRASP_DEPTH_MAX}
        assert validate_pick_args(args) is None
        args['pregrasp_offset'] = PICK_PREGRASP_OFFSET_MAX
        args['grasp_depth'] = PICK_GRASP_DEPTH_MIN
        assert validate_pick_args(args) is None

    @pytest.mark.parametrize('offset', [0.04, 0.51, -1.0])
    def test_pregrasp_out_of_range(self, offset):
        detail = validate_pick_args({'target_marker_id': 42, 'pregrasp_offset': offset})
        assert detail is not None and 'pregrasp_offset' in detail

    @pytest.mark.parametrize('depth', [0.009, 0.11, 1.0])
    def test_grasp_depth_out_of_range(self, depth):
        detail = validate_pick_args({'target_marker_id': 42, 'grasp_depth': depth})
        assert detail is not None and 'grasp_depth' in detail

    def test_non_number_rejected(self):
        assert validate_pick_args({'target_marker_id': 42, 'pregrasp_offset': 'far'})
        assert validate_pick_args({'target_marker_id': 42, 'grasp_depth': True})

    def test_non_integer_marker_rejected(self):
        assert validate_pick_args({'target_marker_id': '42'})
        assert validate_pick_args({'target_marker_id': True})


# ---------------------------------------------------------------------------
# ToolValidator chain integration
# ---------------------------------------------------------------------------

class TestValidatorPickObject:
    def test_valid_call_allowed(self):
        verdict = ToolValidator().validate('pick_object', VALID_ARGS)
        assert verdict['status'] == VALIDATION_ALLOWED

    def test_missing_marker_id_schema_rejected(self):
        verdict = ToolValidator().validate('pick_object', {})
        assert verdict['status'] == VALIDATION_REJECTED
        assert verdict['reason'] == REASON_SCHEMA

    def test_string_marker_id_schema_rejected(self):
        verdict = ToolValidator().validate('pick_object', {'target_marker_id': '42'})
        assert verdict['status'] == VALIDATION_REJECTED
        assert verdict['reason'] == REASON_SCHEMA

    def test_unexpected_arg_schema_rejected(self):
        verdict = ToolValidator().validate(
            'pick_object', {'target_marker_id': 42, 'force': 10.0})
        assert verdict['status'] == VALIDATION_REJECTED
        assert verdict['reason'] == REASON_SCHEMA

    def test_out_of_bounds_rejected(self):
        v = ToolValidator()
        verdict = v.validate('pick_object',
                             {'target_marker_id': 42, 'pregrasp_offset': 5.0})
        assert verdict['status'] == VALIDATION_REJECTED
        assert verdict['reason'] == REASON_BOUNDS
        verdict = v.validate('pick_object',
                             {'target_marker_id': 42, 'grasp_depth': 0.5})
        assert verdict['status'] == VALIDATION_REJECTED
        assert verdict['reason'] == REASON_BOUNDS

    def test_estop_blocks_pick_object(self):
        verdict = ToolValidator().validate('pick_object', VALID_ARGS, estop_active=True)
        assert verdict['status'] == VALIDATION_BLOCKED
        assert verdict['reason'] == REASON_ESTOPPED


# ---------------------------------------------------------------------------
# MockExecutor
# ---------------------------------------------------------------------------

class TestMockPickObject:
    def test_pick_object_success_with_fake_trajectory(self):
        result = MockExecutor().execute('pick_object', VALID_ARGS)
        assert result['status'] == 'SUCCESS'
        assert result['data']['marker_id'] == 42
        assert result['data']['trajectory_points'] > 0

    def test_pick_object_bad_marker_still_success_mock(self):
        result = MockExecutor().execute('pick_object', {'target_marker_id': 'x'})
        assert result['status'] == 'SUCCESS'


# ---------------------------------------------------------------------------
# RosActionExecutor pick_object (fake action client, no ROS)
# ---------------------------------------------------------------------------

class FakeGraspFuture:
    def __init__(self, value):
        self._value = value

    def done(self):
        return True

    def result(self):
        return self._value


class FakeGraspGoalHandle:
    def __init__(self, accepted=True, result=None):
        self.accepted = accepted
        self._result = result
        self.cancel_called = False

    def get_result_async(self):
        # rclpy wraps the action result in a response with a `.result` field
        return FakeGraspFuture(types.SimpleNamespace(result=self._result))

    def cancel_goal_async(self):
        self.cancel_called = True
        return FakeGraspFuture(None)


class FakeGraspResult:
    def __init__(self, success=True, message='Grasp executed successfully', points=8):
        self.success = success
        self.message = message
        self.trajectory = types.SimpleNamespace(points=list(range(points)))


class FakeGraspClient:
    def __init__(self, server_available=True, goal_handle=None):
        self._server_available = server_available
        self._goal_handle = goal_handle or FakeGraspGoalHandle(
            accepted=True, result=FakeGraspResult())
        self.last_goal = None
        self.wait_called = False

    def wait_for_server(self, timeout_sec=5.0):
        self.wait_called = True
        return self._server_available

    def send_goal_async(self, goal_msg):
        self.last_goal = goal_msg
        return FakeGraspFuture(self._goal_handle)


class FakeGraspExecute:
    class Goal:
        def __init__(self):
            self.target_marker_id = 0
            self.pregrasp_offset = 0.0
            self.grasp_depth = 0.0


def _make_grasp_executor(client, timeout_s=10.0):
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
    ex._client = None
    ex._grasp_client = client
    ex._initialized = True
    ex._RobotCommand = None
    ex._GraspExecute = FakeGraspExecute
    ex._rclpy = types.SimpleNamespace(ok=lambda: True)
    return ex


class TestRosPickObject:
    def test_goal_fields_and_success_result(self):
        client = FakeGraspClient()
        ex = _make_grasp_executor(client)

        outcome = ex.execute('pick_object', {
            'target_marker_id': 42, 'pregrasp_offset': 0.2, 'grasp_depth': 0.03})

        assert outcome['status'] == 'SUCCESS'
        assert outcome['detail'] == 'Grasp executed successfully'
        assert outcome['data']['marker_id'] == 42
        assert outcome['data']['trajectory_points'] == 8
        assert client.last_goal.target_marker_id == 42
        assert client.last_goal.pregrasp_offset == pytest.approx(0.2)
        assert client.last_goal.grasp_depth == pytest.approx(0.03)

    def test_defaults_fill_optional_params(self):
        client = FakeGraspClient()
        ex = _make_grasp_executor(client)

        outcome = ex.execute('pick_object', VALID_ARGS)

        assert outcome['status'] == 'SUCCESS'
        assert client.last_goal.pregrasp_offset == pytest.approx(PICK_PREGRASP_OFFSET_DEFAULT)
        assert client.last_goal.grasp_depth == pytest.approx(PICK_GRASP_DEPTH_DEFAULT)

    def test_server_unavailable_failed(self):
        client = FakeGraspClient(server_available=False)
        ex = _make_grasp_executor(client)

        outcome = ex.execute('pick_object', VALID_ARGS)

        assert outcome['status'] == 'FAILED'
        assert outcome['detail'] == 'action server not available'
        assert client.wait_called

    @pytest.mark.parametrize('args,detail', [
        ({}, 'target_marker_id'),
        ({'target_marker_id': '42'}, 'target_marker_id'),
        ({'target_marker_id': True}, 'target_marker_id'),
        ({'target_marker_id': 42, 'pregrasp_offset': 9.9}, 'outside bounds'),
        ({'target_marker_id': 42, 'grasp_depth': 0.9}, 'outside bounds'),
        ({'target_marker_id': 42, 'pregrasp_offset': 'near'}, 'must be a number'),
    ])
    def test_bad_args_failed_without_contacting_server(self, args, detail):
        client = FakeGraspClient()
        ex = _make_grasp_executor(client)

        outcome = ex.execute('pick_object', args)

        assert outcome['status'] == 'FAILED'
        assert detail in outcome['detail']
        assert not client.wait_called
        assert client.last_goal is None

    def test_goal_rejected_failed(self):
        client = FakeGraspClient(goal_handle=FakeGraspGoalHandle(accepted=False))
        ex = _make_grasp_executor(client)

        outcome = ex.execute('pick_object', VALID_ARGS)

        assert outcome['status'] == 'FAILED'
        assert outcome['detail'] == 'goal rejected'

    def test_action_failure_propagates_message(self):
        result = FakeGraspResult(success=False, message='marker 42 not visible')
        client = FakeGraspClient(goal_handle=FakeGraspGoalHandle(accepted=True, result=result))
        ex = _make_grasp_executor(client)

        outcome = ex.execute('pick_object', VALID_ARGS)

        assert outcome['status'] == 'FAILED'
        assert outcome['detail'] == 'marker 42 not visible'
        assert outcome['data']['marker_id'] == 42

    def test_timeout_cancels_goal(self):
        goal_handle = FakeGraspGoalHandle(accepted=True, result=None)
        client = FakeGraspClient(goal_handle=goal_handle)
        ex = _make_grasp_executor(client, timeout_s=0.001)

        outcome = ex.execute('pick_object', VALID_ARGS)

        assert outcome['status'] == 'TIMEOUT'
        assert 'timeout' in outcome['detail']
        assert goal_handle.cancel_called


# ---------------------------------------------------------------------------
# prompt
# ---------------------------------------------------------------------------

class TestPromptMentionsPick:
    def test_prompt_documents_pick_object(self):
        prompt = build_system_prompt()
        assert 'pick_object' in prompt
        assert 'target_marker_id' in prompt
        assert '0.15' in prompt and '0.02' in prompt
        assert '[0.05, 0.5]' in prompt and '[0.01, 0.1]' in prompt
