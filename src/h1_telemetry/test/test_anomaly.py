# Unit tests for anomaly.py (pure, no ROS).
import math

import pytest

from h1_telemetry.anomaly import AnomalyScorer


def test_constant_series_no_anomaly():
    sc = AnomalyScorer('cpu_load', window=50)
    scores = [sc.update(0.5)[0] for _ in range(30)]
    assert all(s == 0.0 for s in scores)
    assert sc.update(0.5) == (0.0, False)


def test_spike_triggers_z_anomaly():
    sc = AnomalyScorer('cpu_load', window=50)
    for _ in range(40):
        sc.update(0.5)
    score, anomaly = sc.update(5.0)  # 9 sigma spike vs constant window
    assert anomaly is True
    assert score == 1.0


def test_gradual_trend_not_anomalous():
    sc = AnomalyScorer('body_pitch_deg', window=50)
    v = 0.0
    for _ in range(50):
        sc.update(v)
        v += 0.1
    score, anomaly = sc.update(v)  # tiny step, well within window variance
    assert anomaly is False
    assert score < 0.5


def test_threshold_breach_forces_anomaly_and_score_1():
    sc = AnomalyScorer('cpu_load', window=50)
    for _ in range(30):
        sc.update(0.5)
    score, anomaly = sc.update(0.51, breached=True)
    assert anomaly is True
    assert score == 1.0


def test_z_score_of_does_not_update_window():
    sc = AnomalyScorer('cpu_load', window=50)
    for _ in range(20):
        sc.update(0.5)
    before = sc.count
    z = sc.z_score_of(10.0)
    assert math.isinf(z)  # constant window, deviating probe -> inf sigma
    assert sc.count == before
    assert sc.z_score_of(0.5) == 0.0


def test_ramp_up_needs_warmup():
    sc = AnomalyScorer('cpu_load', window=50, z_threshold=3.5)
    sc.update(0.5)  # single sample: not enough for z-score
    assert sc.update(0.9) == (0.0, False)


def test_isolation_forest_stub_shape():
    sc = AnomalyScorer('cpu_load', window=20)
    for _ in range(10):
        sc.update(0.5)
    score, z = sc.isolation_forest_score(0.6)
    assert 0.0 <= score <= 1.0
    assert z >= 0.0
    assert isinstance(score, float)


def test_reset():
    sc = AnomalyScorer('cpu_load', window=20)
    for _ in range(10):
        sc.update(0.5)
    sc.reset()
    assert sc.count == 0
    assert sc.update(0.5) == (0.0, False)


def test_invalid_window():
    with pytest.raises(ValueError):
        AnomalyScorer('x', window=1)
    with pytest.raises(ValueError):
        AnomalyScorer('x', window=50, score_sigma_hi=0.5)
