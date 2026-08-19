import json
import os

import h1_aws_sync.sync_telemetry as runner
from conftest import FakeS3, FakeDynamoDB, FakeSNS, write_lines
from h1_aws_sync.config import DEFAULTS, load_config
from h1_aws_sync.s3_uploader import S3_WATERMARK_FILENAME

S1 = {'stamp': 100.0, 'cpu_load': 0.4, 'anomaly': True,
      'anomaly_score': 1.0, 'detail': 'fall_risk_score_max=1.00'}
S2 = {'stamp': 101.0, 'cpu_load': 0.5, 'anomaly': False, 'detail': ''}
S3 = {'stamp': 102.0, 'cpu_load': 0.9, 'anomaly': True,
      'anomaly_score': 0.6, 'detail': 'cpu_load_max=0.99'}

NOW = 1700000000.0


def make_cfg(tmp_path):
    cfg = dict(DEFAULTS)
    cfg['data_dir'] = str(tmp_path)
    return cfg


def make_fakes():
    return {'s3': FakeS3(), 'dynamodb': FakeDynamoDB(), 'sns': FakeSNS()}


def run_sync(tmp_path, dry_run=False, clients=None, extra_alerts=None):
    cfg = make_cfg(tmp_path)
    telemetry = os.path.join(str(tmp_path), cfg['telemetry_file'])
    write_lines(telemetry, [S1, S2, S3])
    if extra_alerts:
        write_lines(os.path.join(str(tmp_path), 'alerts.jsonl'), extra_alerts)
    fakes = clients or make_fakes()
    summary = runner.run(cfg, data_dir=str(tmp_path), clients=fakes,
                         dry_run=dry_run)
    return summary, fakes


def test_full_sync_uploads_writes_and_notifies(tmp_path):
    summary, fakes = run_sync(tmp_path)
    assert summary['uploaded'] == 3
    assert summary['alerts'] == 2
    assert summary['written'] == 2
    assert summary['sent'] == 1  # only the CRITICAL one, throttle max 1
    assert summary['throttled'] == 0  # exactly one critical in batch
    assert len(fakes['s3'].puts) == 1
    assert len(fakes['dynamodb'].items) == 2
    assert len(fakes['sns'].publishes) == 1
    assert fakes['sns'].publishes[0]['Message'].startswith('anomaly: fall')
    assert os.path.exists(os.path.join(str(tmp_path), S3_WATERMARK_FILENAME))


def test_rerun_uploads_nothing_duplicates_nothing(tmp_path):
    summary1, fakes = run_sync(tmp_path)
    assert summary1['uploaded'] == 3
    summary2, fakes = run_sync(tmp_path, clients=fakes)
    assert summary2['uploaded'] == 0
    assert summary2['alerts'] == 0
    assert len(fakes['s3'].puts) == 1
    assert len(fakes['dynamodb'].items) == 2


def test_dry_run_no_calls_no_state(tmp_path):
    summary, fakes = run_sync(tmp_path, dry_run=True)
    assert summary['dry_run'] is True
    assert summary['uploaded'] == 3
    assert summary['alerts'] == 2
    assert summary['written'] == 2
    assert summary['sent'] == 1
    assert len(fakes['s3'].puts) == 0
    assert len(fakes['dynamodb'].items) == 0
    assert len(fakes['sns'].publishes) == 0
    assert not os.path.exists(
        os.path.join(str(tmp_path), S3_WATERMARK_FILENAME))
    assert not os.path.exists(
        os.path.join(str(tmp_path), 'aws_sync_sns_state'))


def test_dry_run_prints_plan(capsys, tmp_path):
    summary, _ = run_sync(tmp_path, dry_run=True)
    runner._print_summary(summary)
    out = capsys.readouterr().out
    assert 'DRY-RUN' in out
    assert 'upload 3 line(s)' in out
    assert 'write 2 alert(s)' in out
    assert 'send 1 critical' in out


def test_main_cli_dry_run_flag(capsys, tmp_path, monkeypatch):
    captured = {}
    printed = {}

    def fake_run(cfg, data_dir=None, clients=None, dry_run=False):
        captured['dry_run'] = dry_run
        captured['cfg'] = cfg
        return {'dry_run': dry_run, 'bucket': cfg['bucket'], 'uploaded': 0,
                'key': None, 'alerts': 0, 'written': 0, 'sent': 0,
                'throttled': 0}

    def fake_print(summary):
        printed['summary'] = summary

    monkeypatch.setattr(runner, 'run', fake_run)
    monkeypatch.setattr(runner, '_print_summary', fake_print)
    rc = runner.main(['--dry-run', '--data-dir', str(tmp_path)])
    assert rc == 0
    assert captured['dry_run'] is True
    assert captured['cfg']['data_dir'] == DEFAULTS['data_dir']
    assert printed['summary']['dry_run'] is True


def test_explicit_alerts_file_merged(tmp_path):
    extra = [{'stamp': 50.0, 'level': 'CRITICAL', 'source': 'estop',
              'message': 'estop pressed', 'score': 1.0}]
    summary, fakes = run_sync(tmp_path, extra_alerts=extra)
    assert summary['alerts'] == 3
    assert len(fakes['dynamodb'].items) == 3
    assert len(fakes['sns'].publishes) == 1