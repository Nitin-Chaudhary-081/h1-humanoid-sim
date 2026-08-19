"""Config loading for h1_aws_sync. Pure logic, no ROS, no boto3.

Loads config/aws_sync.yaml (or an explicit path) and merges it over
sane defaults so every parameter is always present.
"""

import os

try:
    import yaml
except ImportError:
    yaml = None

CONFIG_FILENAME = 'aws_sync.yaml'

DEFAULTS = {
    'bucket': 'h1-sim-telemetry',
    'prefix': 'telemetry',
    'region': 'ap-south-1',
    'data_dir': '/home/ubuntu/humanoid_sim_ws/data',
    'telemetry_file': 'telemetry.jsonl',
    'watermark_file': 'aws_sync_watermark',
    'sns_state_file': 'aws_sync_sns_state',
    'table': 'h1_alerts',
    'topic_arn': 'arn:aws:sns:ap-south-1:250738719996:h1-alerts',
    'alert_throttle': {'max_messages': 1, 'window_minutes': 10},
    's3': {'content_type': 'application/x-ndjson'},
}


def default_config_path():
    """Path to the packaged config yaml (works in source tree and install)."""
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(os.path.dirname(os.path.dirname(here)),
                     'config', CONFIG_FILENAME),
        os.path.join(here, 'config', CONFIG_FILENAME),
    ]
    for prefix in (os.environ.get('AMENT_PREFIX_PATH') or '').split(os.pathsep):
        if prefix:
            candidates.append(os.path.join(prefix, 'share',
                                           'h1_aws_sync', 'config',
                                           CONFIG_FILENAME))
    for cand in candidates:
        if os.path.isfile(cand):
            return cand
    return candidates[0]


def load_config(path=None):
    """Load config yaml and merge over defaults.

    Args:
        path: explicit yaml path. If None, uses the packaged
            config/aws_sync.yaml. Missing file is not an error (defaults win).
    """
    cfg = dict(DEFAULTS)
    path = path or default_config_path()
    if path and os.path.isfile(path) and yaml is not None:
        with open(path) as f:
            loaded = yaml.safe_load(f) or {}
        if isinstance(loaded, dict):
            for k, v in loaded.items():
                if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                    cfg[k] = {**cfg[k], **v}
                else:
                    cfg[k] = v
    return cfg