#!/usr/bin/env python3
"""Create Lambda deployment package for h1_aws_sync.

Zips the h1_aws_sync pure logic plus a Lambda handler that calls
sync_telemetry.main(dry_run=False) and returns the sync result as JSON.

Outputs: h1_aws_sync_lambda.zip ready for aws lambda create/update-function-code.
"""

import os
import sys
import zipfile
import shutil
import tempfile
from pathlib import Path


def create_lambda_handler():
    """Generate the lambda_handler.py content."""
    return '''"""Lambda handler for h1_aws_sync_ingest.

Entry point for AWS Lambda. Calls sync_telemetry.run() with dry_run=False
and returns the sync result as JSON.
"""

import json
import os
import sys

# Ensure the packaged h1_aws_sync module is importable
sys.path.insert(0, os.path.dirname(__file__))

from h1_aws_sync.sync_telemetry import run
from h1_aws_sync.config import load_config


def handler(event, context):
    """AWS Lambda handler.

    Args:
        event: Lambda event dict (unused, reserved for future config override).
        context: Lambda context object.

    Returns:
        dict with statusCode and body (JSON string of sync summary).
    """
    try:
        # Load config from packaged aws_sync.yaml (with env var overrides)
        config_path = os.environ.get('AWS_SYNC_CONFIG_PATH')
        cfg = load_config(config_path)

        # Allow event to override data_dir (for testing)
        data_dir = event.get('data_dir') if isinstance(event, dict) else None

        # Run the sync (NOT dry-run - this is the production Lambda)
        summary = run(cfg, data_dir=data_dir, dry_run=False)

        return {
            'statusCode': 200,
            'body': json.dumps(summary)
        }
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
'''


def main():
    ws_root = Path('/home/ubuntu/humanoid_sim_ws')
    src_pkg = ws_root / 'src' / 'h1_aws_sync' / 'src' / 'h1_aws_sync'
    config_file = ws_root / 'src' / 'h1_aws_sync' / 'config' / 'aws_sync.yaml'
    output_zip = ws_root / 'h1_aws_sync_lambda.zip'

    if not src_pkg.exists():
        print(f'ERROR: Source package not found: {src_pkg}', file=sys.stderr)
        sys.exit(1)
    if not config_file.exists():
        print(f'ERROR: Config file not found: {config_file}', file=sys.stderr)
        sys.exit(1)

    # Clean up any existing zip
    if output_zip.exists():
        output_zip.unlink()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        pkg_dir = tmp / 'h1_aws_sync'
        pkg_dir.mkdir()

        # Copy the h1_aws_sync package (source files only)
        for item in src_pkg.iterdir():
            if item.name in ('__pycache__', '.pytest_cache', 'test'):
                continue
            if item.suffix == '.pyc':
                continue
            if item.is_file():
                shutil.copy2(item, pkg_dir / item.name)
            elif item.is_dir():
                shutil.copytree(item, pkg_dir / item.name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'test*'))

        # Write lambda_handler.py
        (tmp / 'lambda_handler.py').write_text(create_lambda_handler())

        # Copy config file to package root (so it's findable by load_config)
        shutil.copy2(config_file, tmp / 'aws_sync.yaml')

        # Create the zip file
        with zipfile.ZipFile(output_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(tmp):
                # Skip __pycache__ directories
                dirs[:] = [d for d in dirs if d != '__pycache__']
                for file in files:
                    if file.endswith('.pyc'):
                        continue
                    filepath = Path(root) / file
                    arcname = filepath.relative_to(tmp)
                    zf.write(filepath, arcname)

    # Verify zip contents
    print(f'Created: {output_zip}')
    print(f'Size: {output_zip.stat().st_size} bytes')
    print()
    print('Zip contents:')
    with zipfile.ZipFile(output_zip, 'r') as zf:
        for info in zf.infolist():
            print(f'  {info.filename} ({info.file_size} bytes)')

    # Validate key files exist
    with zipfile.ZipFile(output_zip, 'r') as zf:
        names = zf.namelist()
        required = [
            'lambda_handler.py',
            'h1_aws_sync/__init__.py',
            'h1_aws_sync/sync_telemetry.py',
            'h1_aws_sync/config.py',
            'h1_aws_sync/alerts.py',
            'h1_aws_sync/s3_uploader.py',
            'h1_aws_sync/dynamodb_writer.py',
            'h1_aws_sync/sns_notifier.py',
            'aws_sync.yaml',
        ]
        missing = [r for r in required if r not in names]
        if missing:
            print(f'ERROR: Missing required files in zip: {missing}', file=sys.stderr)
            sys.exit(1)
        print()
        print('All required files present.')


if __name__ == '__main__':
    main()