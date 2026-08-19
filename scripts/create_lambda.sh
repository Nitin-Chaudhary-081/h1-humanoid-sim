#!/bin/bash
# create_lambda.sh
# Creates/updates the h1_aws_sync_ingest Lambda function.
# Requires: IAM role ARN (from create_iam_role.sh), deployment zip (from deploy_lambda.py).
# Reads resource ARNs from /tmp/opencode/aws_resources.json.

set -euo pipefail

LAMBDA_NAME="h1_aws_sync_ingest"
AWS_REGION="ap-south-1"
ZIP_FILE="/home/ubuntu/humanoid_sim_ws/h1_aws_sync_lambda.zip"
RESOURCES_JSON="/tmp/opencode/aws_resources.json"

if [[ ! -f "${ZIP_FILE}" ]]; then
    echo "ERROR: Deployment zip not found: ${ZIP_FILE}"
    echo "Run scripts/deploy_lambda.py first."
    exit 1
fi

if [[ ! -f "${RESOURCES_JSON}" ]]; then
    echo "ERROR: Resources JSON not found: ${RESOURCES_JSON}"
    exit 1
fi

# Extract ARNs from resources JSON
S3_BUCKET=$(jq -r '.resources.s3_bucket.name' "${RESOURCES_JSON}")
DDB_TABLE=$(jq -r '.resources.dynamodb_table.name' "${RESOURCES_JSON}")
SNS_TOPIC_ARN=$(jq -r '.resources.sns_topic.arn' "${RESOURCES_JSON}")
ROLE_ARN=$(jq -r '.resources.iam_role.arn' "${RESOURCES_JSON}")

if [[ "${ROLE_ARN}" == "null" || -z "${ROLE_ARN}" ]]; then
    echo "ERROR: IAM role ARN not found in ${RESOURCES_JSON}. Run create_iam_role.sh first and update the JSON."
    exit 1
fi

echo "Creating/updating Lambda: ${LAMBDA_NAME}"
echo "  Runtime: python3.12"
echo "  Handler: lambda_handler.handler"
echo "  Timeout: 30s"
echo "  Memory: 256MB"
echo "  Role: ${ROLE_ARN}"
echo "  Env vars: S3_BUCKET=${S3_BUCKET}, DDB_TABLE=${DDB_TABLE}, SNS_TOPIC_ARN=${SNS_TOPIC_ARN}"

# Check if function exists
if aws lambda get-function --function-name "${LAMBDA_NAME}" --region "${AWS_REGION}" >/dev/null 2>&1; then
    echo "Function exists, updating code and configuration..."

    # Update function code
    aws lambda update-function-code \
        --function-name "${LAMBDA_NAME}" \
        --zip-file "fileb://${ZIP_FILE}" \
        --region "${AWS_REGION}" \
        --no-cli-pager

    # Update function configuration (env vars, timeout, memory)
    aws lambda update-function-configuration \
        --function-name "${LAMBDA_NAME}" \
        --handler "lambda_handler.handler" \
        --timeout 30 \
        --memory-size 256 \
        --environment "Variables={S3_BUCKET=${S3_BUCKET},DDB_TABLE=${DDB_TABLE},SNS_TOPIC_ARN=${SNS_TOPIC_ARN},AWS_SYNC_CONFIG_PATH=/var/task/aws_sync.yaml}" \
        --region "${AWS_REGION}" \
        --no-cli-pager
else
    echo "Function does not exist, creating..."

    aws lambda create-function \
        --function-name "${LAMBDA_NAME}" \
        --runtime "python3.12" \
        --role "${ROLE_ARN}" \
        --handler "lambda_handler.handler" \
        --zip-file "fileb://${ZIP_FILE}" \
        --timeout 30 \
        --memory-size 256 \
        --environment "Variables={S3_BUCKET=${S3_BUCKET},DDB_TABLE=${DDB_TABLE},SNS_TOPIC_ARN=${SNS_TOPIC_ARN},AWS_SYNC_CONFIG_PATH=/var/task/aws_sync.yaml}" \
        --region "${AWS_REGION}" \
        --no-cli-pager
fi

# Get function ARN
FUNCTION_ARN=$(aws lambda get-function --function-name "${LAMBDA_NAME}" --region "${AWS_REGION}" --query 'Configuration.FunctionArn' --output text)

echo ""
echo "=== SUCCESS ==="
echo "Lambda ARN: ${FUNCTION_ARN}"
echo ""
echo "Test with:"
echo "  aws lambda invoke --function-name ${LAMBDA_NAME} --payload '{}' /dev/stdout --region ${AWS_REGION}"