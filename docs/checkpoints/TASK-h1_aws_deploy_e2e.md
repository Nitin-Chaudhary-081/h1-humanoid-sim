# TASK-h1_aws_deploy_e2e — M4.4 live e2e + schema fix

**Date**: 2026-08-22 · **Owner**: main thread (Session 14) · **Status**: DONE (Lambda remains admin-blocked)

## What changed
- `src/h1_aws_sync/src/h1_aws_sync/dynamodb_writer.py`: item key `ts` → `timestamp`
  (live table KeySchema = timestamp HASH / alert_id RANGE; code assumed the inverse).
- `src/h1_aws_sync/test/test_dynamodb_writer.py`: updated key assertions.
- `docs/ADMIN_DEPLOYMENT.md`: appended Live Status section (resource table, admin
  command sequence, verbatim e2e output).

## Verification evidence
1. Unit: `pytest src/h1_aws_sync/test/ -q` → **46 passed**.
2. Live e2e (`sync_telemetry.main([])` against real AWS):
   - S3 upload 17 lines → `s3://h1-sim-telemetry/telemetry/2026/08/22/telemetry-1787367989.jsonl` ✓
   - DynamoDB 17 alerts → `scan --select COUNT` = **17** ✓ (pre-fix this raised
     ValidationException: Missing the key timestamp in the item)
   - SNS publish OK (1 critical sent, 16 throttled)
3. SNS email subscription re-created → pending confirmation at stickfitofficial@gmail.com.

## Remaining (external)
- Admin runs `scripts/create_iam_role.sh` then `scripts/deploy_aws_stack.sh`
  (dev-user lacks iam:CreateRole — AccessDenied captured in /tmp/opencode/aws_deploy.log).
- Human clicks SNS confirmation email.

## Next step
After Lambda is live: set function URL for M9 dashboard hook, wire sync_runner cron.
