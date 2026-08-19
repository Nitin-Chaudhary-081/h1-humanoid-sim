import json

from conftest import FakeDynamoDB
from h1_aws_sync.alerts import normalize_stamp
from h1_aws_sync.dynamodb_writer import DDB_TABLE, DynamoDBAlertWriter

ALERTS = [
    {'stamp': 100.5, 'level': 'CRITICAL', 'source': 'h1_telemetry',
     'message': 'anomaly: fall_risk_score_max=1.00', 'score': 1.0},
    {'stamp': {'sec': 200, 'nanosec': 500_000_000}, 'level': 'WARN',
     'source': 'h1_telemetry', 'message': 'anomaly: cpu_load_max=0.99',
     'score': 0.55},
]


def make_writer(fake=None):
    return DynamoDBAlertWriter(table_name=DDB_TABLE, region='ap-south-1',
                               client=fake or FakeDynamoDB())


def test_put_writes_all_alerts_with_alert_fields(tmp_path):
    fake = FakeDynamoDB()
    writer = make_writer(fake)
    n = writer.put(ALERTS)
    assert n == 2
    assert len(fake.items) == 2
    for call in fake.items:
        assert call['TableName'] == DDB_TABLE
        item = call['Item']
        assert set(item.keys()) == {
            'alert_id', 'ts', 'level', 'source', 'message', 'score'}
        assert 'S' in item['alert_id'] and item['alert_id']['S']
        assert item['ts']['N'] == repr(normalize_stamp(
            ALERTS[fake.items.index(call)]['stamp']))


def test_put_empty_alerts_makes_no_calls(tmp_path):
    fake = FakeDynamoDB()
    writer = make_writer(fake)
    assert writer.put([]) == 0
    assert len(fake.items) == 0


def test_alert_id_deterministic(tmp_path):
    writer = make_writer(FakeDynamoDB())
    id1 = writer._alert_id(ALERTS[0])
    id2 = writer._alert_id(ALERTS[0])
    assert id1 == id2
    assert len(id1) == 16


def test_item_fields_typed(tmp_path):
    fake = FakeDynamoDB()
    writer = make_writer(fake)
    writer.put([ALERTS[0]])
    item = fake.items[0]['Item']
    assert item['level'] == {'S': 'CRITICAL'}
    assert item['score'] == {'N': '1.0'}
    assert item['ts'] == {'N': '100.5'}