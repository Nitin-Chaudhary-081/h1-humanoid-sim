"""DynamoDB alert recorder.

Pure logic, no ROS. boto3 is imported lazily; tests inject a fake client.

Alerts are put into a provisioned table (partition key alert_id, sort key
ts). The alert_id is a deterministic hash of the alert content so repeated
syncs overwrite the same item instead of duplicating it.
"""

import hashlib

from .alerts import normalize_stamp

DDB_TABLE = 'h1_alerts'


class DynamoDBAlertWriter:

    def __init__(self, table_name=DDB_TABLE, region='ap-south-1',
                 client=None):
        self.table_name = table_name
        self.region = region
        if client is None:
            client = self._make_client()
        self.client = client

    def _make_client(self):
        import boto3
        return boto3.client('dynamodb', region_name=self.region)

    @staticmethod
    def _alert_id(alert):
        raw = '{source}|{ts}|{score}|{message}'.format(
            source=alert['source'], ts=alert['stamp'],
            score=alert['score'], message=alert['message'])
        return hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]

    @staticmethod
    def _num(value):
        return {'N': repr(float(value))}

    @staticmethod
    def _str(value):
        return {'S': str(value)}

    def _to_item(self, alert):
        ts = normalize_stamp(alert['stamp'])
        return {
            'alert_id': self._str(self._alert_id(alert)),
            'ts': self._num(ts),
            'level': self._str(alert['level']),
            'source': self._str(alert['source']),
            'message': self._str(alert['message']),
            'score': self._num(alert['score']),
        }

    def put(self, alerts):
        """Put all alerts into the table. Returns the number written."""
        count = 0
        for alert in alerts:
            self.client.put_item(
                TableName=self.table_name,
                Item=self._to_item(alert),
            )
            count += 1
        return count