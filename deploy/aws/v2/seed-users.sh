#!/usr/bin/env bash
# Create the seed accounts (1 admin + 3 staff) with scripts/seed_users.py as a one-off Fargate task and
# show its output once. Run from the repository root:
#   deploy/aws/v2/seed-users.sh [extra seed_users.py arguments]
# The script prints the generated passwords exactly once. Because a Fargate task can only speak through
# CloudWatch Logs, the log stream that carried them is deleted right after it is shown here; copy the
# passwords from this terminal.
set -euo pipefail
. "$(dirname "$0")/common.sh"

GROUP="/ecs/${APP}-v2-migrate"
LAST_TASK_STREAM=""
status=0
run_task "$(out MigrationTaskDef)" migrate "$(out MigrateSecurityGroup)" "$GROUP" python scripts/seed_users.py "$@" || status=$?
if [ -n "$LAST_TASK_STREAM" ]; then
  aws logs delete-log-stream --region "$REGION" --log-group-name "$GROUP" --log-stream-name "$LAST_TASK_STREAM" \
    && echo "(log stream $LAST_TASK_STREAM deleted: the passwords above exist only in this terminal now)" >&2 \
    || echo "WARNING: could not delete $GROUP/$LAST_TASK_STREAM; delete it by hand, it holds the passwords" >&2
fi
exit $status
