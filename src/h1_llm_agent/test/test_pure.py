"""Pure-logic unit tests for h1_llm_agent (no ROS imports; no google-genai).

Run: cd /tmp/opencode/wt-h1_llm_agent && PYTHONPATH=src python3 -m pytest test/ -q
"""
import sys
import types

import pytest

from h1_llm_agent.audit import AuditWriter
from h1_llm_agent.executor import (
    MODES,
    ExecutorInterface,
    MockExecutor,
    RosActionExecutor,
    build_executor,
)
from h1_llm_agent.loop import (
    ApiKeyMissingError,
    GeminiModel,
    ModelInterface,
    ToolCall,
    canonicalize_intent,
    run_tool_loop,
)
from h1_llm_agent.prompt import SYSTEM_PROMPT, build_system_prompt
from h1_llm_agent.tools import (
    ACTUATION_TOOLS,
    ALLOWED_TOOLS,
    READONLY_TOOLS,
    TOOL_MODE_MAP,
    TOOL_SCHEMAS,
    WALK_DISTANCE_MAX,
    WALK_DISTANCE_MIN,
)
from h1_llm_agent.validation import (
    REASON_BOUNDS,
    REASON_ESTOPPED,
    REASON_LOOP_BREAK,
    REASON_SCHEMA,
    REASON_UNKNOWN_TOOL,
    VALIDATION_ALLOWED,
    VALIDATION_BLOCKED,
    VALIDATION_REJECTED,
    ToolValidator,
)


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------

class TestValidation:
    def test_valid_calls_allowed(self):
        v = ToolValidator()
        for tool in ALLOWED_TOOLS:
            args = {'distance_m': 1.0} if tool == 'walk' else {}
            verdict = v.validate(tool, args, estop_active=False)
            assert verdict['status'] == VALIDATION_ALLOWED, tool
        assert v.validate('walk', {'distance_m': 2.5})['status'] == VALIDATION_ALLOWED

    def test_boundary_distances_allowed(self):
        v = ToolValidator()
        assert v.validate('walk', {'distance_m': WALK_DISTANCE_MIN})['status'] == VALIDATION_ALLOWED
        assert v.validate('walk', {'distance_m': WALK_DISTANCE_MAX})['status'] == VALIDATION_ALLOWED

    def test_allowlist_rejects_unknown_tool(self):
        verdict = ToolValidator().validate('open_gate', {}, estop_active=False)
        assert verdict['status'] == VALIDATION_REJECTED
        assert verdict['reason'] == REASON_UNKNOWN_TOOL

    @pytest.mark.parametrize('distance', [-1.0, 5.01, 100.0, 1e6])
    def test_bounds_reject_walk(self, distance):
        verdict = ToolValidator().validate('walk', {'distance_m': distance})
        assert verdict['status'] == VALIDATION_REJECTED
        assert verdict['reason'] == REASON_BOUNDS

    @pytest.mark.parametrize('args', [5, '2.0', None, {'distance_m': 'far'}])
    def test_schema_reject_bad_args(self, args):
        v = ToolValidator()
        assert v.validate('walk', args)['status'] == VALIDATION_REJECTED
        assert v.validate('walk', args)['reason'] == REASON_SCHEMA

    def test_schema_reject_missing_required_and_unexpected(self):
        v = ToolValidator()
        assert v.validate('walk', {})['reason'] == REASON_SCHEMA
        assert v.validate('stand', {'distance_m': 1.0})['reason'] == REASON_SCHEMA

    def test_estop_blocks_all_actuation_tools(self):
        v = ToolValidator()
        for tool in sorted(ACTUATION_TOOLS):
            args = {'distance_m': 1.0} if tool == 'walk' else {}
            verdict = v.validate(tool, args, estop_active=True)
            assert verdict['status'] == VALIDATION_BLOCKED, tool
            assert verdict['reason'] == REASON_ESTOPPED, tool

    def test_estop_keeps_readonly_tools_allowed(self):
        v = ToolValidator()
        for tool in sorted(READONLY_TOOLS):
            assert v.validate(tool, {}, estop_active=True)['status'] == VALIDATION_ALLOWED

    def test_estop_inactive_allows_actuation(self):
        v = ToolValidator()
        assert v.validate('stand', {}, estop_active=False)['status'] == VALIDATION_ALLOWED

    def test_loop_breaker_after_max_same_rejections(self):
        v = ToolValidator(max_same_rejection=2)
        v.validate('walk', {'distance_m': 10.0})
        assert v.loop_breaker() is False
        v.validate('walk', {'distance_m': 10.0})
        assert v.loop_breaker() is True
        v.validate('stand', {}, estop_active=True)  # new reason -> new sequence
        assert v.loop_breaker() is False

    def test_loop_breaker_resets_on_allowed(self):
        v = ToolValidator(max_same_rejection=2)
        v.validate('walk', {'distance_m': 10.0})
        v.validate('stand', {}, estop_active=False)
        assert v.loop_breaker() is False

    def test_loop_breaker_resets_on_different_reason(self):
        v = ToolValidator(max_same_rejection=2)
        v.validate('walk', {'distance_m': 10.0})
        v.validate('no_such_tool', {})
        assert v.loop_breaker() is False

    def test_estop_rejections_trip_loop_breaker(self):
        v = ToolValidator(max_same_rejection=2)
        for _ in range(2):
            verdict = v.validate('walk', {'distance_m': 1.0}, estop_active=True)
            assert verdict['status'] == VALIDATION_BLOCKED
            assert verdict['reason'] == REASON_ESTOPPED
        assert v.loop_breaker() is True


# ---------------------------------------------------------------------------
# executor
# ---------------------------------------------------------------------------

class TestExecutor:
    def test_mock_executor_statuses(self):
        ex = MockExecutor()
        for tool in sorted(READONLY_TOOLS):
            result = ex.execute(tool)
            assert result['status'] == 'SUCCESS'
            assert 'data' in result and 'detail' in result
        assert ex.execute('stand')['status'] == 'SUCCESS'
        assert ex.execute('stop')['status'] == 'SUCCESS'
        assert ex.execute('stop_robot')['status'] == 'SUCCESS'

    def test_mock_walk_returns_mode_and_distance(self):
        result = MockExecutor().execute('walk', {'distance_m': 2.5})
        assert result['status'] == 'SUCCESS'
        assert result['data']['mode'] == 'WALK'
        assert result['data']['distance'] == 2.5

    def test_mock_unknown_tool_failed(self):
        result = MockExecutor().execute('dance', {})
        assert result['status'] == 'FAILED'

    def test_interface_compliance(self):
        ex = MockExecutor()
        assert isinstance(ex, ExecutorInterface)
        assert set(ex.available_tools()) == set(ALLOWED_TOOLS)

    def test_build_executor_factory(self):
        assert isinstance(build_executor('mock'), MockExecutor)
        with pytest.raises(ValueError):
            build_executor('ros')

    def test_ros_executor_skeleton_not_implemented(self):
        ex = RosActionExecutor()
        assert isinstance(ex, ExecutorInterface)
        with pytest.raises(NotImplementedError) as excinfo:
            ex.execute('walk', {'distance_m': 1.0})
        assert '/h1/command' in str(excinfo.value)

    def test_modes_match_frozen_robot_command_constants(self):
        # h1_interfaces/action/RobotCommand.action (FROZEN): STAND=0 WALK=1 STOP=2
        assert MODES == {'STAND': 0, 'WALK': 1, 'STOP': 2}
        assert set(TOOL_MODE_MAP.keys()) == set(ACTUATION_TOOLS)
        for mode in TOOL_MODE_MAP.values():
            assert mode in MODES

    def test_zero_actuation_when_estop(self):
        """Adversarial: with estop active, NO actuation tool may ever be
        executed by the mock executor, regardless of what the model proposes."""
        v = ToolValidator(max_same_rejection=2)
        ex = MockExecutor()
        executed = []
        estop = {'active': True}
        calls = [ToolCall('stand'), ToolCall('walk', {'distance_m': 1.0}),
                 ToolCall('stop_robot'), ToolCall('walk', {'distance_m': 100.0})]
        for call in calls:
            verdict = v.validate(call.name, call.args, estop_active=estop['active'])
            if verdict['status'] == VALIDATION_ALLOWED:
                executed.append(ex.execute(call.name, call.args))
        assert executed == []


# ---------------------------------------------------------------------------
# audit
# ---------------------------------------------------------------------------

class TestAudit:
    def test_writes_jsonl_and_creates_dirs(self, tmp_path):
        path = tmp_path / 'nested' / 'dirs' / 'audit.jsonl'
        writer = AuditWriter(path)
        writer.write({'input_text': 'stand up', 'intent': 'stand up',
                      'tool_calls': [], 'results': [], 'estop_active': False,
                      'outcome': 'SUCCESS'})
        writer.write({'input_text': 'walk 10m', 'intent': 'walk 10m',
                      'tool_calls': [], 'results': [], 'estop_active': True,
                      'outcome': 'BLOCKED'})
        assert path.exists()
        records = writer.read_records()
        assert len(records) == 2
        assert records[0]['outcome'] == 'SUCCESS'
        assert records[1]['estop_active'] is True
        assert 'ts' in records[0]

    def test_read_records_missing_file(self, tmp_path):
        writer = AuditWriter(tmp_path / 'missing.jsonl')
        assert writer.read_records() == []


# ---------------------------------------------------------------------------
# prompt / tools
# ---------------------------------------------------------------------------

class TestTools:
    def test_schemas_exactly_allowlisted_tools(self):
        assert {s['name'] for s in TOOL_SCHEMAS} == set(ALLOWED_TOOLS)
        assert len(TOOL_SCHEMAS) == len(ALLOWED_TOOLS) == 7

    def test_schema_format_gemini_declarations(self):
        for schema in TOOL_SCHEMAS:
            assert set(schema) >= {'name', 'description', 'parameters'}
            assert schema['parameters']['type'] == 'object'
            assert 'properties' in schema['parameters']
            assert schema['name'] in TOOL_MODE_MAP or schema['name'] in READONLY_TOOLS

    def test_walk_schema_bounds_required(self):
        schema = next(s for s in TOOL_SCHEMAS if s['name'] == 'walk')
        assert 'distance_m' in schema['parameters']['properties']
        assert schema['parameters']['required'] == ['distance_m']

    def test_descriptions_short_semantic(self):
        for schema in TOOL_SCHEMAS:
            assert schema['description']
            assert len(schema['description'].split()) <= 3

    def test_prompt_has_safety_guidance(self):
        prompt = build_system_prompt()
        assert prompt == SYSTEM_PROMPT
        assert 'safe' in prompt.lower()
        assert 'estop' in prompt.lower() or 'emergency stop' in prompt.lower()
        assert '5.0' in prompt


# ---------------------------------------------------------------------------
# loop
# ---------------------------------------------------------------------------

class FakeModel(ModelInterface):
    """Scripted model: list of steps; each step is a list[ToolCall] or str."""

    def __init__(self, script, last_text=None):
        self._script = list(script)
        self._last_text = last_text or 'ok'
        self.calls_seen = []

    def generate_tool_calls(self, user_text, tool_schemas):
        self.calls_seen.append((user_text, tool_schemas))
        step = self._script.pop(0) if self._script else []
        if isinstance(step, str):
            self._last_text = step
            return []
        return step

    @property
    def last_text(self):
        return self._last_text


class RecordingExecutor(MockExecutor):
    """MockExecutor that records every execution (proxy for the real
    actuation path: if a call reaches execute(), it 'happens')."""

    def __init__(self):
        super().__init__()
        self.executed = []

    def execute(self, tool_name, args=None):
        self.executed.append((tool_name, dict(args or {})))
        return super().execute(tool_name, args)


class TestLoop:
    def test_successful_turn_executes_validated_tools(self):
        executor = RecordingExecutor()
        outcome = run_tool_loop(
            model=FakeModel([[ToolCall('walk', {'distance_m': 1.0})], 'done walking']),
            user_text='walk forward one meter',
            validator=ToolValidator(),
            executor=executor,
            estop_active=lambda: False,
            max_tool_steps=5,
        )
        assert outcome['outcome'] == 'SUCCESS'
        assert outcome['steps'] == 2
        assert outcome['final_text'] == 'done walking'
        assert executor.executed == [('walk', {'distance_m': 1.0})]

    def test_estop_active_zero_executions_loop_breaker(self):
        """Adversarial (plan 1D): estop on + model keeps proposing actuation
        -> 0 actuation commands ever executed, loop aborts BLOCKED."""
        executor = RecordingExecutor()
        proposal = [ToolCall('walk', {'distance_m': 1.0})]
        outcome = run_tool_loop(
            model=FakeModel([proposal, proposal, proposal]),
            user_text='walk forward',
            validator=ToolValidator(max_same_rejection=2),
            executor=executor,
            estop_active=lambda: True,
            max_tool_steps=5,
        )
        assert executor.executed == []
        assert outcome['outcome'] == 'BLOCKED'
        assert any(e['event'] == 'loop_breaker' for e in outcome['events'])
        assert any(e['event'] == 'validation'
                   and e['verdict']['reason'] == REASON_ESTOPPED
                   for e in outcome['events'])

    def test_out_of_bounds_zero_executions(self):
        executor = RecordingExecutor()
        outcome = run_tool_loop(
            model=FakeModel([[ToolCall('walk', {'distance_m': 100.0})],
                             [ToolCall('walk', {'distance_m': 100.0})]]),
            user_text='walk 100 meters',
            validator=ToolValidator(max_same_rejection=2),
            executor=executor,
            estop_active=lambda: False,
            max_tool_steps=5,
        )
        assert executor.executed == []
        assert outcome['outcome'] == 'BLOCKED'
        assert outcome['detail'] == 'loop-breaker: {}'.format(REASON_BOUNDS)

    def test_rejected_then_sane_call_allowed(self):
        executor = RecordingExecutor()
        outcome = run_tool_loop(
            model=FakeModel([[ToolCall('walk', {'distance_m': 100.0}),
                              ToolCall('walk', {'distance_m': 1.0})], 'done']),
            user_text='go forward',
            validator=ToolValidator(),
            executor=executor,
            estop_active=lambda: False,
            max_tool_steps=5,
        )
        assert outcome['outcome'] == 'SUCCESS'
        assert executor.executed == [('walk', {'distance_m': 1.0})]

    def test_timeout_when_model_never_answers(self):
        executor = RecordingExecutor()
        outcome = run_tool_loop(
            model=FakeModel([[ToolCall('get_pose')]] * 10),
            user_text='keep going',
            validator=ToolValidator(),
            executor=executor,
            estop_active=lambda: False,
            max_tool_steps=3,
        )
        assert outcome['outcome'] == 'TIMEOUT'
        assert outcome['steps'] == 3
        assert len(executor.executed) == 3

    def test_missing_api_key_blocked(self):
        class NoKeyModel(ModelInterface):
            def generate_tool_calls(self, user_text, tool_schemas):
                raise ApiKeyMissingError('no api key')

        outcome = run_tool_loop(
            model=NoKeyModel(),
            user_text='stand up',
            validator=ToolValidator(),
            executor=RecordingExecutor(),
            estop_active=lambda: False,
            max_tool_steps=5,
        )
        assert outcome['outcome'] == 'BLOCKED'
        assert outcome['detail'] == 'no api key'

    def test_model_error_failed(self):
        class BrokenModel(ModelInterface):
            def generate_tool_calls(self, user_text, tool_schemas):
                raise RuntimeError('boom')

        outcome = run_tool_loop(
            model=BrokenModel(),
            user_text='hi',
            validator=ToolValidator(),
            executor=RecordingExecutor(),
            estop_active=lambda: False,
            max_tool_steps=5,
        )
        assert outcome['outcome'] == 'FAILED'
        assert 'boom' in outcome['detail']

    def test_audit_record_written_by_loop(self, tmp_path):
        writer = AuditWriter(tmp_path / 'llm_audit.jsonl')
        outcome = run_tool_loop(
            model=FakeModel([[ToolCall('stand')], 'standing']),
            user_text='Stand up!',
            validator=ToolValidator(),
            executor=RecordingExecutor(),
            estop_active=lambda: False,
            max_tool_steps=5,
            audit=writer,
            intent='stand up',
        )
        assert outcome['outcome'] == 'SUCCESS'
        records = writer.read_records()
        assert len(records) == 1
        record = records[0]
        assert record['input_text'] == 'Stand up!'
        assert record['intent'] == 'stand up'
        assert record['estop_active'] is False
        assert record['outcome'] == 'SUCCESS'
        assert record['tool_calls'] == [{'tool': 'stand', 'args': {}}]

    def test_canonicalize_intent(self):
        assert canonicalize_intent('  Walk   Forward ') == 'walk forward'
        assert canonicalize_intent('') == ''


# ---------------------------------------------------------------------------
# GeminiModel (lazy google-genai, injected via sys.modules)
# ---------------------------------------------------------------------------

class TestGeminiModel:
    def test_raises_api_key_missing(self, monkeypatch):
        monkeypatch.delenv('GEMINI_API_KEY', raising=False)
        model = GeminiModel(api_key='')
        with pytest.raises(ApiKeyMissingError):
            model.generate_tool_calls('stand up', TOOL_SCHEMAS)

    def test_parses_function_calls_from_fake_genai(self, monkeypatch):
        class FakePart:
            def __init__(self, name=None, args=None, text=None):
                self.function_call = None
                self.text = text
                if name:
                    self.function_call = types.SimpleNamespace(name=name, args=args)

        class FakeContent:
            parts = [FakePart(name='walk', args={'distance_m': 2.0}),
                     FakePart(text='will do')]

        class FakeCandidate:
            content = FakeContent()

        class FakeResponse:
            candidates = [FakeCandidate()]

        class FakeModels:
            def generate_content(self, model, contents, config, timeout=None):
                assert config['tools'][0]['function_declarations'] == list(TOOL_SCHEMAS)
                assert 'system_instruction' in config
                return FakeResponse()

        class FakeClient:
            models = FakeModels()

        fake_genai = types.SimpleNamespace(Client=lambda api_key: FakeClient())
        monkeypatch.setitem(sys.modules, 'google', types.SimpleNamespace(__path__=[]))
        monkeypatch.setitem(sys.modules, 'google.genai', fake_genai)

        model = GeminiModel(api_key='test-key', system_instruction='be safe')
        calls = model.generate_tool_calls('walk two meters', TOOL_SCHEMAS)
        assert [c.name for c in calls] == ['walk']
        assert calls[0].args == {'distance_m': 2.0}
        assert model.last_text == 'will do'

    def test_importable_without_google_genai_installed(self):
        # The package must import cleanly on a box without google-genai
        # (this test only fails if any top-level import touches genai).
        assert hasattr(GeminiModel, 'generate_tool_calls')
        assert GeminiModel(api_key='x').has_api_key()
