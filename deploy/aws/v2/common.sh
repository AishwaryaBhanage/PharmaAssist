# Shared by deploy/aws/v2/*.sh (sourced, not run). Everything runs as the pharmassist-deployer role
# (AWS_PROFILE=pharmassist by default) against the pharmassist-v2 stack. bash 3.2 (macOS) compatible.

export AWS_PROFILE=${AWS_PROFILE:-pharmassist}
APP=${APP:-pharmassist}
STACK=${STACK:-${APP}-v2}
REGION=${AWS_REGION:-$(aws configure get region 2>/dev/null || echo us-east-1)}
export AWS_REGION=$REGION AWS_DEFAULT_REGION=$REGION

out() {  # stack output by key
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}

stack_status() {
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" \
    --query 'Stacks[0].StackStatus' --output text 2>/dev/null || echo NONE
}

# run_task TASKDEF CONTAINER SECURITY_GROUP LOG_GROUP [COMMAND...]
# Runs one Fargate task in the stack's subnets with a public IP (no NAT gateway), waits for it, prints
# its log stream and returns the container's exit code. COMMAND replaces the task definition's command;
# the entrypoint that composes DATABASE_URL stays. Sets LAST_TASK_STREAM for callers that clean up logs.
run_task() {
  local taskdef=$1 container=$2 sg=$3 group=$4; shift 4
  local overrides='{}' args task code reason i
  if [ $# -gt 0 ]; then
    # each argument JSON-encoded (backslashes and double quotes escaped)
    args=$(for a in "$@"; do printf '"%s",' "$(printf '%s' "$a" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g')"; done)
    overrides="{\"containerOverrides\":[{\"name\":\"$container\",\"command\":[${args%,}]}]}"
  fi
  task=$(aws ecs run-task --region "$REGION" --cluster "$(out Cluster)" --task-definition "$taskdef" \
    --launch-type FARGATE --platform-version LATEST \
    --network-configuration "awsvpcConfiguration={subnets=[$(out SubnetIds)],securityGroups=[$sg],assignPublicIp=ENABLED}" \
    --overrides "$overrides" --tags key=Project,value="$APP" \
    --query 'tasks[0].taskArn' --output text) || return 1
  [ -n "$task" ] && [ "$task" != "None" ] || { echo "run-task returned no task (capacity or permission problem?)" >&2; return 1; }
  echo "started $task" >&2
  for i in 1 2 3 4 5 6; do   # the waiter gives up after 10 min; long jobs need several rounds (max 60 min)
    aws ecs wait tasks-stopped --region "$REGION" --cluster "$(out Cluster)" --tasks "$task" && break
    [ "$i" = 6 ] && { echo "task still running after 60 min; stop it with: aws ecs stop-task --cluster $(out Cluster) --task $task" >&2; return 1; }
  done
  code=$(aws ecs describe-tasks --region "$REGION" --cluster "$(out Cluster)" --tasks "$task" \
    --query 'tasks[0].containers[0].exitCode' --output text)
  reason=$(aws ecs describe-tasks --region "$REGION" --cluster "$(out Cluster)" --tasks "$task" \
    --query 'tasks[0].stoppedReason' --output text)
  # awslogs stream name: <stream-prefix>/<container>/<task id>; the prefix is the container name in template.yaml
  LAST_TASK_STREAM="${container}/${container}/${task##*/}"
  echo "--- task output ($group / $LAST_TASK_STREAM)" >&2
  aws logs tail "$group" --region "$REGION" --log-stream-names "$LAST_TASK_STREAM" --since 3h --format short || true
  echo "--- stopped: exit $code ($reason)" >&2
  [ "$code" = "0" ]
}
