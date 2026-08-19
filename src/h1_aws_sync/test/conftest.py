import json
import os

import pytest

REAL_LINE_WARN = ('{"stamp": 979.246, "cpu_load": 0.987, "ram_used_mb": 1551.87109375, '
                  '"joint_states_hz": 785.7142857137243, "odometry_hz": 49.99999999999859, '
                  '"imu_hz": 99.99999999999908, "body_pitch_deg": -83.47812075505276, '
                  '"body_roll_deg": -90.00006372627361, "fall_risk_score": 1.0, '
                  '"anomaly_score": 1.0, "anomaly": true, '
                  '"detail": "cpu_load_max=0.99 (limit > 0.95); fall_risk_score_max=1.00 (limit > 0.80)"}')

REAL_LINE_CRITICAL = ('{"stamp": 978.253, "cpu_load": 0.0, "ram_used_mb": 1527.97265625, '
                      '"joint_states_hz": 846.1538461533003, "odometry_hz": 49.999999999997094, '
                      '"imu_hz": 99.99999999999521, "body_pitch_deg": -83.44905027142312, '
                      '"body_roll_deg": -90.00014297809446, "fall_risk_score": 1.0, '
                      '"anomaly_score": 1.0, "anomaly": true, '
                      '"detail": "fall_risk_score_max=1.00 (limit > 0.80)"}')

REAL_SAMPLE_WARN = json.loads(REAL_LINE_WARN)
REAL_SAMPLE_CRITICAL = json.loads(REAL_LINE_CRITICAL)


class FakeS3:
    def __init__(self):
        self.puts = []

    def put_object(self, **kwargs):
        self.puts.append(dict(kwargs))
        return {}


class FakeDynamoDB:
    def __init__(self):
        self.items = []

    def put_item(self, **kwargs):
        self.items.append(dict(kwargs))
        return {}


class FakeSNS:
    def __init__(self):
        self.publishes = []

    def publish(self, **kwargs):
        self.publishes.append(dict(kwargs))
        return {}


@pytest.fixture
def fake_clients():
    return {'s3': FakeS3(), 'dynamodb': FakeDynamoDB(), 'sns': FakeSNS()}


def write_lines(path, lines):
    with open(path, 'w') as f:
        for line in lines:
            f.write(line if isinstance(line, str) else json.dumps(line))
            f.write('\n')


def read_all(path):
    with open(path) as f:
        return f.read()


def ensure_dirs(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path