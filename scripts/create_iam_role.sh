#!/bin/bash
# create_iam_role.sh
# Creates IAM role for h1_aws_sync Lambda function.
# Must be run by an admin with IAM permissions (iam:CreateRole, iam:PutRolePolicy, iam:AttachRolePolicy).
# Outputs the Role ARN for Lambda creation.

set -euo pipefail

ROLE_NAME="h1-aws-sync-lambda-role"
AWS_REGION="ap-south-1"
ACCOUNT_ID="250738719996"

# Trust policy for Lambda
TRUST_POLICY=$(cat <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "lambda.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF
)

# Inline policy for h1_aws_sync permissions
INLINE_POLICY=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "S3PutObject",
      "Effect": "Allow",
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::h1-sim-telemetry/*"
    },
    {
      "Sid": "DynamoDBPutItem",
      "Effect": "Allow",
      "Action": "dynamodb:PutItem",
      "Resource": "arn:aws:dynamodb:ap-south-1:250738719996:table/h1_alerts"
    },
    {
      "Sid": "SNSPublish",
      "Effect": "Allow",
      "Action": "sns:Publish",
      "Resource": "arn:aws:sns:ap-south-1:250738719996:h1-critical-alerts"
    }
  ]
}
EOF
)

echo "Creating IAM role: ${ROLE_NAME}"

# Create the role
ROLE_ARN=$(aws iam create-role \
    --role-name "${ROLE_NAME}" \
    --assume-role-policy-document "${TRUST_POLICY}" \
    --description "Role for h1_aws_sync Lambda to upload telemetry to S3, write alerts to DynamoDB, and publish critical alerts to SNS" \
    --query 'Role.Arn' \
    --output text)

echo "Role created: ${ROLE_ARN}"

# Attach managed policy for basic Lambda execution (CloudWatch Logs)
echo "Attaching managed policy: AWSLambdaBasicExecutionRole"
aws iam attach-role-policy \
    --role-name "${ROLE_NAME}" \
    --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"

# Put inline policy
echo "Putting inline policy: h1-aws-sync-permissions"
aws iam put-role-policy \
    --role-name "${ROLE_NAME}" \
    --policy-name "h1-aws-sync-permissions" \
    --policy-document "${INLINE_POLICY}"

echo ""
echo "=== SUCCESS ==="
echo "Role ARN: ${ROLE_ARN}"
echo ""
echo "Use this ARN in create_lambda.sh or aws lambda create-function:"
echo "  --role ${ROLE_ARN}"