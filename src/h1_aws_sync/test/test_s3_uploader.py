import json

from conftest import FakeS3, write_lines
from h1_aws_sync.s3_uploader import S3_WATERMARK_FILENAME, S3Uploader

S1 = {'stamp': 100.0, 'cpu_load': 0.4, 'anomaly': True, 'detail': 'x'}
S2 = {'stamp': 101.0, 'cpu_load': 0.5, 'anomaly': False, 'detail': ''}
S3 = {'stamp': 102.0, 'cpu_load': 0.9, 'anomaly': True, 'detail': 'y'}

NOW = 1700000000.0  # 2023-11-14 22:13:20 UTC


def make_uploader(tmp_path, fake=None, **kw):
    telemetry = str(tmp_path / 'telemetry.jsonl')
    watermark = str(tmp_path / S3_WATERMARK_FILENAME)
    kw.setdefault('telemetry_path', telemetry)
    kw.setdefault('watermark_path', watermark)
    kw.setdefault('now_fn', lambda: NOW)
    kw.setdefault('client', fake or FakeS3())
    return S3Uploader(bucket='h1-sim-telemetry', prefix='telemetry',
                      region='ap-south-1', **kw)


def test_upload_new_lines_and_key_format(tmp_path):
    fake = FakeS3()
    up = make_uploader(tmp_path, fake)
    write_lines(up.telemetry_path, [S1, S2])
    r = up.sync()
    assert r['uploaded'] == 2
    assert len(fake.puts) == 1
    assert fake.puts[0]['Bucket'] == 'h1-sim-telemetry'
    assert fake.puts[0]['Key'] == 'telemetry/2023/11/14/telemetry-1700000000.jsonl'
    assert fake.puts[0]['ContentType'] == 'application/x-ndjson'
    body = fake.puts[0]['Body'].decode()
    assert body.count('\n') == 2
    assert json.loads(body.split('\n')[0]) == S1
    assert r['samples'] == [S1, S2]
    assert r['key'] == 'telemetry/2023/11/14/telemetry-1700000000.jsonl'


def test_watermark_idempotency_only_new_line_uploaded(tmp_path):
    fake = FakeS3()
    up = make_uploader(tmp_path, fake)
    write_lines(up.telemetry_path, [S1, S2])
    r1 = up.sync()
    assert r1['uploaded'] == 2
    assert len(fake.puts) == 1

    r2 = up.sync()
    assert r2['uploaded'] == 0
    assert r2['key'] is None
    assert len(fake.puts) == 1

    with open(up.telemetry_path, 'a') as f:
        f.write(json.dumps(S3) + '\n')
    r3 = up.sync()
    assert r3['uploaded'] == 1
    assert len(fake.puts) == 2
    assert json.loads(fake.puts[1]['Body'].decode()) == S3

    r4 = up.sync()
    assert r4['uploaded'] == 0
    assert len(fake.puts) == 2


def test_watermark_survives_new_uploader_instance(tmp_path):
    fake = FakeS3()
    up = make_uploader(tmp_path, fake)
    write_lines(up.telemetry_path, [S1, S2])
    up.sync()

    up2 = make_uploader(tmp_path, fake)
    with open(up2.telemetry_path, 'a') as f:
        f.write(json.dumps(S3) + '\n')
    r = up2.sync()
    assert r['uploaded'] == 1
    assert len(fake.puts) == 2
    assert json.loads(fake.puts[1]['Body'].decode()) == S3


def test_missing_file_no_crash(tmp_path):
    fake = FakeS3()
    up = make_uploader(tmp_path, fake)
    r = up.sync()
    assert r['uploaded'] == 0
    assert r['key'] is None
    assert len(fake.puts) == 0


def test_empty_file_no_crash(tmp_path):
    fake = FakeS3()
    up = make_uploader(tmp_path, fake)
    open(up.telemetry_path, 'w').close()
    r = up.sync()
    assert r['uploaded'] == 0
    assert len(fake.puts) == 0


def test_partial_tail_line_skipped_until_completed(tmp_path):
    fake = FakeS3()
    up = make_uploader(tmp_path, fake)
    with open(up.telemetry_path, 'w') as f:
        f.write(json.dumps(S1) + '\n')
        f.write(json.dumps(S2) + '\n')
        f.write(json.dumps(S3))  # no trailing newline (in-progress append)
    r = up.sync()
    assert r['uploaded'] == 2
    assert len(fake.puts) == 1

    with open(up.telemetry_path, 'a') as f:
        f.write('\n')
    r2 = up.sync()
    assert r2['uploaded'] == 1
    assert len(fake.puts) == 2
    assert json.loads(fake.puts[1]['Body'].decode()) == S3


def test_truncated_file_resets_watermark(tmp_path):
    fake = FakeS3()
    up = make_uploader(tmp_path, fake)
    write_lines(up.telemetry_path, [S1, S2])
    up.sync()
    with open(up.watermark_path, 'w') as f:
        f.write('99999')
    with open(up.telemetry_path, 'w') as f:
        f.write(json.dumps(S3) + '\n')
    r = up.sync()
    assert r['uploaded'] == 1
    assert len(fake.puts) == 2
    assert json.loads(fake.puts[1]['Body'].decode()) == S3


def test_dry_run_uploads_nothing_and_does_not_advance_watermark(tmp_path):
    fake = FakeS3()
    up = make_uploader(tmp_path, fake)
    write_lines(up.telemetry_path, [S1, S2])
    r1 = up.sync(dry_run=True)
    assert r1['uploaded'] == 2
    assert r1['key'] is not None
    assert len(fake.puts) == 0
    assert up.read_watermark() == 0

    r2 = up.sync(dry_run=True)
    assert r2['uploaded'] == 2  # still sees both lines (watermark untouched)
    assert len(fake.puts) == 0

    r3 = up.sync()
    assert r3['uploaded'] == 2
    assert len(fake.puts) == 1