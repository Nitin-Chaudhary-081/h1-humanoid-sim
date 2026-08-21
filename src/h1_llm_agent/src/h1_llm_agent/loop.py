"""Agent tool loop (pure logic, no ROS imports; google-genai imported lazily).

run_tool_loop() drives: model -> validation (ToolValidator) -> execution
(ExecutorInterface), up to max_tool_steps, aborting early when the
loop-breaker trips. google-genai is ONLY imported inside GeminiModel at call
time, so this module (and the whole package) is importable and testable on a
box where google-genai is not installed — tests inject a fake model or a
fake `google.genai` module via sys.modules.
"""
import os
from abc import ABC, abstractmethod

from h1_llm_agent.audit import AuditWriter
from h1_llm_agent.tools import TOOL_SCHEMAS

OUTCOME_SUCCESS = 'SUCCESS'
OUTCOME_FAILED = 'FAILED'
OUTCOME_BLOCKED = 'BLOCKED'
OUTCOME_TIMEOUT = 'TIMEOUT'


class ApiKeyMissingError(Exception):
    """Raised when no GEMINI_API_KEY is available for a model call."""


class GenAIImportError(Exception):
    """Raised when google-genai is not installed."""


class ToolCall:
    def __init__(self, name, args=None):
        self.name = name
        self.args = dict(args) if args else {}

    def to_dict(self):
        return {'tool': self.name, 'args': self.args}

    def __repr__(self):
        return 'ToolCall({!r}, {!r})'.format(self.name, self.args)


class ModelInterface(ABC):
    """Seam for the LLM. Wave 1 tests inject fakes; the node uses
    GeminiModel."""

    @abstractmethod
    def generate_tool_calls(self, user_text, tool_schemas):
        """Return the list of ToolCall the model wants to run.
        Empty list means the model produced a final text answer."""
        raise NotImplementedError

    @property
    def last_text(self):
        """Final text answer from the model (None if not set)."""
        return None


class GeminiModel(ModelInterface):
    """google-genai wrapper for gemini-3.6-flash with function calling.

    Lazy: google-genai is imported on first call only. A missing API key or
    a missing package raises ApiKeyMissingError / GenAIImportError, which
    run_tool_loop maps to a BLOCKED outcome ('no api key'). The exact SDK
    call shape (config dicts vs types objects) is finalized during Wave 2
    integration against the installed google-genai version.
    """

    def __init__(self, model='gemini-3.6-flash', thinking_level='low',
                 step_timeout_s=20.0, api_key=None, system_instruction=None):
        self._model = model
        self._thinking_level = thinking_level
        self._timeout_s = step_timeout_s
        self._system_instruction = system_instruction
        self._api_key = api_key if api_key is not None else os.environ.get('GEMINI_API_KEY', '')
        self._client = None
        self._last_text = None
        self._history = []

    @property
    def last_text(self):
        return self._last_text

    def has_api_key(self):
        return bool(self._api_key)

    def reset(self):
        self._history = []
        self._last_text = None

    def generate_tool_calls(self, user_text, tool_schemas):
        if not self._api_key:
            raise ApiKeyMissingError('no api key')
        client = self._get_client()
        # New google-genai (2.19) expects parts as [{"text": "..."}] not ["..."]
        # and uses camelCase aliases but accepts snake_case via pydantic.
        # Keep dict-style for test compatibility (fake client asserts dict config).
        contents = list(self._history) + [{'role': 'user', 'parts': [{'text': user_text}]}]
        config = {
            'tools': [{'function_declarations': list(tool_schemas)}],
            'thinking_config': {'thinking_level': self._thinking_level},
        }
        if self._system_instruction:
            config['system_instruction'] = self._system_instruction
        # Try typed config for real SDK, fall back to dict for fake clients/tests
        try:
            from google.genai import types as _types
            # Build typed tools if possible to satisfy new SDK validation
            try:
                _typed_decls = []
                for s in tool_schemas:
                    # Convert dict schema to types.Schema if needed
                    params = s.get('parameters')
                    schema = None
                    if params:
                        # params is {"type": "object", "properties": {...}, "required": [...]}
                        props = {}
                        for pn, pd in params.get('properties', {}).items():
                            ptype = pd.get('type', 'string').upper()
                            # Map to types.Type enum via string; Schema accepts string type
                            props[pn] = _types.Schema(type=ptype, description=pd.get('description', ''))
                        schema = _types.Schema(
                            type=_types.Type.OBJECT,
                            properties=props,
                            required=params.get('required'),
                        )
                    _typed_decls.append(_types.FunctionDeclaration(
                        name=s['name'],
                        description=s.get('description', ''),
                        parameters=schema,
                    ))
                _typed_tool = _types.Tool(function_declarations=_typed_decls)
                _typed_config = _types.GenerateContentConfig(
                    tools=[_typed_tool],
                    thinking_config=_types.ThinkingConfig(thinking_level=self._thinking_level.upper()) if self._thinking_level else None,
                    system_instruction=self._system_instruction,
                )
                # Use typed contents as well
                _typed_contents = []
                for c in contents:
                    # c is {"role": "user", "parts": [{"text": ...}]} or history entries
                    parts = []
                    for p in c.get('parts', []):
                        if isinstance(p, dict):
                            if 'text' in p:
                                parts.append(_types.Part(text=p['text']))
                            elif 'function_call' in p or 'functionCall' in p:
                                fc = p.get('function_call') or p.get('functionCall') or {}
                                parts.append(_types.Part(function_call=_types.FunctionCall(name=fc.get('name'), args=fc.get('args', {}))))
                            elif 'function_response' in p or 'functionResponse' in p:
                                fr = p.get('function_response') or p.get('functionResponse') or {}
                                parts.append(_types.Part(function_response=_types.FunctionResponse(name=fr.get('name'), response=fr.get('response', {}))))
                            else:
                                parts.append(_types.Part(text=str(p)))
                        else:
                            parts.append(p)
                    _typed_contents.append(_types.Content(role=c.get('role', 'user'), parts=parts))
                # Prefer typed call for real API validation
                try:
                    response = client.models.generate_content(
                        model=self._model, contents=_typed_contents, config=_typed_config)
                    return self._parse_response(response, contents)
                except Exception:
                    pass
            except Exception:
                pass
        except ImportError:
            pass
        try:
            response = client.models.generate_content(
                model=self._model, contents=contents, config=config,
                timeout=self._timeout_s)
        except TypeError:
            response = client.models.generate_content(
                model=self._model, contents=contents, config=config)
        return self._parse_response(response, contents)

    def submit_tool_results(self, calls, results):
        """Feed executed tool results back to the model for the next turn."""
        parts = []
        for call, result in zip(calls, results):
            parts.append({
                'function_response': {
                    'name': call.name,
                    'response': {'result': result},
                },
            })
        if parts:
            # Store as dict with proper Part shape (text vs functionResponse)
            # History is kept as dicts for backward compat with tests; typed
            # conversion happens on next generate_tool_calls.
            self._history.append({'role': 'user', 'parts': parts})

    def _get_client(self):
        if self._client is None:
            try:
                import importlib
                genai = importlib.import_module('google.genai')  # lazy import
            except ImportError as exc:
                raise GenAIImportError(
                    'google-genai not installed; model calls unavailable') from exc
            self._client = genai.Client(api_key=self._api_key)
        return self._client

    def _parse_response(self, response, contents):
        calls = []
        text = ''
        parts = self._extract_parts(response)
        self._history = contents
        for part in parts:
            function_call = self._attr(part, 'function_call', None)
            if function_call is not None:
                name = self._attr(function_call, 'name', None)
                args = self._attr(function_call, 'args', {}) or {}
                calls.append(ToolCall(name, dict(args) if isinstance(args, dict) else {}))
            else:
                part_text = self._attr(part, 'text', '') or ''
                text += part_text
        self._history = contents + [{
            'role': 'model',
            'parts': [self._part_to_dict(p) for p in parts],
        }]
        self._last_text = text or None
        return calls

    @staticmethod
    def _extract_parts(response):
        try:
            candidates = getattr(response, 'candidates', None) or []
            content = getattr(candidates[0], 'content', None)
            if content is None:
                content = candidates[0]['content'] if isinstance(candidates[0], dict) else None
            parts = getattr(content, 'parts', None)
            if parts is None and isinstance(content, dict):
                parts = content.get('parts', [])
            return parts or []
        except (AttributeError, IndexError, TypeError, KeyError):
            return []

    @staticmethod
    def _attr(obj, name, default):
        try:
            return getattr(obj, name, default)
        except AttributeError:
            if isinstance(obj, dict):
                return obj.get(name, default)
            return default

    @staticmethod
    def _part_to_dict(part):
        if isinstance(part, dict):
            return part
        try:
            return {'function_call': {'name': part.function_call.name,
                                      'args': part.function_call.args or {}},
                    'text': getattr(part, 'text', '')}
        except (AttributeError, TypeError):
            return {'text': getattr(part, 'text', '') or ''}


def canonicalize_intent(text):
    """Normalize raw input text into the canonical intent string."""
    return ' '.join(str(text).strip().split()).lower()


def run_tool_loop(model, user_text, validator, executor, estop_active=None,
                  max_tool_steps=15, tool_schemas=None, audit=None, intent=None):
    """Run the model->validate->execute loop for one user utterance.

    Returns {outcome, detail, final_text, steps, tool_calls, results, events}
    where outcome is SUCCESS | FAILED | BLOCKED | TIMEOUT:
      - SUCCESS: model produced a final answer (no further tool calls).
      - BLOCKED: api key missing / genai missing / loop-breaker tripped.
      - FAILED:  model raised an unexpected error.
      - TIMEOUT: max_tool_steps exhausted.
    When `audit` (AuditWriter) is given, one JSONL record is appended:
    {ts, input_text, intent, tool_calls, results, estop_active, outcome}.
    """
    estop_active = estop_active if estop_active is not None else (lambda: False)
    schemas = tool_schemas if tool_schemas is not None else TOOL_SCHEMAS
    events = []
    tool_calls = []
    results = []

    outcome = {
        'outcome': OUTCOME_SUCCESS,
        'detail': 'model answered',
        'final_text': None,
        'steps': 0,
        'tool_calls': tool_calls,
        'results': results,
        'events': events,
    }

    steps = 0
    while steps < max_tool_steps:
        steps += 1
        try:
            calls = model.generate_tool_calls(user_text, schemas)
        except (ApiKeyMissingError, GenAIImportError) as exc:
            outcome.update({'outcome': OUTCOME_BLOCKED, 'detail': str(exc)})
            events.append({'event': 'blocked', 'step': steps, 'detail': str(exc)})
            break
        except Exception as exc:  # model hiccup — do not crash the node
            outcome.update({'outcome': OUTCOME_FAILED,
                            'detail': 'model error: {}'.format(exc)})
            events.append({'event': 'failed', 'step': steps, 'detail': str(exc)})
            break

        if not calls:
            outcome['final_text'] = model.last_text
            break

        step_calls, step_results = [], []
        aborted = False
        for call in calls:
            verdict = validator.validate(call.name, call.args,
                                         estop_active=estop_active())
            events.append({'event': 'validation', 'step': steps,
                           'tool': call.name, 'args': call.args,
                           'verdict': verdict})
            if verdict['status'] != 'ALLOWED':
                if validator.loop_breaker():
                    events.append({'event': 'loop_breaker', 'step': steps,
                                   'reason': verdict['reason'],
                                   'detail': verdict['detail']})
                    outcome.update({
                        'outcome': OUTCOME_BLOCKED,
                        'detail': 'loop-breaker: {}'.format(verdict['reason']),
                    })
                    aborted = True
                    break
                continue
            result = executor.execute(call.name, call.args)
            step_calls.append(call)
            step_results.append(result)
            tool_calls.append({'tool': call.name, 'args': call.args})
            results.append({'tool': call.name, 'result': result})
            events.append({'event': 'execution', 'step': steps,
                           'tool': call.name, 'result': result})
        if aborted:
            break
        if step_calls and hasattr(model, 'submit_tool_results'):
            model.submit_tool_results(step_calls, step_results)
    else:
        outcome.update({'outcome': OUTCOME_TIMEOUT,
                        'detail': 'max_tool_steps {} exhausted'.format(max_tool_steps)})
        events.append({'event': 'timeout',
                       'detail': 'max_tool_steps {} exhausted'.format(max_tool_steps)})

    outcome['steps'] = steps

    if audit is not None:
        audit.write({
            'input_text': user_text,
            'intent': intent if intent is not None else canonicalize_intent(user_text),
            'tool_calls': tool_calls,
            'results': results,
            'estop_active': bool(estop_active()),
            'outcome': outcome['outcome'],
        })
    return outcome
