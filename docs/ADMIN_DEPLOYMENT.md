# M4.4 Admin Deployment Guide — AWS Sync Stack

This guide covers deploying the `h1_aws_sync` Lambda + SNS + DynamoDB telemetry ingestion stack on AWS (Free Tier only).

---

## 1. Prerequisites

### Tools
- **AWS CLI v2** — `aws --version` → `aws-cli/2.x`
- **jq** — `jq --version` → `jq-1.6+`
- **Python 3.10+** — for `deploy_lambda.py`
- **zip** — for packaging Lambda

### IAM Permissions (Exact Policies)
Attach these managed policies to your deployment user/role:
| Policy ARN | Purpose |
|---|---|
| `arn:aws:iam::aws:policy/IAMFullAccess` | Create role, attach policies |
| `arn:aws:iam::aws:policy/AWSLambda_FullAccess` | Create/update Lambda function |
| `arn:aws:iam::aws:policy/AmazonSNSFullAccess` | Create topic + subscription |
| `arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess` | Create table + write items |
| `arn:aws:iam::aws:policy/AmazonS3FullAccess` | Create bucket + upload zip |
| `arn:aws:iam::aws:policy/CloudWatchLogsFullAccess` | Lambda log group |
| `arn:aws:iam::aws:policy/CloudWatchFullAccess` | Dashboard + billing alarm |

> **Least-privilege alternative**: create a custom policy with only the specific actions listed in `scripts/create_iam_role.sh` (see script for exact action list).

---

## 2. Create IAM Role for Lambda

```bash
cd /home/ubuntu/humanoid_sim_ws
./scripts/create_iam_role.sh
```

Output example:
```
ROLE_ARN=arn:aws:iam::123456789012:role/h1-aws-sync-lambda-role
```

**Capture the `ROLE_ARN`** — you need it for the next step.

---

## 3. Package & Deploy Lambda Code

```bash
./scripts/deploy_lambda.py
```

This creates `h1_aws_sync_lambda.zip` in the workspace root with:
- `sync_telemetry.py` (handler)
- `config.py`, `dynamodb_writer.py`, `s3_uploader.py`, `sns_notifier.py`, `alerts.py`
- `aws_sync.yaml` config

Verify:
```bash
unzip -l h1_aws_sync_lambda.zip
```

---

## 4. Create Lambda Function

```bash
./scripts/create_lambda.sh <ROLE_ARN>
```

Example:
```bash
./scripts/create_lambda.sh arn:aws:iam::123456789012:role/h1-aws-sync-lambda-role
```

Output:
```
Function created: h1_aws_sync_ingest
```

---

## 5. Test Lambda Invocation

```bash
aws lambda invoke \
  --function-name h1_aws_sync_ingest \
  --payload '{}' \
  /tmp/out.json
```

Check response:
```bash
cat /tmp/out.json | jq .
```

Expected:
```json
{
  "statusCode": 200,
  "body": "{\"status\": \"ok\", \"items_written\": 0, ...}"
}
```

Check CloudWatch Logs:
```bash
aws logs tail /aws/lambda/h1_aws_sync_ingest --follow
```

---

## 6. Verify SNS Subscription

1. Check email inbox for **"AWS Notification - Subscription Confirmation"**
2. Click **"Confirm subscription"** link
3. Verify in console:
   ```bash
   aws sns list-subscriptions-by-topic --topic-arn <TOPIC_ARN>
   ```
   `SubscriptionArn` should be a valid ARN (not `PendingConfirmation`).

> The topic ARN is printed by `create_lambda.sh` or found in `aws_sync.yaml` under `sns_topic_arn`.

---

## 7. Enable Telemetry Sync on Robot

Edit the telemetry node config:
```yaml
# src/h1_telemetry/config/thresholds.yaml
h1_telemetry:
  ros__parameters:
    sync_enabled: true
    # ... other params
```

Rebuild and restart:
```bash
cd /home/ubuntu/humanoid_sim_ws
colcon build --packages-select h1_telemetry
# Restart the telemetry node (or full bringup)
```

Verify sync is running:
```bash
ros2 topic echo /h1/telemetry/sync_status --once
```
Should show `sync_enabled: true` and periodic `last_sync_ts` updates.

---

## 8. Cost Monitoring

### CloudWatch Dashboard
A dashboard named `H1-AWS-Sync-Cost` is created by the stack with:
- Lambda invocations / duration / errors
- SNS publish count
- DynamoDB write capacity / throttles
- S3 PUT requests
- Estimated monthly cost (metric math)

### Billing Alarm (Already Configured)
- **Alarm name**: `H1-Monthly-Cost-Alarm`
- **Threshold**: $5.00 (Free Tier buffer)
- **Action**: SNS → email (same topic as alerts)

Verify:
```bash
aws cloudwatch describe-alarms --alarm-names H1-Monthly-Cost-Alarm
```

---

## 9. Teardown (Clean Up Free Tier Resources)

```bash
# Delete Lambda
aws lambda delete-function --function-name h1_aws_sync_ingest

# Delete SNS topic + subscription
aws sns delete-topic --topic-arn <TOPIC_ARN>

# Delete DynamoDB table
aws dynamodb delete-table --table-name h1_telemetry

# Delete S3 bucket (must be empty first)
aws s3 rb s3://h1-telemetry-<account-id> --force

# Delete IAM role
aws iam detach-role-policy --role-name h1-aws-sync-lambda-role --policy-arn <POLICY_ARN>
aws iam delete-role --role-name h1-aws-sync-lambda-role

# Delete CloudWatch dashboard + alarm
aws cloudwatch delete-dashboards --dashboard-names H1-AWS-Sync-Cost
aws cloudwatch delete-alarms --alarm-names H1-Monthly-Cost-Alarm
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `AccessDenied` on Lambda create | Ensure IAM user has `IAMFullAccess` + `Lambda_FullAccess` |
| SNS subscription stays `PendingConfirmation` | Check spam folder; re-run `create_lambda.sh` to resend |
| Lambda timeout (>30s) | Increase timeout in `create_lambda.sh` (`--timeout 60`) |
| DynamoDB `ProvisionedThroughputExceeded` | Enable on-demand capacity in `deploy_lambda.py` |
| Telemetry node shows `sync_enabled: false` | Rebuild `h1_telemetry` after config change; check param with `ros2 param get /h1_telemetry sync_enabled` |

---

## File Reference

| File | Purpose |
|---|---|
| `scripts/create_iam_role.sh` | Creates Lambda execution role + inline policy |
| `scripts/deploy_lambda.py` | Packages Python source into `h1_aws_sync_lambda.zip` |
| `scripts/create_lambda.sh` | Creates/updates Lambda function, SNS topic, DynamoDB table, S3 bucket |
| `src/h1_aws_sync/config/aws_sync.yaml` | Runtime config (table name, topic ARN, bucket, region) |
| `src/h1_telemetry/config/thresholds.yaml` | Robot-side `sync_enabled` flag |

---

## Security Notes

- **No hardcoded credentials** — Lambda uses IAM role
- **SNS topic** — email endpoint only; no HTTP/SQS
- **DynamoDB** — encryption at rest (AWS managed key)
- **S3** — bucket versioning enabled; block public access
- **CloudWatch** — logs retained 14 days (Free Tier)

---

*Generated for M4.4 — AWS Sync Stack Deployment*