"""One-shot telemetry -> AWS sync runner (entry point).

No ROS imports. Order of operations: upload new JSONL lines to S3, derive
alerts from the uploaded samples (plus optional explicit alerts file), put
them into DynamoDB, and notify CRITICAL alerts via SNS (throttled).

Use --dry-run to see what would happen without touching any AWS resource
or local state.
"""

import argparse
import json
import os
import sys

from .alerts import alerts_from_samples, load_alerts_file
from .config import load_config
from .dynamodb_writer import DynamoDBAlertWriter
from .s3_uploader import S3Uploader
from .sns_notifier import SNSNotifier


def build_components(cfg, data_dir, clients=None):
    """Construct uploader/writer/notifier from config, with optional DI.

    clients: dict with keys s3/dynamodb/sns (fake clients for tests).
    """
    throttle = cfg.get('alert_throttle', {})
    return (
        S3Uploader(
            bucket=cfg['bucket'],
            prefix=cfg['prefix'],
            region=cfg['region'],
            telemetry_path=os.path.join(data_dir, cfg['telemetry_file']),
            watermark_path=os.path.join(data_dir, cfg['watermark_file']),
            content_type=cfg.get('s3', {}).get('content_type'),
            client=(clients or {}).get('s3'),
        ),
        DynamoDBAlertWriter(
            table_name=cfg['table'],
            region=cfg['region'],
            client=(clients or {}).get('dynamodb'),
        ),
        SNSNotifier(
            topic_arn=cfg['topic_arn'],
            region=cfg['region'],
            client=(clients or {}).get('sns'),
            state_path=os.path.join(data_dir, cfg['sns_state_file']),
            max_messages=throttle.get('max_messages', 1),
            window_minutes=throttle.get('window_minutes', 10),
        ),
    )


def run(cfg, data_dir=None, clients=None, dry_run=False):
    """Run one sync pass. Returns a summary dict of what happened."""
    data_dir = data_dir or cfg['data_dir']
    uploader, writer, notifier = build_components(cfg, data_dir, clients)

    result = uploader.sync(dry_run=dry_run)
    samples = result['samples']

    alerts = alerts_from_samples(samples)
    alert_file = os.path.join(data_dir, 'alerts.jsonl')
    alerts += load_alerts_file(alert_file)

    written = 0
    if alerts and not dry_run:
        written = writer.put(alerts)

    sent, throttled = notifier.publish(alerts, dry_run=dry_run)

    return {
        'dry_run': bool(dry_run),
        'bucket': cfg['bucket'],
        'uploaded': result['uploaded'],
        'key': result['key'],
        'alerts': len(alerts),
        'written': written if not dry_run else len(alerts),
        'sent': sent,
        'throttled': throttled,
    }


def _print_summary(summary):
    mode = 'DRY-RUN (no AWS calls, no state changes)'
    if summary['dry_run']:
        print(mode)
    s3_line = 'S3      : upload %d line(s) -> s3://%s/%s' % (
        summary['uploaded'], summary['bucket'], summary['key'] or '-')
    print(s3_line)
    print('DynamoDB: write %d alert(s) -> table h1_alerts' % summary['alerts'])
    print('SNS     : send %d critical notification(s) (throttled %d)' % (
        summary['sent'], summary['throttled']))
    if not summary['dry_run']:
        print('done: %d line(s) uploaded, %d alert(s) written, %d sent' % (
            summary['uploaded'], summary['written'], summary['sent']))


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='sync_telemetry',
        description='Sync telemetry JSONL to S3, alerts to DynamoDB/SNS.')
    parser.add_argument('--config', default=None,
                        help='path to aws_sync.yaml (default: packaged config)')
    parser.add_argument('--data-dir', default=None,
                        help='override data directory from config')
    parser.add_argument('--dry-run', action='store_true',
                        help='print what would be done without any AWS calls')
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    summary = run(cfg, data_dir=args.data_dir, dry_run=args.dry_run)
    _print_summary(summary)
    return 0


if __name__ == '__main__':
    sys.exit(main())