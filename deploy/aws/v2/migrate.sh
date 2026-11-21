#!/usr/bin/env bash
# Run the database migration as a one-off Fargate task with the API image and wait for it. Run from
# the repository root (deploy.sh calls it after every stack update):
#   deploy/aws/v2/migrate.sh                 # alembic upgrade head
#   deploy/aws/v2/migrate.sh downgrade -1    # any other alembic arguments
set -euo pipefail
. "$(dirname "$0")/common.sh"

if [ $# -gt 0 ]; then
  run_task "$(out MigrationTaskDef)" migrate "$(out MigrateSecurityGroup)" "/ecs/${APP}-v2-migrate" \
    python -m alembic -c db/alembic.ini "$@"
else
  run_task "$(out MigrationTaskDef)" migrate "$(out MigrateSecurityGroup)" "/ecs/${APP}-v2-migrate"
fi
