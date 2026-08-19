import json

from h1_aws_sync.alerts import (
    ALERT_FIELDS,
    alert_from_telemetry_line,
    alert_level,
    alerts_from_samples,
    load_alerts_file,
    normalize_stamp,
)
from conftest import REAL_SAMPLE_CRITICAL, REAL_SAMPLE_WARN, write_lines

SAMPLE_OK = {'stamp': 100.0, 'anomaly': False, 'detail': ''}
SAMPLE_WARN = {'stamp': 101.0, 'anomaly': True, 'anomaly_score': 0.55,
               'detail': 'cpu_load_max=0.99 (limit > 0.95)'}
SAMPLE_CRIT = {'stamp': 102.0, 'anomaly': True, 'anomaly_score': 1.0,
               'detail': 'body_pitch_deg_max=44.1 (limit > 45.0)'}


def test_no_alert_for_normal_sample():
    assert alert_from_telemetry_line(SAMPLE_OK) is None


def test_alert_fields_match_h1_interfaces_alert():
    a = alert_from_telemetry_line(SAMPLE_CRIT)
    assert set(a.keys()) == set(ALERT_FIELDS)
    assert a['source'] == 'h1_telemetry'
    assert a['message'].startswith('anomaly: ')
    assert a['stamp'] == 102.0


def test_level_mapping():
    assert alert_level('cpu_load_max=1.0') == 'WARN'
    assert alert_level('ram_used_mb_max=1800') == 'WARN'
    for suffix in ('body_pitch_deg_max', 'body_roll_deg_max', 'fall_risk_score_max'):
        assert alert_level('breach %s=1.0' % suffix) == 'CRITICAL'


def test_real_h1_telemetry_format_warn():
    a = alert_from_telemetry_line(REAL_SAMPLE_WARN)
    assert a is not None
    assert a['level'] == 'CRITICAL'  # detail contains fall_risk_score_max too
    assert a['score'] == 1.0
    assert a['stamp'] == 979.246


def test_real_h1_telemetry_format_critical():
    a = alert_from_telemetry_line(REAL_SAMPLE_CRITICAL)
    assert a['level'] == 'CRITICAL'
    assert a['message'] == 'anomaly: fall_risk_score_max=1.00 (limit > 0.80)'


def test_alerts_from_samples_skips_non_anomaly():
    alerts = alerts_from_samples([SAMPLE_OK, SAMPLE_WARN, SAMPLE_CRIT])
    assert len(alerts) == 2
    assert alerts[0]['level'] == 'WARN'
    assert alerts[1]['level'] == 'CRITICAL'


def test_normalize_stamp_handles_ros_time_dict():
    assert normalize_stamp({'sec': 100, 'nanosec': 500_000_000}) == 100.5
    assert normalize_stamp({'sec': 5, 'nanosec': 0}) == 5.0
    assert normalize_stamp(123.456) == 123.456
    assert normalize_stamp(7) == 7.0


def test_load_alerts_file_explicit(tmp_path):
    path = str(tmp_path / 'alerts.jsonl')
    write_lines(path, [
        {'stamp': 1.0, 'level': 'CRITICAL', 'source': 'estop',
         'message': 'estop pressed', 'score': 1.0},
        {'stamp': 2.0, 'level': 'warn', 'source': 'agent',
         'message': 'retry', 'score': 0.3},
        'garbage line',
    ])
    alerts = load_alerts_file(path)
    assert len(alerts) == 2
    assert alerts[0]['level'] == 'CRITICAL'
    assert alerts[1]['level'] == 'WARN'
    assert alerts[1]['stamp'] == 2.0


def test_load_alerts_file_missing_returns_empty(tmp_path):
    assert load_alerts_file(str(tmp_path / 'missing.jsonl')) == []
    assert load_alerts_file(None) == []


def test_load_alerts_file_skips_incomplete(tmp_path):
    path = str(tmp_path / 'alerts.jsonl')
    write_lines(path, [{'stamp': 1.0, 'level': 'CRITICAL'}])
    assert load_alerts_file(path) == []