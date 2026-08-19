"""SNS notifier for CRITICAL alerts, throttled to N per M minutes.

Pure logic, no ROS. boto3 is imported lazily; tests inject a fake client.

Throttle state (timestamps of recent sends) is persisted to a local file
so throttling survives process restarts and separate cron invocations.
"""

import os
import time

SNS_STATE_FILENAME = 'aws_sync_sns_state'

_CRITICAL = 'CRITICAL'


class SNSNotifier:

    def __init__(self, topic_arn, region='ap-south-1', client=None,
                 state_path=None, max_messages=1, window_minutes=10,
                 now_fn=None):
        self.topic_arn = topic_arn
        self.region = region
        self.state_path = state_path
        self.max_messages = max(1, int(max_messages))
        self.window_seconds = float(window_minutes) * 60.0
        self.now_fn = now_fn or time.time
        if client is None:
            client = self._make_client()
        self.client = client

    def _make_client(self):
        import boto3
        return boto3.client('sns', region_name=self.region)

    def _load_state(self):
        if not self.state_path or not os.path.isfile(self.state_path):
            return []
        try:
            with open(self.state_path) as f:
                values = []
                for line in f:
                    line = line.strip()
                    if line:
                        values.append(float(line))
                return values
        except (ValueError, OSError):
            return []

    def _save_state(self, timestamps):
        if not self.state_path:
            return
        tmp = self.state_path + '.tmp'
        with open(tmp, 'w') as f:
            for ts in timestamps:
                f.write('%.6f\n' % ts)
        os.replace(tmp, self.state_path)

    def publish(self, alerts, dry_run=False):
        """Publish CRITICAL alerts, respecting the N-per-window throttle.

        Returns (sent, throttled). In dry_run mode no SNS calls happen and
        the throttle state is not modified.
        """
        critical = [a for a in alerts
                    if str(a.get('level', '')).upper() == _CRITICAL]
        if not critical:
            return 0, 0
        now = self.now_fn()
        recent = [t for t in self._load_state()
                  if now - t < self.window_seconds]
        allowed = max(0, self.max_messages - len(recent))
        sent = 0
        for alert in critical[:allowed]:
            subject = 'h1 alert %s' % _CRITICAL
            message = str(alert.get('message', ''))[:1000]
            if not dry_run:
                self.client.publish(
                    TopicArn=self.topic_arn,
                    Subject=subject,
                    Message=message,
                )
            recent.append(now)
            sent += 1
        if not dry_run:
            self._save_state(sorted(recent)[-self.max_messages:])
        throttled = max(0, len(critical) - sent)
        return sent, throttled