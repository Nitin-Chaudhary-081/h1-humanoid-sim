"""Rolling-window anomaly scoring on a chosen metric.

Pure logic, no ROS imports.

Primary scorer: rolling z-score
    z = (value - mean(window)) / std(window)     (ddof=0)
with a configurable window (default 50 samples). A value is anomalous
when |z| > z_threshold (default 3.5) or a configured threshold breach
occurs (see thresholds.ThresholdEvaluator). A constant window (zero
variance) that the new value deviates from yields z = +inf (anomalous);
equal value yields z = 0.

PLACEHOLDER: isolation_forest_score() is a documented stub. The real
IsolationForest is trained OFFLINE on a nominal telemetry bag (M4 follow-up,
per plan.md) and shipped as a fitted model artifact; the stub currently
returns the z-based score so the pipeline, message fields and tests are
exercised end-to-end. Replace the body when the trained artifact lands.
"""

import math
from collections import deque


class AnomalyScorer:
    """Rolling-window z-score anomaly detector for ONE metric."""

    def __init__(self, metric_name, window=50, z_threshold=3.5,
                 score_sigma_lo=1.0, score_sigma_hi=3.5):
        if window < 2:
            raise ValueError('window must be >= 2')
        if not (score_sigma_hi > score_sigma_lo >= 0):
            raise ValueError('need 0 <= score_sigma_lo < score_sigma_hi')
        self.metric_name = metric_name
        self.window_size = window
        self.z_threshold = z_threshold
        self._score_lo = score_sigma_lo
        self._score_hi = score_sigma_hi
        self._values = deque(maxlen=window)

    def reset(self):
        self._values.clear()

    @property
    def count(self):
        return len(self._values)

    def _z_score(self, value):
        n = len(self._values)
        if n < 2:
            return 0.0
        mean = sum(self._values) / n
        if n > 1:
            var = sum((v - mean) ** 2 for v in self._values) / n
        else:
            var = 0.0
        if var == 0.0:
            # Constant window: any deviation is infinite-sigma (anomalous).
            return float('inf') if value != mean else 0.0
        return (value - mean) / math.sqrt(var)

    def z_score_of(self, value):
        """|z| of value vs current window WITHOUT updating it."""
        return abs(self._z_score(value))

    @staticmethod
    def _z_to_score(z_abs):
        """Map |z| to a 0..1 score. Linear ramp between sigma_lo and
        sigma_hi: 0 at |z| <= 1.0, 1.0 at |z| >= 3.5 (stub scaling)."""
        if z_abs <= 1.0:
            return 0.0
        if z_abs >= 3.5:
            return 1.0
        return (z_abs - 1.0) / (3.5 - 1.0)

    def isolation_forest_score(self, value):
        """PLACEHOLDER for a real IsolationForest.

        Real implementation: fit on a nominal bag offline, expose
        score_samples -> 0..1 anomaly likelihood, and combine with the
        z-score here. For now return the z-based score (documented stub).
        """
        z_abs = self._z_score(value)
        return self._z_to_score(z_abs), z_abs

    def update(self, value, breached=False):
        """Push value into the window; return (score, anomaly).

        score: 0..1 (z-based; 1.0 forced on threshold breach).
        anomaly: True if breach or |z| > z_threshold.
        """
        z_abs = self._z_score(value)
        self._values.append(value)
        if breached:
            return 1.0, True
        score = self._z_to_score(z_abs)
        return score, z_abs > self.z_threshold
