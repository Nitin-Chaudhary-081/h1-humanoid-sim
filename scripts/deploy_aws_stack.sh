#!/bin/bash
# deploy_aws_stack.sh
# End-to-end admin deployment for h1 AWS sync stack.
# Run by admin with IAM permissions (iam:CreateRole, iam:PutRolePolicy, iam:AttachRolePolicy, lambda:CreateFunction, lambda:UpdateFunctionCode, lambda:UpdateFunctionConfiguration, iam:PassRole).
# Reads resource ARNs from /tmp/opencode/aws_resources.json.
# Idempotent: safe to re-run (create-or-update logic).

set -euo pipefail

# --- Configuration ---
AWS_REGION="ap-south-1"
ACCOUNT_ID="250738719996"
RESOURCES_JSON="/tmp/opencode/aws_resources.json"
ROLE_NAME="h1-aws-sync-lambda-role"
LAMBDA_NAME="h1_aws_sync_ingest"
ZIP_FILE="/home/ubuntu/humanoid_sim_ws/h1_aws_sync_lambda.zip"
DEPLOY_LAMBDA_PY="/home/ubuntu/humanoid_sim_ws/scripts/deploy_lambda.py"
SNS_EMAIL="stickfitofficial@gmail.com"

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

# --- Step 1: Prerequisites check ---
check_prerequisites() {
    log_info "Step 1: Checking prerequisites..."

    # aws CLI v2
    if ! command -v aws &>/dev/null; then
        log_error "aws CLI not found. Install AWS CLI v2."
        exit 1
    fi
    AWS_VERSION=$(aws --version 2>&1 | head -1)
    if [[ ! "$AWS_VERSION" =~ ^aws-cli/2\. ]]; then
        log_error "AWS CLI v2 required. Found: $AWS_VERSION"
        exit 1
    fi
    log_success "AWS CLI: $AWS_VERSION"

    # jq
    if ! command -v jq &>/dev/null; then
        log_error "jq not found. Install jq."
        exit 1
    fi
    log_success "jq: $(jq --version)"

    # AWS credentials configured
    if ! aws sts get-caller-identity --region "$AWS_REGION" &>/dev/null; then
        log_error "AWS credentials not configured or invalid. Run 'aws configure' or set env vars."
        exit 1
    fi
    CALLER=$(aws sts get-caller-identity --region "$AWS_REGION" --query 'Account' --output text)
    if [[ "$CALLER" != "$ACCOUNT_ID" ]]; then
        log_error "AWS account mismatch. Expected $ACCOUNT_ID, got $CALLER"
        exit 1
    fi
    log_success "AWS credentials valid for account $ACCOUNT_ID in region $AWS_REGION"

    # Resources JSON exists
    if [[ ! -f "$RESOURCES_JSON" ]]; then
        log_error "Resources JSON not found: $RESOURCES_JSON"
        exit 1
    fi
    log_success "Resources JSON found: $RESOURCES_JSON"
}

# --- Step 2: Create/update IAM role ---
create_iam_role() {
    log_info "Step 2: Creating/updating IAM role: $ROLE_NAME"

    # Extract ARNs from resources JSON
    S3_BUCKET_ARN=$(jq -r '.resources.s3_bucket.arn' "$RESOURCES_JSON")
    DDB_TABLE_ARN=$(jq -r '.resources.dynamodb_table.arn' "$RESOURCES_JSON")
    SNS_TOPIC_ARN=$(jq -r '.resources.sns_topic.arn' "$RESOURCES_JSON")

    if [[ "$S3_BUCKET_ARN" == "null" || "$DDB_TABLE_ARN" == "null" || "$SNS_TOPIC_ARN" == "null" ]]; then
        log_error "Required resource ARNs not found in $RESOURCES_JSON"
        exit 1
    fi

    # Trust policy for Lambda
    TRUST_POLICY=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "lambda.amazonaws.com" },
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
      "Resource": "${S3_BUCKET_ARN}/*"
    },
    {
      "Sid": "DynamoDBPutItem",
      "Effect": "Allow",
      "Action": "dynamodb:PutItem",
      "Resource": "${DDB_TABLE_ARN}"
    },
    {
      "Sid": "SNSPublish",
      "Effect": "Allow",
      "Action": "sns:Publish",
      "Resource": "${SNS_TOPIC_ARN}"
    }
  ]
}
EOF
)

    # Check if role exists
    if aws iam get-role --role-name "$ROLE_NAME" --region "$AWS_REGION" &>/dev/null; then
        log_warn "Role $ROLE_NAME exists, updating policies..."
        ROLE_ARN=$(aws iam get-role --role-name "$ROLE_NAME" --region "$AWS_REGION" --query 'Role.Arn' --output text)
    else
        log_info "Creating role $ROLE_NAME..."
        ROLE_ARN=$(aws iam create-role \
            --role-name "$ROLE_NAME" \
            --assume-role-policy-document "$TRUST_POLICY" \
            --description "Role for h1_aws_sync Lambda to upload telemetry to S3, write alerts to DynamoDB, and publish critical alerts to SNS" \
            --query 'Role.Arn' \
            --output text \
            --region "$AWS_REGION")
        log_success "Role created: $ROLE_ARN"
    fi

    # Attach managed policy for basic Lambda execution (CloudWatch Logs)
    log_info "Attaching managed policy: AWSLambdaBasicExecutionRole"
    aws iam attach-role-policy \
        --role-name "$ROLE_NAME" \
        --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole" \
        --region "$AWS_REGION"

    # Put/replace inline policy
    log_info "Putting inline policy: h1-aws-sync-permissions"
    aws iam put-role-policy \
        --role-name "$ROLE_NAME" \
        --policy-name "h1-aws-sync-permissions" \
        --policy-document "$INLINE_POLICY" \
        --region "$AWS_REGION"

    log_success "IAM role ready: $ROLE_ARN"
    echo "$ROLE_ARN"
}

# --- Step 3: Build Lambda zip ---
build_lambda_zip() {
    log_info "Step 3: Building Lambda deployment package..."
    if [[ ! -f "$DEPLOY_LAMBDA_PY" ]]; then
        log_error "deploy_lambda.py not found: $DEPLOY_LAMBDA_PY"
        exit 1
    fi
    python3 "$DEPLOY_LAMBDA_PY"
    if [[ ! -f "$ZIP_FILE" ]]; then
        log_error "Lambda zip not created: $ZIP_FILE"
        exit 1
    fi
    log_success "Lambda zip built: $ZIP_FILE ($(stat -c%s "$ZIP_FILE") bytes)"
}

# --- Step 4: Create/update Lambda function ---
create_lambda_function() {
    log_info "Step 4: Creating/updating Lambda function: $LAMBDA_NAME"

    ROLE_ARN=$(jq -r '.resources.iam_role.arn' "$RESOURCES_JSON")
    if [[ "$ROLE_ARN" == "null" || -z "$ROLE_ARN" ]]; then
        log_error "IAM role ARN not found in resources JSON. Run IAM role creation first."
        exit 1
    fi

    S3_BUCKET=$(jq -r '.resources.s3_bucket.name' "$RESOURCES_JSON")
    DDB_TABLE=$(jq -r '.resources.dynamodb_table.name' "$RESOURCES_JSON")
    SNS_TOPIC_ARN=$(jq -r '.resources.sns_topic.arn' "$RESOURCES_JSON")

    if [[ ! -f "$ZIP_FILE" ]]; then
        log_error "Lambda zip not found: $ZIP_FILE. Run build step first."
        exit 1
    fi

    # Check if function exists
    if aws lambda get-function --function-name "$LAMBDA_NAME" --region "$AWS_REGION" &>/dev/null; then
        log_info "Function exists, updating code and configuration..."

        aws lambda update-function-code \
            --function-name "$LAMBDA_NAME" \
            --zip-file "fileb://$ZIP_FILE" \
            --region "$AWS_REGION" \
            --no-cli-pager

        aws lambda update-function-configuration \
            --function-name "$LAMBDA_NAME" \
            --handler "lambda_handler.handler" \
            --timeout 30 \
            --memory-size 256 \
            --environment "Variables={S3_BUCKET=$S3_BUCKET,DDB_TABLE=$DDB_TABLE,SNS_TOPIC_ARN=$SNS_TOPIC_ARN,AWS_SYNC_CONFIG_PATH=/var/task/aws_sync.yaml}" \
            --region "$AWS_REGION" \
            --no-cli-pager
    else
        log_info "Function does not exist, creating..."

        aws lambda create-function \
            --function-name "$LAMBDA_NAME" \
            --runtime "python3.12" \
            --role "$ROLE_ARN" \
            --handler "lambda_handler.handler" \
            --zip-file "fileb://$ZIP_FILE" \
            --timeout 30 \
            --memory-size 256 \
            --environment "Variables={S3_BUCKET=$S3_BUCKET,DDB_TABLE=$DDB_TABLE,SNS_TOPIC_ARN=$SNS_TOPIC_ARN,AWS_SYNC_CONFIG_PATH=/var/task/aws_sync.yaml}" \
            --region "$AWS_REGION" \
            --no-cli-pager
    fi

    FUNCTION_ARN=$(aws lambda get-function --function-name "$LAMBDA_NAME" --region "$AWS_REGION" --query 'Configuration.FunctionArn' --output text)
    log_success "Lambda function ready: $FUNCTION_ARN"
    echo "$FUNCTION_ARN"
}

# --- Step 5: Wait for Lambda active and test invoke ---
test_lambda() {
    log_info "Step 5: Waiting for Lambda active state and testing invoke..."

    # Wait for function to be Active
    local max_wait=60
    local waited=0
    while [[ $waited -lt $max_wait ]]; do
        STATE=$(aws lambda get-function --function-name "$LAMBDA_NAME" --region "$AWS_REGION" --query 'Configuration.State' --output text 2>/dev/null || echo "Pending")
        if [[ "$STATE" == "Active" ]]; then
            log_success "Lambda is Active"
            break
        fi
        log_info "Lambda state: $STATE (waiting...)"
        sleep 5
        waited=$((waited + 5))
    done

    if [[ "$STATE" != "Active" ]]; then
        log_error "Lambda did not become Active within ${max_wait}s. Last state: $STATE"
        exit 1
    fi

    # Test invoke with empty payload
    log_info "Testing Lambda invoke with empty payload..."
    RESULT=$(aws lambda invoke \
        --function-name "$LAMBDA_NAME" \
        --payload '{}' \
        --region "$AWS_REGION" \
        --no-cli-pager \
        /dev/stdout 2>&1)

    STATUS_CODE=$(echo "$RESULT" | jq -r '.statusCode // "unknown"')
    BODY=$(echo "$RESULT" | jq -r '.body // "no body"')

    if [[ "$STATUS_CODE" == "200" ]]; then
        log_success "Lambda test invoke PASSED (statusCode: 200)"
        log_info "Response: $BODY"
        TEST_RESULT="PASS"
    else
        log_error "Lambda test invoke FAILED (statusCode: $STATUS_CODE)"
        log_error "Response: $BODY"
        TEST_RESULT="FAIL"
    fi
}

# --- Step 6: Check SNS subscription status ---
check_sns_subscription() {
    log_info "Step 6: Checking SNS subscription status for $SNS_EMAIL..."

    SNS_TOPIC_ARN=$(jq -r '.resources.sns_topic.arn' "$RESOURCES_JSON")

    SUBSCRIPTIONS=$(aws sns list-subscriptions-by-topic \
        --topic-arn "$SNS_TOPIC_ARN" \
        --region "$AWS_REGION" \
        --query 'Subscriptions[?Protocol==`email` && Endpoint==`'$SNS_EMAIL'`]' \
        --output json)

    if [[ "$SUBSCRIPTIONS" == "[]" ]]; then
        log_warn "No email subscription found for $SNS_EMAIL on topic $SNS_TOPIC_ARN"
        SUB_STATUS="NOT_FOUND"
    else
        SUB_ARN=$(echo "$SUBSCRIPTIONS" | jq -r '.[0].SubscriptionArn')
        if [[ "$SUB_ARN" == "PendingConfirmation" ]]; then
            log_warn "SNS subscription for $SNS_EMAIL is PENDING (email confirmation required)"
            SUB_STATUS="PENDING"
        else
            log_success "SNS subscription for $SNS_EMAIL is CONFIRMED"
            SUB_STATUS="CONFIRMED"
        fi
    fi
}

# --- Step 7: Output summary ---
output_summary() {
    log_info "Step 7: Deployment Summary"
    echo ""
    echo "=========================================="
    echo "       H1 AWS SYNC STACK DEPLOYMENT"
    echo "=========================================="
    echo ""

    # Resource ARNs from JSON
    S3_BUCKET_ARN=$(jq -r '.resources.s3_bucket.arn' "$RESOURCES_JSON")
    DDB_TABLE_ARN=$(jq -r '.resources.dynamodb_table.arn' "$RESOURCES_JSON")
    SNS_TOPIC_ARN=$(jq -r '.resources.sns_topic.arn' "$RESOURCES_JSON")
    ROLE_ARN=$(jq -r '.resources.iam_role.arn' "$RESOURCES_JSON")
    LAMBDA_ARN=$(aws lambda get-function --function-name "$LAMBDA_NAME" --region "$AWS_REGION" --query 'Configuration.FunctionArn' --output text 2>/dev/null || echo "NOT_CREATED")

    echo "Resource ARNs:"
    echo "  S3 Bucket:     $S3_BUCKET_ARN"
    echo "  DynamoDB Table: $DDB_TABLE_ARN"
    echo "  SNS Topic:     $SNS_TOPIC_ARN"
    echo "  IAM Role:      $ROLE_ARN"
    echo "  Lambda Function: $LAMBDA_ARN"
    echo ""
    echo "Lambda Test Result: $TEST_RESULT"
    echo "SNS Subscription:   $SUB_STATUS (for $SNS_EMAIL)"
    echo ""
    echo "=========================================="
    if [[ "$TEST_RESULT" == "PASS" && "$SUB_STATUS" == "CONFIRMED" ]]; then
        log_success "DEPLOYMENT COMPLETE - All checks passed"
    elif [[ "$TEST_RESULT" == "PASS" ]]; then
        log_warn "DEPLOYMENT COMPLETE - Lambda works, but SNS subscription pending confirmation"
    else
        log_error "DEPLOYMENT INCOMPLETE - Lambda test failed"
    fi
    echo "=========================================="
}

# --- Main ---
main() {
    echo ""
    echo "=========================================="
    echo "   H1 AWS SYNC STACK DEPLOYMENT (M4.4)"
    echo "=========================================="
    echo ""

    check_prerequisites
    ROLE_ARN=$(create_iam_role)

    # Update resources JSON with role ARN if not present
    CURRENT_ROLE_ARN=$(jq -r '.resources.iam_role.arn' "$RESOURCES_JSON")
    if [[ "$CURRENT_ROLE_ARN" == "null" || "$CURRENT_ROLE_ARN" != "$ROLE_ARN" ]]; then
        log_info "Updating resources JSON with IAM role ARN..."
        jq --arg arn "$ROLE_ARN" '.resources.iam_role.arn = $arn | .resources.iam_role.status = "CREATED"' "$RESOURCES_JSON" > "${RESOURCES_JSON}.tmp" && mv "${RESOURCES_JSON}.tmp" "$RESOURCES_JSON"
    fi

    build_lambda_zip
    FUNCTION_ARN=$(create_lambda_function)
    test_lambda
    check_sns_subscription
    output_summary
}

main "$@"