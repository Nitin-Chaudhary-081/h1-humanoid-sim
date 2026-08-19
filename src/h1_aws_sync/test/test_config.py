import os

from h1_aws_sync.config import DEFAULTS, default_config_path, load_config

CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          'config', 'aws_sync.yaml')


def test_packaged_config_exists_and_loads():
    assert os.path.isfile(CONFIG_DIR)
    cfg = load_config()
    assert cfg['bucket'] == 'h1-sim-telemetry'
    assert cfg['prefix'] == 'telemetry'
    assert cfg['region'] == 'ap-south-1'
    assert cfg['table'] == 'h1_alerts'
    assert cfg['topic_arn'].startswith('arn:aws:sns:')
    assert cfg['alert_throttle']['max_messages'] >= 1
    assert cfg['alert_throttle']['window_minutes'] > 0


def test_defaults_when_file_missing(tmp_path):
    cfg = load_config(os.path.join(str(tmp_path), 'nope.yaml'))
    assert cfg == DEFAULTS


def test_explicit_config_overrides_defaults(tmp_path):
    path = os.path.join(str(tmp_path), 'aws_sync.yaml')
    with open(path, 'w') as f:
        f.write('bucket: my-bucket\nregion: eu-west-1\nalert_throttle:\n  max_messages: 5\n')
    cfg = load_config(path)
    assert cfg['bucket'] == 'my-bucket'
    assert cfg['region'] == 'eu-west-1'
    assert cfg['alert_throttle']['max_messages'] == 5
    assert cfg['alert_throttle']['window_minutes'] == 10
    assert cfg['prefix'] == 'telemetry'


def test_default_config_path_points_at_packaged_file():
    assert os.path.isfile(default_config_path())
    assert default_config_path().endswith('config/aws_sync.yaml')