"""Validation layer between the Gemini model and actuation (pure logic).

Chain (per plan.md 1D): schema -> allowlist -> bounds -> preconditions ->
loop-breaker. Verdicts: ALLOWED | REJECTED | BLOCKED.

- REJECTED: the call itself is malformed or out of policy (schema, unknown
  tool, out-of-bounds parameter).
- BLOCKED: the environment currently forbids it (estop precondition, or the
  loop-breaker aborts after repeated identical rejections).
- loop_breaker(): True once consecutive same-reason rejections reach
  max_same_rejection (config, default 2) — the agent loop should abort.
"""
from h1_llm_agent.tools import (
    ACTUATION_TOOLS,
    ALLOWED_TOOLS,
    TOOL_MODE_MAP,
    TOOL_PARAMS,
    WALK_DISTANCE_MAX,
    WALK_DISTANCE_MIN,
)

VALIDATION_ALLOWED = 'ALLOWED'
VALIDATION_REJECTED = 'REJECTED'
VALIDATION_BLOCKED = 'BLOCKED'

REASON_SCHEMA = 'SCHEMA'
REASON_UNKNOWN_TOOL = 'UNKNOWN_TOOL'
REASON_BOUNDS = 'BOUNDS'
REASON_ESTOPPED = 'ESTOPPED'
REASON_LOOP_BREAK = 'LOOP_BREAK'

DEFAULT_MAX_SAME_REJECTION = 2


class ToolValidator:
    """Deterministic gate for every tool call. No ROS imports."""

    def __init__(self, max_same_rejection=DEFAULT_MAX_SAME_REJECTION):
        self.max_same_rejection = int(max_same_rejection)
        self._reason = None
        self._count = 0

    # -- public API -----------------------------------------------------

    def validate(self, tool_name, args=None, estop_active=False):
        """Return {status: ALLOWED|REJECTED|BLOCKED, reason, detail}."""
        args = args if args is not None else {}
        verdict = self._check_schema(tool_name, args)
        if verdict is not None:
            return verdict
        verdict = self._check_allowlist(tool_name)
        if verdict is not None:
            return verdict
        verdict = self._check_bounds(tool_name, args)
        if verdict is not None:
            return verdict
        verdict = self._check_preconditions(tool_name, estop_active)
        if verdict is not None:
            return verdict
        self._reset()
        return self._verdict(VALIDATION_ALLOWED, None,
                             'call allowed for {}'.format(tool_name))

    def loop_breaker(self):
        """True when consecutive same-reason rejections >= max_same_rejection."""
        return self._count >= self.max_same_rejection

    def reset(self):
        self._reason = None
        self._count = 0

    # -- chain steps ----------------------------------------------------

    def _check_schema(self, tool_name, args):
        if not isinstance(args, dict):
            return self._reject(REASON_SCHEMA,
                                'args must be a JSON object, got {}'.format(type(args).__name__))
        declared = set(TOOL_PARAMS.get(tool_name, {}))
        given = set(args.keys())
        unexpected = given - declared
        if unexpected:
            return self._reject(REASON_SCHEMA,
                                'unexpected argument(s): {}'.format(sorted(unexpected)))
        for name, (ptype, is_required) in TOOL_PARAMS.get(tool_name, {}).items():
            if name not in given:
                if is_required:
                    return self._reject(REASON_SCHEMA,
                                        'missing required argument: {}'.format(name))
                continue
            if ptype == 'number' and isinstance(args[name], bool):
                return self._reject(REASON_SCHEMA,
                                    'argument {} must be a number'.format(name))
            if ptype == 'number' and not isinstance(args[name], (int, float)):
                return self._reject(REASON_SCHEMA,
                                    'argument {} must be a number, got {}'.format(
                                        name, type(args[name]).__name__))
        return None

    def _check_allowlist(self, tool_name):
        if tool_name not in ALLOWED_TOOLS:
            return self._reject(REASON_UNKNOWN_TOOL,
                                "unknown tool '{}'".format(tool_name))
        if tool_name in ACTUATION_TOOLS and tool_name not in TOOL_MODE_MAP:
            return self._reject(REASON_UNKNOWN_TOOL,
                                'actuation tool {} has no RobotCommand mode'.format(tool_name))
        return None

    def _check_bounds(self, tool_name, args):
        if tool_name == 'walk':
            distance = args.get('distance_m')
            if distance < WALK_DISTANCE_MIN or distance > WALK_DISTANCE_MAX:
                return self._reject(
                    REASON_BOUNDS,
                    'walk distance_m {:.3f} outside bounds [{:.1f}, {:.1f}] m'.format(
                        distance, WALK_DISTANCE_MIN, WALK_DISTANCE_MAX))
        return None

    def _check_preconditions(self, tool_name, estop_active):
        if estop_active and tool_name in ACTUATION_TOOLS:
            return self._block(REASON_ESTOPPED,
                               'estop active: actuation tool {} blocked'.format(tool_name))
        return None

    # -- rejection tracking ----------------------------------------------

    def _reject(self, reason, detail):
        return self._track(reason, VALIDATION_REJECTED, detail)

    def _block(self, reason, detail):
        return self._track(reason, VALIDATION_BLOCKED, detail)

    def _track(self, reason, status, detail):
        if reason == self._reason:
            self._count += 1
        else:
            self._reason = reason
            self._count = 1
        return self._verdict(status, reason, detail)

    def _verdict(self, status, reason, detail):
        return {'status': status, 'reason': reason, 'detail': detail}

    def _reset(self):
        self._reason = None
        self._count = 0
