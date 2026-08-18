"""Threshold evaluation from config/thresholds.yaml.

Pure logic, no ROS imports.

Convention (documented in config/thresholds.yaml):
  - names ending in ``_min`` are LOWER bounds -> breached when value < limit
  - names ending in ``_max`` are UPPER bounds -> breached when value > limit
Anything else in the yaml is ignored (forward-compatible: extra keys are
never treated as thresholds).
"""

import yaml

BREACH_MIN = 'min'
BREACH_MAX = 'max'


class Breach:
    """One threshold violation: name, sample value, limit, bound kind."""

    __slots__ = ('name', 'value', 'limit', 'kind')

    def __init__(self, name, value, limit, kind):
        self.name = name
        self.value = value
        self.limit = limit
        self.kind = kind

    def __repr__(self):
        return ('Breach(name=%r, value=%r, limit=%r, kind=%r)'
                % (self.name, self.value, self.limit, self.kind))

    def __eq__(self, other):
        return (isinstance(other, Breach)
                and self.name == other.name
                and self.value == other.value
                and self.limit == other.limit
                and self.kind == other.kind)


class ThresholdEvaluator:
    """Evaluate a sample dict {metric_name: value} against a threshold map."""

    def __init__(self, thresholds=None):
        """thresholds: dict of {name: limit}. None -> empty (no breaches).
        Keys without a ``_min``/``_max`` suffix are dropped (ignored)."""
        self._limits = {}
        self._kinds = {}
        for name, limit in (thresholds or {}).items():
            kind = self._kind_for(name)
            if kind is not None:
                self._limits[name] = limit
                self._kinds[name] = kind

    @staticmethod
    def _kind_for(name):
        if name.endswith('_min'):
            return BREACH_MIN
        if name.endswith('_max'):
            return BREACH_MAX
        return None

    @classmethod
    def from_yaml(cls, path):
        """Load thresholds from a yaml mapping {name: limit}."""
        with open(path, 'r') as f:
            data = yaml.safe_load(f)
        if data is None:
            return cls({})
        if not isinstance(data, dict):
            raise ValueError('thresholds yaml must be a mapping, got %r'
                             % type(data).__name__)
        return cls(data)

    @property
    def limits(self):
        return dict(self._limits)

    def is_threshold(self, name):
        """True if name is a recognized (non-ignored) threshold key."""
        return self._kinds.get(name) is not None

    def evaluate(self, sample):
        """sample: dict {name: numeric value}.

        Returns list of Breach for every violated threshold, in yaml order.
        Missing keys are not breaches. Non-recognized keys are ignored.
        """
        breached = []
        for name, limit in self._limits.items():
            kind = self._kinds.get(name)
            if kind is None or name not in sample:
                continue
            value = sample[name]
            if kind == BREACH_MIN and value < limit:
                breached.append(Breach(name, value, limit, kind))
            elif kind == BREACH_MAX and value > limit:
                breached.append(Breach(name, value, limit, kind))
        return breached
