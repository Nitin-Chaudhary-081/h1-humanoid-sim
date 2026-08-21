"""Validation layer between the Gemini model and actuation (pure logic).

Chain (per plan.md 1D): schema -> allowlist -> bounds -> preconditions ->
rate_limit -> loop-breaker. Verdicts: ALLOWED | REJECTED | BLOCKED.

- REJECTED: the call itself is malformed or out of policy (schema, unknown
  tool, out-of-bounds parameter).
- BLOCKED: the environment currently forbids it (estop precondition, rate
  limit exceeded, or the loop-breaker aborts after repeated identical rejections).
- loop_breaker(): True once consecutive same-reason rejections reach
  max_same_rejection (config, default 2) — the agent loop should abort.
"""
import time
from h1_llm_agent.tools import (
    ACTUATION_TOOLS,
    ALLOWED_TOOLS,
    PICK_GRASP_DEPTH_MAX,
    PICK_GRASP_DEPTH_MIN,
    PICK_PREGRASP_OFFSET_MAX,
    PICK_PREGRASP_OFFSET_MIN,
    TOOL_MODE_MAP,
    TOOL_PARAMS,
    WALK_DISTANCE_MAX,
    WALK_DISTANCE_MIN,
)
from h1_llm_agent.audit import AuditWriter, DEFAULT_AUDIT_PATH

VALIDATION_ALLOWED = 'ALLOWED'
VALIDATION_REJECTED = 'REJECTED'
VALIDATION_BLOCKED = 'BLOCKED'

REASON_SCHEMA = 'SCHEMA'
REASON_UNKNOWN_TOOL = 'UNKNOWN_TOOL'
REASON_BOUNDS = 'BOUNDS'
REASON_ESTOPPED = 'ESTOPPED'
REASON_RATE_LIMIT = 'RATE_LIMIT'
REASON_LOOP_BREAK = 'LOOP_BREAK'

DEFAULT_MAX_SAME_REJECTION = 2
DEFAULT_RATE_LIMIT_PER_MIN = 10

# Actuation tools that bypass the RobotCommand TOOL_MODE_MAP (they have
# their own action type, e.g. pick_object -> GraspExecute on /h1/grasp/execute).
NON_MODE_ACTUATION_TOOLS = frozenset(['pick_object'])


class TokenBucket:
    """Token bucket rate limiter per session (correlation_id)."""

    def __init__(self, rate_per_min=DEFAULT_RATE_LIMIT_PER_MIN):
        self.rate_per_min = int(rate_per_min)
        self.capacity = self.rate_per_min
        self.tokens = float(self.capacity)
        self.last_refill = time.time()

    def _refill(self):
        now = time.time()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * (self.rate_per_min / 60.0))
        self.last_refill = now

    def consume(self, tokens=1):
        self._refill()
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_pick_args(args):
    """Pure bounds/type check for pick_object args (no ROS).

    Returns None when valid, else a human-readable detail string.
    target_marker_id is required by TOOL_PARAMS (schema step); here we
    enforce integer-ness and the PICK_* bounds on the optional floats.
    """
    marker_id = args.get('target_marker_id')
    if marker_id is not None:
        if isinstance(marker_id, bool) or not isinstance(marker_id, int):
            if not (isinstance(marker_id, float) and float(marker_id).is_integer()):
                return 'target_marker_id must be an integer, got {}'.format(
                    type(marker_id).__name__)
    for name, lo, hi in (('pregrasp_offset', PICK_PREGRASP_OFFSET_MIN, PICK_PREGRASP_OFFSET_MAX),
                         ('grasp_depth', PICK_GRASP_DEPTH_MIN, PICK_GRASP_DEPTH_MAX)):
        value = args.get(name)
        if value is None:
            continue
        if not _is_number(value):
            return '{} must be a number, got {}'.format(name, type(value).__name__)
        if value < lo or value > hi:
            return '{} {:.3f} outside bounds [{:.2f}, {:.2f}] m'.format(name, value, lo, hi)
    return None


class ToolValidator:
    """Deterministic gate for every tool call. No ROS imports."""

    def __init__(self, max_same_rejection=DEFAULT_MAX_SAME_REJECTION,
                 rate_limit_per_min=DEFAULT_RATE_LIMIT_PER_MIN,
                 walk_distance_min=WALK_DISTANCE_MIN,
                 walk_distance_max=WALK_DISTANCE_MAX,
                 allowed_tools=None,
                 audit_path=DEFAULT_AUDIT_PATH,
                 audit_clock=None):
        self.max_same_rejection = int(max_same_rejection)
        self.rate_limit_per_min = int(rate_limit_per_min)
        self.walk_distance_min = float(walk_distance_min)
        self.walk_distance_max = float(walk_distance_max)
        self.allowed_tools = set(allowed_tools) if allowed_tools is not None else set(ALLOWED_TOOLS)
        self._reason = None
        self._count = 0
        self._buckets = {}
        self._audit = AuditWriter(audit_path, clock=audit_clock)

    # -- public API -----------------------------------------------------

    def validate(self, tool_name, args=None, estop_active=False, correlation_id=None):
        """Return {status: ALLOWED|REJECTED|BLOCKED, reason, detail}."""
        args = args if args is not None else {}
        correlation_id = correlation_id or 'default'

        verdict = self._check_schema(tool_name, args)
        if verdict is not None:
            self._audit_validation(correlation_id, tool_name, args, verdict)
            return verdict

        verdict = self._check_allowlist(tool_name)
        if verdict is not None:
            self._audit_validation(correlation_id, tool_name, args, verdict)
            return verdict

        verdict = self._check_bounds(tool_name, args)
        if verdict is not None:
            self._audit_validation(correlation_id, tool_name, args, verdict)
            return verdict

        verdict = self._check_preconditions(tool_name, estop_active)
        if verdict is not None:
            self._audit_validation(correlation_id, tool_name, args, verdict)
            return verdict

        verdict = self._check_rate_limit(correlation_id)
        if verdict is not None:
            self._audit_validation(correlation_id, tool_name, args, verdict)
            return verdict

        self._reset()
        verdict = self._verdict(VALIDATION_ALLOWED, None,
                                'call allowed for {}'.format(tool_name))
        self._audit_validation(correlation_id, tool_name, args, verdict)
        return verdict

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
            if ptype == 'integer':
                value = args[name]
                if isinstance(value, bool) or not isinstance(value, int):
                    if not (isinstance(value, float) and float(value).is_integer()):
                        return self._reject(REASON_SCHEMA,
                                            'argument {} must be an integer, got {}'.format(
                                                name, type(value).__name__))
        return None

    def _check_allowlist(self, tool_name):
        if tool_name not in self.allowed_tools:
            return self._reject(REASON_UNKNOWN_TOOL,
                                "tool '{}' not in allowed list".format(tool_name))
        if (tool_name in ACTUATION_TOOLS
                and tool_name not in TOOL_MODE_MAP
                and tool_name not in NON_MODE_ACTUATION_TOOLS):
            return self._reject(REASON_UNKNOWN_TOOL,
                                'actuation tool {} has no RobotCommand mode'.format(tool_name))
        return None

    def _check_bounds(self, tool_name, args):
        if tool_name == 'walk':
            distance = args.get('distance_m')
            if distance < self.walk_distance_min or distance > self.walk_distance_max:
                return self._reject(
                    REASON_BOUNDS,
                    'walk distance_m {:.3f} outside bounds [{:.3f}, {:.3f}] m'.format(
                        distance, self.walk_distance_min, self.walk_distance_max))
        if tool_name == 'pick_object':
            detail = validate_pick_args(args)
            if detail is not None:
                return self._reject(REASON_BOUNDS, detail)
        return None

    def _check_preconditions(self, tool_name, estop_active):
        if estop_active and tool_name in ACTUATION_TOOLS:
            return self._block(REASON_ESTOPPED,
                               'estop active: actuation tool {} blocked'.format(tool_name))
        return None

    def _check_rate_limit(self, correlation_id):
        bucket = self._buckets.get(correlation_id)
        if bucket is None:
            bucket = TokenBucket(self.rate_limit_per_min)
            self._buckets[correlation_id] = bucket
        if not bucket.consume(1):
            return self._block(REASON_RATE_LIMIT,
                               'rate limit exceeded: max {} commands/min'.format(self.rate_limit_per_min))
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

    def _audit_validation(self, correlation_id, tool_name, args, verdict):
        record = {
            'timestamp': self._audit._clock(),
            'correlation_id': correlation_id,
            'tool': tool_name,
            'args': args,
            'decision': verdict['status'],
            'reason': verdict['reason'],
        }
        self._audit.write(record)
