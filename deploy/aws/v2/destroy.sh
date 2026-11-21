#!/usr/bin/env bash
# Delete the v2 stack and everything it created (load balancers, Elastic IPs, instances, RDS with a final
# snapshot, ElastiCache, queues, cluster, roles, secrets). Run from the repository root:
#   deploy/aws/v2/destroy.sh
# Kept on purpose: the S3 bucket (v1's, holds the documents), the ECR repositories and their images,
# the RDS final snapshot (named by CloudFormation; delete it in the console when no longer needed)
# and the v1 stack. The deleted secrets are purged immediately so their names can be reused by a redeploy.
set -euo pipefail
. "$(dirname "$0")/common.sh"

ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
STATUS=$(stack_status)
[ "$STATUS" != NONE ] || { echo "stack $STACK does not exist in $REGION"; exit 0; }
echo "This deletes stack $STACK ($STATUS) in account $ACCOUNT / $REGION, including the database (a final snapshot is kept)."
printf 'Type the stack name to confirm: '
read -r answer
[ "$answer" = "$STACK" ] || { echo "aborted"; exit 1; }

# a running worker would block service deletion; CloudFormation only deletes a service at 0 tasks
CLUSTER=$(out Cluster 2>/dev/null || true); SERVICE=$(out WorkerService 2>/dev/null || true)
if [ -n "$CLUSTER" ] && [ -n "$SERVICE" ] && [ "$CLUSTER" != None ]; then
  aws ecs update-service --region "$REGION" --cluster "$CLUSTER" --service "$SERVICE" --desired-count 0 >/dev/null 2>&1 || true
fi

aws cloudformation delete-stack --region "$REGION" --stack-name "$STACK" \
  --role-arn "arn:aws:iam::${ACCOUNT}:role/${APP}-cfn-exec"
echo "deleting ... (RDS takes ~10 min; the final snapshot is written first)"
aws cloudformation wait stack-delete-complete --region "$REGION" --stack-name "$STACK" || {
  echo "deletion did not finish cleanly; see the stack events, fix the blocker and rerun" >&2
  aws cloudformation describe-stack-events --region "$REGION" --stack-name "$STACK" \
    --query "StackEvents[?ResourceStatus=='DELETE_FAILED'].[LogicalResourceId,ResourceStatusReason]" --output text | head -20
  exit 1
}
echo "stack deleted"

# Secrets Manager keeps deleted secrets for 30 days and refuses to reuse the name; purge ours now
for name in "${APP}/v2/jwt" "${APP}/v2/app-keys" "${APP}/v2/cache-auth"; do
  aws secretsmanager delete-secret --region "$REGION" --secret-id "$name" --force-delete-without-recovery >/dev/null 2>&1 \
    && echo "purged secret $name" || true
done

# Elastic IPs are released with the NLB; release any that the project tag still shows as unattached
for alloc in $(aws ec2 describe-addresses --region "$REGION" --filters Name=tag:Project,Values="$APP" \
    --query 'Addresses[?AssociationId==null].AllocationId' --output text); do
  aws ec2 release-address --region "$REGION" --allocation-id "$alloc" && echo "released $alloc"
done
echo "done. Still present: bucket ${APP}-docs-${ACCOUNT}, ECR repos ${APP}-v2-web/${APP}-v2-ingest, the RDS final snapshot, the v1 stack."
