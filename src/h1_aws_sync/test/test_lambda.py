"""Integration-style tests for Lambda deployment package and handler.

Validates zip structure and handler signature without AWS calls.
"""

import json
import os
import sys
import zipfile
from pathlib import Path

import pytest


def get_project_root():
    return Path(__file__).parent.parent.parent.parent


def test_deploy_lambda_script_exists():
    """deploy_lambda.py script exists in scripts/."""
    script = get_project_root() / 'scripts' / 'deploy_lambda.py'
    assert script.is_file(), f'Missing: {script}'


def test_lambda_zip_created_by_script():
    """Running deploy_lambda.py produces a valid zip with required files."""
    # Run the script
    script = get_project_root() / 'scripts' / 'deploy_lambda.py'
    import subprocess
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        cwd=str(get_project_root())
    )
    assert result.returncode == 0, f'deploy_lambda.py failed: {result.stderr}'

    zip_path = get_project_root() / 'h1_aws_sync_lambda.zip'
    assert zip_path.is_file(), 'Zip file not created'

    # Validate zip contents
    with zipfile.ZipFile(zip_path, 'r') as zf:
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
        for req in required:
            assert req in names, f'Missing from zip: {req}'

        # No test files, no __pycache__, no .pyc
        for name in names:
            assert '__pycache__' not in name
            assert not name.endswith('.pyc')
            assert 'test' not in name.split('/') or name == 'aws_sync.yaml'


def test_lambda_handler_signature():
    """lambda_handler.handler(event, context) returns proper response dict."""
    # Ensure the packaged module is importable
    zip_path = get_project_root() / 'h1_aws_sync_lambda.zip'
    assert zip_path.is_file(), 'Run deploy_lambda.py first'

    with zipfile.ZipFile(zip_path, 'r') as zf:
        # Extract to temp location for import
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            zf.extractall(tmpdir)
            sys.path.insert(0, tmpdir)

            import lambda_handler

            # Verify handler function exists
            assert hasattr(lambda_handler, 'handler'), 'handler function not found'

            # Create fake clients for testing (mirror conftest.py)
            class FakeS3:
                def __init__(self):
                    self.puts = []
                def put_object(self, **kwargs):
                    self.puts.append(dict(kwargs))
                    return {}

            class FakeDynamoDB:
                def __init__(self):
                    self.items = []
                def put_item(self, **kwargs):
                    self.items.append(dict(kwargs))
                    return {}

            class FakeSNS:
                def __init__(self):
                    self.publishes = []
                def publish(self, **kwargs):
                    self.publishes.append(dict(kwargs))
                    return {}

            fake_clients = {
                's3': FakeS3(),
                'dynamodb': FakeDynamoDB(),
                'sns': FakeSNS(),
            }

            # Patch boto3.client to return fake clients
            import boto3
            original_client = boto3.client

            def mock_client(service, **kwargs):
                if service in fake_clients:
                    return fake_clients[service]
                return original_client(service, **kwargs)

            boto3.client = mock_client
            try:
                # Create minimal telemetry file for the test
                telemetry_path = os.path.join(tmpdir, 'telemetry.jsonl')
                with open(telemetry_path, 'w') as f:
                    f.write('{"stamp": 100.0, "cpu_load": 0.5, "anomaly": false, "detail": ""}\n')

                event = {'data_dir': tmpdir}
                context = type('Context', (), {'function_name': 'test'})()

                response = lambda_handler.handler(event, context)

                # Validate response structure
                assert isinstance(response, dict)
                assert 'statusCode' in response
                assert 'body' in response
                assert response['statusCode'] == 200

                body = json.loads(response['body'])
                assert isinstance(body, dict)
                assert 'dry_run' in body
                assert 'uploaded' in body
                assert 'alerts' in body
                assert 'written' in body
                assert 'sent' in body
                assert 'throttled' in body
            finally:
                boto3.client = original_client


def test_lambda_handler_error_handling():
    """Handler returns 500 on exception."""
    zip_path = get_project_root() / 'h1_aws_sync_lambda.zip'
    assert zip_path.is_file(), 'Run deploy_lambda.py first'

    with zipfile.ZipFile(zip_path, 'r') as zf:
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            zf.extractall(tmpdir)
            sys.path.insert(0, tmpdir)

            import lambda_handler

            # Force an error by making load_config raise in lambda_handler's namespace
            original_load = lambda_handler.load_config

            def failing_load_config(path=None):
                raise RuntimeError('Config load failed')

            lambda_handler.load_config = failing_load_config
            try:
                response = lambda_handler.handler({}, None)
                assert response['statusCode'] == 500
                body = json.loads(response['body'])
                assert 'error' in body
                assert 'Config load failed' in body['error']
            finally:
                lambda_handler.load_config = original_load


def test_iam_role_script_exists():
    """create_iam_role.sh exists and is executable."""
    script = get_project_root() / 'scripts' / 'create_iam_role.sh'
    assert script.is_file(), f'Missing: {script}'
    assert os.access(script, os.X_OK), f'Not executable: {script}'


def test_lambda_creation_script_exists():
    """create_lambda.sh exists and is executable."""
    script = get_project_root() / 'scripts' / 'create_lambda.sh'
    assert script.is_file(), f'Missing: {script}'
    assert os.access(script, os.X_OK), f'Not executable: {script}'


def test_iam_role_script_syntax():
    """create_iam_role.sh passes shellcheck (if available) or basic bash -n."""
    script = get_project_root() / 'scripts' / 'create_iam_role.sh'
    import subprocess
    import shutil
    # Try shellcheck first
    if shutil.which('shellcheck'):
        result = subprocess.run(
            ['shellcheck', str(script)],
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            pytest.fail(f'shellcheck failed:\n{result.stdout}\n{result.stderr}')
    # Fallback: bash -n for syntax check
    result = subprocess.run(
        ['bash', '-n', str(script)],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0, f'bash syntax error: {result.stderr}'


def test_lambda_creation_script_syntax():
    """create_lambda.sh passes basic bash -n."""
    script = get_project_root() / 'scripts' / 'create_lambda.sh'
    import subprocess
    result = subprocess.run(
        ['bash', '-n', str(script)],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0, f'bash syntax error: {result.stderr}'