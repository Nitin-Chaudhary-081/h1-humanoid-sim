# Unit tests for thresholds.py (pure, no ROS).
import pytest

from h1_telemetry.thresholds import BREACH_MAX, BREACH_MIN, Breach, ThresholdEvaluator

THRESHOLDS = {
    'joint_states_hz_min': 30.0,
    'odometry_hz_min': 2.0,
    'cpu_load_max': 0.95,
    'ram_used_mb_max': 1700.0,
}


def test_no_breaches():
    ev = ThresholdEvaluator(THRESHOLDS)
    sample = {'joint_states_hz': 50.0, 'odometry_hz': 30.0,
              'cpu_load': 0.5, 'ram_used_mb': 800.0}
    assert ev.evaluate(sample) == []


def test_min_breach():
    ev = ThresholdEvaluator(THRESHOLDS)
    out = ev.evaluate({'joint_states_hz': 25.0, 'odometry_hz': 2.5})
    assert out == [Breach('joint_states_hz_min', 25.0, 30.0, BREACH_MIN)]


def test_max_breach():
    ev = ThresholdEvaluator(THRESHOLDS)
    out = ev.evaluate({'cpu_load': 0.99, 'ram_used_mb': 1600.0})
    assert out == [Breach('cpu_load_max', 0.99, 0.95, BREACH_MAX)]


def test_multiple_breaches_preserve_order():
    ev = ThresholdEvaluator(THRESHOLDS)
    sample = {'joint_states_hz': 10.0, 'odometry_hz': 1.0,
              'cpu_load': 1.0, 'ram_used_mb': 1800.0}
    out = ev.evaluate(sample)
    assert [b.name for b in out] == [
        'joint_states_hz_min', 'odometry_hz_min', 'cpu_load_max', 'ram_used_mb_max']
    assert out[0].kind == BREACH_MIN
    assert out[2].kind == BREACH_MAX


def test_boundary_values_not_breached():
    ev = ThresholdEvaluator(THRESHOLDS)
    # min: value == limit is OK; max: value == limit is OK.
    assert ev.evaluate({'joint_states_hz': 30.0}) == []
    assert ev.evaluate({'cpu_load': 0.95}) == []


def test_missing_and_unknown_keys_ignored():
    ev = ThresholdEvaluator(THRESHOLDS)
    assert ev.evaluate({}) == []
    assert ev.evaluate({'not_a_threshold': 999.0}) == []
    assert not ev.is_threshold('not_a_threshold')
    assert ev.is_threshold('cpu_load_max')
    assert ev.bare_name('ram_used_mb_max') == 'ram_used_mb'


def test_nan_and_inf_values():
    ev = ThresholdEvaluator(THRESHOLDS)
    assert ev.evaluate({'cpu_load': float('nan')}) == []  # nan > x is False
    assert ev.evaluate({'cpu_load': float('inf')}) != []


def test_from_yaml(tmp_path):
    p = tmp_path / 'thresholds.yaml'
    p.write_text('joint_states_hz_min: 30.0\ncpu_load_max: 0.95\n')
    ev = ThresholdEvaluator.from_yaml(str(p))
    assert ev.evaluate({'joint_states_hz': 1.0})[0].name == 'joint_states_hz_min'
    assert ev.evaluate({'cpu_load': 0.9}) == []


def test_from_yaml_empty_or_non_mapping(tmp_path):
    p = tmp_path / 'empty.yaml'
    p.write_text('')
    assert ThresholdEvaluator.from_yaml(str(p)).limits == {}

    p = tmp_path / 'list.yaml'
    p.write_text('- a\n- b\n')
    with pytest.raises(ValueError):
        ThresholdEvaluator.from_yaml(str(p))


def test_non_suffix_keys_dropped():
    ev = ThresholdEvaluator({'cpu_load_max': 0.9, 'bogus_key': 5.0})
    assert ev.limits == {'cpu_load_max': 0.9}
    assert not ev.is_threshold('bogus_key')
    assert ev.evaluate({'bogus_key': 100.0}) == []


def test_package_thresholds_yaml_roundtrip():
    """The shipped config/thresholds.yaml must load and evaluate a
    telemetry-sample-shaped dict (bare metric keys) without error."""
    import os
    path = os.path.join(os.path.dirname(__file__), '..', 'config',
                        'thresholds.yaml')
    ev = ThresholdEvaluator.from_yaml(path)
    assert len(ev.limits) == 8
    sample = {'cpu_load': 0.3, 'ram_used_mb': 900.0, 'joint_states_hz': 100.0,
              'odometry_hz': 50.0, 'imu_hz': 400.0, 'body_pitch_deg': 2.0,
              'body_roll_deg': 1.0, 'fall_risk_score': 0.05,
              'anomaly_score': 0.0, 'anomaly': False, 'detail': ''}
    assert ev.evaluate(sample) == []
    risky = dict(sample, body_pitch_deg=70.0)
    out = ev.evaluate(risky)
    assert out == [Breach('body_pitch_deg_max', 70.0, 45.0, BREACH_MAX)]