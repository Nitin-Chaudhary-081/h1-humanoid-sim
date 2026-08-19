"""Alert extraction from telemetry samples and explicit alert files.

Pure logic, no ROS. Mirrors h1_telemetry's Alert derivation: an anomaly
sample becomes an Alert with fields stamp, level, source, message, score.

CRITICAL suffixes mirror h1_telemetry (tilt/fall thresholds), everything
else WARN.
"""

import json
import os

ALERT_FIELDS = ('stamp', 'level', 'source', 'message', 'score')
CRITICAL_SUFFIXES = ('body_pitch_deg_max', 'body_roll_deg_max',
                     'fall_risk_score_max')
ALERT_SOURCE = 'h1_telemetry'


def normalize_stamp(stamp):
    """Normalize a ROS Time / numeric stamp to float seconds.

    Accepts int/float seconds, or a dict with sec/nanosec keys.
    """
    if isinstance(stamp, dict):
        sec = float(stamp.get('sec', stamp.get('secs', 0)) or 0)
        nsec = float(stamp.get('nanosec', stamp.get('nanosec', 0)) or 0)
        return sec + nsec / 1e9
    try:
        return float(stamp)
    except (TypeError, ValueError):
        return 0.0


def alert_level(detail):
    """Map a telemetry anomaly detail string to WARN or CRITICAL."""
    for suffix in CRITICAL_SUFFIXES:
        if suffix in str(detail):
            return 'CRITICAL'
    return 'WARN'


def alert_from_telemetry_line(sample):
    """Build an Alert dict from one telemetry sample dict, or None.

    Only anomaly samples produce alerts (mirrors h1_telemetry._publish).
    """
    if not isinstance(sample, dict) or not sample.get('anomaly'):
        return None
    detail = str(sample.get('detail', ''))
    return {
        'stamp': normalize_stamp(sample.get('stamp', 0.0)),
        'level': alert_level(detail),
        'source': ALERT_SOURCE,
        'message': 'anomaly: ' + detail,
        'score': float(sample.get('anomaly_score', 0.0)),
    }


def alerts_from_samples(samples):
    """Map a list of telemetry sample dicts to alert dicts (anomalies only)."""
    out = []
    for sample in samples:
        alert = alert_from_telemetry_line(sample)
        if alert is not None:
            out.append(alert)
    return out


def load_alerts_file(path):
    """Load explicit alert dicts from a JSONL file (Alert field format).

    Each line must contain stamp/level/source/message/score. Missing file
    or empty file yields []. Non-conforming lines are skipped.
    """
    if not path or not os.path.isfile(path):
        return []
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if not isinstance(record, dict) or not all(
                    k in record for k in ALERT_FIELDS):
                continue
            out.append({
                'stamp': normalize_stamp(record['stamp']),
                'level': str(record['level']).upper(),
                'source': str(record['source']),
                'message': str(record['message']),
                'score': float(record['score']),
            })
    return out