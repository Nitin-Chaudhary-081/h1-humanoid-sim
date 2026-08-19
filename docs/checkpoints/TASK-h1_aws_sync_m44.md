# TASK-h1_aws_sync_m44 — Complete AWS sync package (h1_aws_sync) + create AWS resources

## Summary
Completed the h1_aws_sync package implementation and created AWS resources (Always-Free tier only, region ap-south-1, account 250738719996).

## Changes Made

### Pure Logic Modules (src/h1_aws_sync/src/h1_aws_sync/)

1. **config.py** — Verified: loads aws_sync.yaml with DEFAULTS, merges overrides
2. **s3_uploader.py** — Added exponential backoff retry (`_put_with_retry` with max_retries=3, base_delay=1.0s)
3. **dynamodb_writer.py** — Fixed key schema to pk=timestamp (N), sk=alert_id (S); added condition expression for idempotency (`attribute_not_exists(#pk) AND attribute_not_exists(#sk)`); implemented batch_write for efficiency
4. **sns_notifier.py** — Changed message format to `{alert_id, timestamp, severity, detail, robot_state}`; uses AlertThrottle from alerts.py
5. **alerts.py** — Added `AlertSeverity` enum (WARN/CRITICAL) and `AlertThrottle` class (sliding window, persists state to file)
6. **sync_telemetry.py** — Added `SyncRunner` class; reads data/telemetry.jsonl, uploads via S3Uploader, processes alerts via DynamoDBWriter + SNSNotifier, uses watermark file for resume

### AWS Resources Created (Always-Free)

| Resource | Name/Details | Status |
|---|---|---|
| S3 Bucket | `h1-sim-telemetry` with lifecycle expire 30 days | ✅ Created & verified |
| DynamoDB Table | `h1_alerts` (provisioned 5 RCU / 5 WCU), pk=timestamp (N), sk=alert_id (S) | ✅ Created & verified |
| SNS Topic | `h1-alerts` (arn:aws:sns:ap-south-1:250738719996:h1-alerts) | ✅ Created & verified |
| SNS Subscription | email → stickfitofficial@gmail.com | ✅ Created (pending confirmation) |
| IAM Role | `h1-aws-sync-lambda-role` | ⚠️ Manual (requires iam:CreateRole) |
| Lambda Function | `h1-telemetry-ingest` (Python 3.12, zip with deps) | ⚠️ Blocked on IAM role |

### Scripts Updated
- `scripts/create_iam_role.sh` — Fixed resource ARNs (S3 bucket, SNS topic)
- `scripts/create_lambda.sh` — Updated to use `h1-telemetry-ingest` function name, removed dependency on external JSON

### Unit Tests
All 46 tests pass covering:
- Watermark logic (idempotency, partial lines, truncation, dry-run)
- Alert throttling (sliding window, persistence, dry-run bypass)
- Retry logic (exponential backoff)
- Idempotency (condition expression, deterministic alert_id)
- Full sync runner integration

## Verification Commands (All Pass)
```bash
# Unit tests
cd /home/ubuntu/wt-h1_aws_sync && PYTHONPATH=src python3 -m pytest src/h1_aws_sync/test/ -q
# → 46 passed

# AWS resources
aws s3 ls s3://h1-sim-telemetry --region ap-south-1
# → S3 bucket exists

aws dynamodb describe-table --table-name h1_alerts --region ap-south-1
# → Table ACTIVE, pk=timestamp, sk=alert_id, 5/5 RCU/WCU

aws sns list-topics --region ap-south-1 | grep h1-alerts
# → Topic exists
```

## Known Issues / Next Steps
1. **IAM Role**: User `dev-user` lacks `iam:CreateRole` permission (has PowerUserAccess + IAMReadOnly). Role must be created by admin or user with IAMFullAccess.
2. **Lambda Function**: Blocked on IAM role creation.
3. **SNS Subscription**: Pending email confirmation at stickfitofficial@gmail.com.

## Files Modified
- src/h1_aws_sync/src/h1_aws_sync/s3_uploader.py (retry logic)
- src/h1_aws_sync/src/h1_aws_sync/dynamodb_writer.py (key schema, batch_write, condition)
- src/h1_aws_sync/src/h1_aws_sync/sns_notifier.py (message format, AlertThrottle integration)
- src/h1_aws_sync/src/h1_aws_sync/alerts.py (AlertSeverity, AlertThrottle, _alert_id)
- src/h1_aws_sync/src/h1_aws_sync/sync_telemetry.py (SyncRunner class)
- src/h1_aws_sync/test/conftest.py (FakeDynamoDB.batch_write_item)
- src/h1_aws_sync/test/test_dynamodb_writer.py (updated for new schema)
- src/h1_aws_sync/test/test_sns_notifier.py (updated for new message format, dry_run behavior)
- src/h1_aws_sync/test/test_sync_runner.py (updated test data, expectations)
- scripts/create_iam_role.sh (fixed resource ARNs)
- scripts/create_lambda.sh (fixed function name, removed JSON dependency)