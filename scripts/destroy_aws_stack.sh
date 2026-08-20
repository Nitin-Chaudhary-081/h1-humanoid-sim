#!/bin/bash
# destroy_aws_stack.sh
# Cleanup script for h1 AWS sync stack.
# Deletes: Lambda, IAM role policies/role, empties+deletes S3 bucket, deletes DynamoDB table, deletes SNS topic.
# Requires confirmations before destructive actions.
# Run by admin with IAM permissions.

set -euo pipefail

# --- Configuration ---
AWS_REGION="ap-south-1"
ACCOUNT_ID="250738719996"
RESOURCES_JSON="/tmp/opencode/aws_resources.json"
ROLE_NAME="h1-aws-sync-lambda-role"
LAMBDA_NAME="h1_aws_sync_ingest"

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

confirm() {
    local prompt="$1"
    local default="${2:-n}"
    local reply

    if [[ "$default" == "y" ]]; then
        prompt="$prompt [Y/n]: "
    else
        prompt="$prompt [y/N]: "
    fi

    read -r -p "$prompt" reply
    reply=${reply:-$default}
    [[ "$reply" =~ ^[Yy]$ ]]
}

check_prerequisites() {
    log_info "Checking prerequisites..."

    if ! command -v aws &>/dev/null; then
        log_error "aws CLI not found."
        exit 1
    fi
    if ! command -v jq &>/dev/null; then
        log_error "jq not found."
        exit 1
    fi
    if ! aws sts get-caller-identity --region "$AWS_REGION" &>/dev/null; then
        log_error "AWS credentials not configured or invalid."
        exit 1
    fi
    if [[ ! -f "$RESOURCES_JSON" ]]; then
        log_error "Resources JSON not found: $RESOURCES_JSON"
        exit 1
    fi

    CALLER=$(aws sts get-caller-identity --region "$AWS_REGION" --query 'Account' --output text)
    if [[ "$CALLER" != "$ACCOUNT_ID" ]]; then
        log_error "AWS account mismatch. Expected $ACCOUNT_ID, got $CALLER"
        exit 1
    fi

    log_success "Prerequisites OK (account: $ACCOUNT_ID, region: $AWS_REGION)"
}

load_resource_arns() {
    log_info "Loading resource ARNs from $RESOURCES_JSON..."

    S3_BUCKET_NAME=$(jq -r '.resources.s3_bucket.name // empty' "$RESOURCES_JSON")
    S3_BUCKET_ARN=$(jq -r '.resources.s3_bucket.arn // empty' "$RESOURCES_JSON")
    DDB_TABLE_NAME=$(jq -r '.resources.dynamodb_table.name // empty' "$RESOURCES_JSON")
    DDB_TABLE_ARN=$(jq -r '.resources.dynamodb_table.arn // empty' "$RESOURCES_JSON")
    SNS_TOPIC_ARN=$(jq -r '.resources.sns_topic.arn // empty' "$RESOURCES_JSON")
    ROLE_ARN=$(jq -r '.resources.iam_role.arn // empty' "$RESOURCES_JSON")
    LAMBDA_ARN=$(jq -r '.resources.lambda_function.arn // empty' "$RESOURCES_JSON")

    echo "Resources found:"
    [[ -n "$S3_BUCKET_NAME" ]] && echo "  S3 Bucket:     $S3_BUCKET_NAME ($S3_BUCKET_ARN)"
    [[ -n "$DDB_TABLE_NAME" ]] && echo "  DynamoDB Table: $DDB_TABLE_NAME ($DDB_TABLE_ARN)"
    [[ -n "$SNS_TOPIC_ARN" ]] && echo "  SNS Topic:     $SNS_TOPIC_ARN"
    [[ -n "$ROLE_ARN" ]] && echo "  IAM Role:      $ROLE_ARN"
    [[ -n "$LAMBDA_ARN" ]] && echo "  Lambda:        $LAMBDA_ARN"
    echo ""
}

# --- Delete Lambda ---
delete_lambda() {
    if [[ -z "$LAMBDA_ARN" || "$LAMBDA_ARN" == "null" ]]; then
        log_warn "Lambda ARN not in resources JSON, checking if function exists by name..."
        if ! aws lambda get-function --function-name "$LAMBDA_NAME" --region "$AWS_REGION" &>/dev/null; then
            log_info "Lambda function $LAMBDA_NAME does not exist."
            return 0
        fi
        LAMBDA_ARN=$(aws lambda get-function --function-name "$LAMBDA_NAME" --region "$AWS_REGION" --query 'Configuration.FunctionArn' --output text)
    fi

    log_info "Deleting Lambda function: $LAMBDA_NAME"
    if confirm "Delete Lambda function $LAMBDA_NAME?"; then
        aws lambda delete-function --function-name "$LAMBDA_NAME" --region "$AWS_REGION" --no-cli-pager
        log_success "Lambda deleted: $LAMBDA_NAME"
    else
        log_warn "Skipped Lambda deletion."
    fi
}

# --- Delete IAM Role ---
delete_iam_role() {
    if [[ -z "$ROLE_ARN" || "$ROLE_ARN" == "null" ]]; then
        log_warn "IAM role ARN not in resources JSON, checking if role exists by name..."
        if ! aws iam get-role --role-name "$ROLE_NAME" --region "$AWS_REGION" &>/dev/null; then
            log_info "IAM role $ROLE_NAME does not exist."
            return 0
        fi
        ROLE_ARN=$(aws iam get-role --role-name "$ROLE_NAME" --region "$AWS_REGION" --query 'Role.Arn' --output text)
    fi

    log_info "Deleting IAM role: $ROLE_NAME"

    # Detach managed policies
    log_info "Detaching managed policies..."
    ATTACHED=$(aws iam list-attached-role-policies --role-name "$ROLE_NAME" --region "$AWS_REGION" --query 'AttachedPolicies[].PolicyArn' --output text)
    for policy in $ATTACHED; do
        if confirm "Detach managed policy $policy from role $ROLE_NAME?"; then
            aws iam detach-role-policy --role-name "$ROLE_NAME" --policy-arn "$policy" --region "$AWS_REGION"
            log_success "Detached: $policy"
        fi
    done

    # Delete inline policies
    log_info "Deleting inline policies..."
    INLINE_POLICIES=$(aws iam list-role-policies --role-name "$ROLE_NAME" --region "$AWS_REGION" --query 'PolicyNames[]' --output text)
    for policy in $INLINE_POLICIES; do
        if confirm "Delete inline policy $policy from role $ROLE_NAME?"; then
            aws iam delete-role-policy --role-name "$ROLE_NAME" --policy-name "$policy" --region "$AWS_REGION"
            log_success "Deleted inline policy: $policy"
        fi
    done

    # Delete role
    if confirm "Delete IAM role $ROLE_NAME?"; then
        aws iam delete-role --role-name "$ROLE_NAME" --region "$AWS_REGION"
        log_success "IAM role deleted: $ROLE_NAME"
    else
        log_warn "Skipped IAM role deletion."
    fi
}

# --- Empty and Delete S3 Bucket ---
delete_s3_bucket() {
    if [[ -z "$S3_BUCKET_NAME" || "$S3_BUCKET_NAME" == "null" ]]; then
        log_warn "S3 bucket name not in resources JSON."
        return 0
    fi

    log_info "Emptying and deleting S3 bucket: $S3_BUCKET_NAME"

    # Check if bucket exists
    if ! aws s3api head-bucket --bucket "$S3_BUCKET_NAME" --region "$AWS_REGION" 2>/dev/null; then
        log_info "S3 bucket $S3_BUCKET_NAME does not exist."
        return 0
    fi

    # List objects (including versions)
    log_info "Listing objects in bucket..."
    OBJECT_COUNT=$(aws s3api list-object-versions --bucket "$S3_BUCKET_NAME" --region "$AWS_REGION" --query 'length(Versions)' --output text 2>/dev/null || echo "0")
    DELETE_MARKER_COUNT=$(aws s3api list-object-versions --bucket "$S3_BUCKET_NAME" --region "$AWS_REGION" --query 'length(DeleteMarkers)' --output text 2>/dev/null || echo "0")
    TOTAL=$((OBJECT_COUNT + DELETE_MARKER_COUNT))

    if [[ $TOTAL -gt 0 ]]; then
        log_warn "Bucket contains $OBJECT_COUNT object version(s) and $DELETE_MARKER_COUNT delete marker(s)."
        if confirm "Delete ALL objects and versions from $S3_BUCKET_NAME? This is IRREVERSIBLE."; then
            # Delete all versions
            aws s3api list-object-versions --bucket "$S3_BUCKET_NAME" --region "$AWS_REGION" --output json | \
                jq -r '.Versions[]? | "--key \(.Key) --version-id \(.VersionId)"' | \
                while read -r line; do
                    eval "aws s3api delete-object --bucket \"$S3_BUCKET_NAME\" $line --region \"$AWS_REGION\" --no-cli-pager"
                done
            # Delete all delete markers
            aws s3api list-object-versions --bucket "$S3_BUCKET_NAME" --region "$AWS_REGION" --output json | \
                jq -r '.DeleteMarkers[]? | "--key \(.Key) --version-id \(.VersionId)"' | \
                while read -r line; do
                    eval "aws s3api delete-object --bucket \"$S3_BUCKET_NAME\" $line --region \"$AWS_REGION\" --no-cli-pager"
                done
            log_success "All objects deleted from $S3_BUCKET_NAME"
        else
            log_warn "Skipped object deletion. Bucket must be empty before deletion."
            return 0
        fi
    else
        log_info "Bucket is already empty."
    fi

    if confirm "Delete S3 bucket $S3_BUCKET_NAME?"; then
        aws s3api delete-bucket --bucket "$S3_BUCKET_NAME" --region "$AWS_REGION" --no-cli-pager
        log_success "S3 bucket deleted: $S3_BUCKET_NAME"
    else
        log_warn "Skipped bucket deletion."
    fi
}

# --- Delete DynamoDB Table ---
delete_dynamodb_table() {
    if [[ -z "$DDB_TABLE_NAME" || "$DDB_TABLE_NAME" == "null" ]]; then
        log_warn "DynamoDB table name not in resources JSON."
        return 0
    fi

    log_info "Deleting DynamoDB table: $DDB_TABLE_NAME"

    if ! aws dynamodb describe-table --table-name "$DDB_TABLE_NAME" --region "$AWS_REGION" &>/dev/null; then
        log_info "DynamoDB table $DDB_TABLE_NAME does not exist."
        return 0
    fi

    if confirm "Delete DynamoDB table $DDB_TABLE_NAME? This is IRREVERSIBLE."; then
        aws dynamodb delete-table --table-name "$DDB_TABLE_NAME" --region "$AWS_REGION" --no-cli-pager
        log_info "Waiting for table deletion to complete..."
        aws dynamodb wait table-not-exists --table-name "$DDB_TABLE_NAME" --region "$AWS_REGION"
        log_success "DynamoDB table deleted: $DDB_TABLE_NAME"
    else
        log_warn "Skipped DynamoDB table deletion."
    fi
}

# --- Delete SNS Topic ---
delete_sns_topic() {
    if [[ -z "$SNS_TOPIC_ARN" || "$SNS_TOPIC_ARN" == "null" ]]; then
        log_warn "SNS topic ARN not in resources JSON."
        return 0
    fi

    log_info "Deleting SNS topic: $SNS_TOPIC_ARN"

    if ! aws sns get-topic-attributes --topic-arn "$SNS_TOPIC_ARN" --region "$AWS_REGION" &>/dev/null; then
        log_info "SNS topic does not exist."
        return 0
    fi

    # List subscriptions first
    SUBSCRIPTIONS=$(aws sns list-subscriptions-by-topic --topic-arn "$SNS_TOPIC_ARN" --region "$AWS_REGION" --query 'Subscriptions[].SubscriptionArn' --output text)
    if [[ -n "$SUBSCRIPTIONS" ]]; then
        log_warn "Topic has subscriptions: $SUBSCRIPTIONS"
        for sub in $SUBSCRIPTIONS; do
            if [[ "$sub" != "PendingConfirmation" ]] && confirm "Delete subscription $sub?"; then
                aws sns unsubscribe --subscription-arn "$sub" --region "$AWS_REGION" --no-cli-pager
                log_success "Unsubscribed: $sub"
            fi
        done
    fi

    if confirm "Delete SNS topic $SNS_TOPIC_ARN?"; then
        aws sns delete-topic --topic-arn "$SNS_TOPIC_ARN" --region "$AWS_REGION" --no-cli-pager
        log_success "SNS topic deleted: $SNS_TOPIC_ARN"
    else
        log_warn "Skipped SNS topic deletion."
    fi
}

# --- Main ---
main() {
    echo ""
    echo "=========================================="
    echo "   H1 AWS SYNC STACK DESTRUCTION (M4.4)"
    echo "=========================================="
    echo ""
    log_warn "This script will PERMANENTLY DELETE AWS resources."
    log_warn "Account: $ACCOUNT_ID, Region: $AWS_REGION"
    echo ""

    if ! confirm "Are you sure you want to proceed with destruction?"; then
        log_info "Aborted by user."
        exit 0
    fi

    check_prerequisites
    load_resource_arns

    # Order: Lambda -> IAM Role -> S3 -> DynamoDB -> SNS
    # (Lambda depends on role, so delete Lambda first)
    delete_lambda
    delete_iam_role
    delete_s3_bucket
    delete_dynamodb_table
    delete_sns_topic

    echo ""
    echo "=========================================="
    log_success "DESTRUCTION COMPLETE"
    echo "=========================================="
    echo ""
    log_info "Note: The resources JSON at $RESOURCES_JSON still contains the old ARNs."
    log_info "You may want to delete or archive it: rm $RESOURCES_JSON"
}

main "$@"