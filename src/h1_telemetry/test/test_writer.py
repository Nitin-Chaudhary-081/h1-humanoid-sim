# Unit tests for writer.py (pure, no ROS).
import csv
import json
import os

from h1_telemetry.writer import CSV_FILENAME, JSONL_FILENAME, SampleWriter

SAMPLE = {'stamp': 1234.5, 'cpu_load': 0.42, 'body_pitch_deg': 3.0,
          'anomaly': False}


def test_writes_csv_and_jsonl_creates_dir(tmp_path):
    data_dir = tmp_path / 'nested' / 'data'
    w = SampleWriter(str(data_dir))
    w.write(SAMPLE)
    assert os.path.isfile(str(data_dir / CSV_FILENAME))
    assert os.path.isfile(str(data_dir / JSONL_FILENAME))


def test_header_once_and_append(tmp_path):
    w = SampleWriter(str(tmp_path))
    w.write(SAMPLE)
    w.write({**SAMPLE, 'cpu_load': 0.9})
    with open(str(tmp_path / CSV_FILENAME)) as f:
        lines = list(csv.reader(f))
    assert len(lines) == 3  # 1 header + 2 rows
    assert lines[0] == list(SAMPLE.keys())
    assert lines[1][1] == '0.42'
    assert lines[2][1] == '0.9'


def test_no_header_dupe_across_restart(tmp_path):
    w1 = SampleWriter(str(tmp_path))
    w1.write(SAMPLE)
    w2 = SampleWriter(str(tmp_path))  # new writer, same dir (restart)
    w2.write({**SAMPLE, 'cpu_load': 0.1})
    with open(str(tmp_path / CSV_FILENAME)) as f:
        lines = list(csv.reader(f))
    assert len(lines) == 3
    assert lines[0] == list(SAMPLE.keys())


def test_jsonl_lines_are_valid_json(tmp_path):
    w = SampleWriter(str(tmp_path))
    w.write(SAMPLE)
    w.write({**SAMPLE, 'anomaly': True, 'extra': 'ignored-by-csv'})
    lines = open(str(tmp_path / JSONL_FILENAME)).read().strip().split('\n')
    assert len(lines) == 2
    parsed = [json.loads(l) for l in lines]
    assert parsed[0]['cpu_load'] == 0.42
    assert parsed[1]['anomaly'] is True
    assert 'extra' in parsed[1]  # jsonl keeps everything, csv does not


def test_sample_keys_stable_after_first_write(tmp_path):
    w = SampleWriter(str(tmp_path))
    w.write({'a': 1, 'b': 2})
    keys = w.write({'a': 3, 'b': 4, 'c': 5})  # c ignored in csv
    assert keys == ['a', 'b']
    with open(str(tmp_path / CSV_FILENAME)) as f:
        rows = list(csv.DictReader(f))
    assert 'c' not in rows[1]


def test_custom_paths(tmp_path):
    w = SampleWriter(str(tmp_path), csv_path=str(tmp_path / 'x.csv'),
                     jsonl_path=str(tmp_path / 'x.jsonl'))
    w.write(SAMPLE)
    assert os.path.isfile(str(tmp_path / 'x.csv'))
    assert os.path.isfile(str(tmp_path / 'x.jsonl'))
    assert not os.path.exists(str(tmp_path / CSV_FILENAME))


def test_custom_keys_order(tmp_path):
    w = SampleWriter(str(tmp_path), sample_keys=['b', 'a'])
    w.write({'a': 1, 'b': 2})
    with open(str(tmp_path / CSV_FILENAME)) as f:
        header = next(csv.reader(f))
    assert header == ['b', 'a']
