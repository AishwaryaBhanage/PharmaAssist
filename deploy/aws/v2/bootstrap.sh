#!/usr/bin/env bash
# Apply (or update) the pharmassist-bootstrap IAM stack: the deploy role and its permissions for the
# v2 stack. Needs an admin profile (the deploy role cannot grant itself permissions):
#   AWS_PROFILE=default deploy/aws/v2/bootstrap.sh
# Idempotent: --no-fail-on-empty-changeset makes a no-op update succeed.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
REGION=${AWS_REGION:-us-east-1}
aws cloudformation deploy --region "$REGION" --stack-name pharmassist-bootstrap \
  --template-file "$HERE/../bootstrap.yaml" --capabilities CAPABILITY_NAMED_IAM \
  --tags Project=pharmassist --no-fail-on-empty-changeset
aws cloudformation describe-stacks --region "$REGION" --stack-name pharmassist-bootstrap \
  --query 'Stacks[0].[StackStatus,LastUpdatedTime]' --output text

# Service-linked roles the v2 stack's services need. Each service creates its own on first use, but a
# resource created in the same call can fail on IAM propagation ("Unable to assume IAM role"), so they
# are created here ahead of the stack. Idempotent: an existing role is reported and skipped.
for svc in ecs.amazonaws.com ecs.application-autoscaling.amazonaws.com autoscaling.amazonaws.com \
           elasticache.amazonaws.com rds.amazonaws.com elasticloadbalancing.amazonaws.com; do
  if out=$(aws iam create-service-linked-role --aws-service-name "$svc" --query Role.RoleName --output text 2>&1); then
    echo "service-linked role created for $svc: $out"
  elif echo "$out" | grep -q "has been taken"; then
    echo "service-linked role for $svc already exists"
  else
    echo "WARNING: could not create the service-linked role for $svc: $out" >&2
  fi
done
