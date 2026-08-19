import os

from conftest import FakeSNS
from h1_aws_sync.sns_notifier import SNSNotifier

ARN = 'arn:aws:sns:ap-south-1:250738719996:h1-alerts'

CRIT = {'stamp': 1.0, 'level': 'CRITICAL', 'source': 'h1_telemetry',
        'message': 'anomaly: fall', 'score': 1.0}
WARN = {'stamp': 2.0, 'level': 'WARN', 'source': 'h1_telemetry',
        'message': 'anomaly: cpu', 'score': 0.5}
INFO = {'stamp': 3.0, 'level': 'INFO', 'source': 'x', 'message': 'ok', 'score': 0.1}


def make_notifier(tmp_path, fake=None, max_messages=1, window_minutes=10,
                  now=None):
    if now is None:
        now = [1000.0]
    notifier = SNSNotifier(
        topic_arn=ARN,
        region='ap-south-1',
        client=fake or FakeSNS(),
        state_path=str(tmp_path / 'aws_sync_sns_state'),
        max_messages=max_messages,
        window_minutes=window_minutes,
        now_fn=lambda: now[0],
    )
    return notifier, now


def test_only_critical_passes_and_throttle_blocks_second(tmp_path):
    fake = FakeSNS()
    notifier, now = make_notifier(tmp_path, fake)
    sent, throttled = notifier.publish([WARN, CRIT, INFO, CRIT])
    assert sent == 1
    assert throttled == 1
    assert len(fake.publishes) == 1
    pub = fake.publishes[0]
    assert pub['TopicArn'] == ARN
    assert 'fall' in pub['Message']
    assert pub['Subject'] == 'h1 alert CRITICAL'


def test_no_critical_no_calls(tmp_path):
    fake = FakeSNS()
    notifier, _ = make_notifier(tmp_path, fake)
    sent, throttled = notifier.publish([WARN, INFO])
    assert sent == 0
    assert throttled == 0
    assert len(fake.publishes) == 0


def test_throttle_respects_n_per_m_minutes(tmp_path):
    fake = FakeSNS()
    notifier, now = make_notifier(tmp_path, fake, max_messages=1, window_minutes=10)
    sent, _ = notifier.publish([CRIT])
    assert sent == 1
    assert len(fake.publishes) == 1

    now[0] += 5 * 60  # 5 min later, inside window
    sent, throttled = notifier.publish([CRIT])
    assert sent == 0
    assert throttled == 1
    assert len(fake.publishes) == 1

    now[0] += 5 * 60 + 1  # 10+1 min later, outside window
    sent, _ = notifier.publish([CRIT])
    assert sent == 1
    assert len(fake.publishes) == 2


def test_throttle_state_persists_across_instances(tmp_path):
    fake = FakeSNS()
    notifier, now = make_notifier(tmp_path, fake)
    notifier.publish([CRIT])
    assert len(fake.publishes) == 1

    fresh, _ = make_notifier(tmp_path, FakeSNS(), now=now)
    sent, throttled = fresh.publish([CRIT])
    assert sent == 0
    assert throttled == 1
    assert len(fake.publishes) == 1


def test_multiple_per_window(tmp_path):
    fake = FakeSNS()
    notifier, _ = make_notifier(tmp_path, fake, max_messages=3, window_minutes=10)
    sent, throttled = notifier.publish([CRIT, CRIT, CRIT, CRIT, CRIT])
    assert sent == 3
    assert throttled == 2
    assert len(fake.publishes) == 3


def test_dry_run_no_calls_and_no_state_change(tmp_path):
    fake = FakeSNS()
    notifier, _ = make_notifier(tmp_path, fake)
    sent, throttled = notifier.publish([CRIT, CRIT], dry_run=True)
    assert sent == 1
    assert throttled == 1
    assert len(fake.publishes) == 0
    assert not os.path.exists(notifier.state_path)

    sent, _ = notifier.publish([CRIT])
    assert sent == 1
    assert len(fake.publishes) == 1