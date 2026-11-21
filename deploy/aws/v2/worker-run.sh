#!/usr/bin/env bash
# Run one ingestion worker task by hand (outside the queue-driven service) and wait for it. Run from
# the repository root:
#   deploy/aws/v2/worker-run.sh                  # drain the queue, then exit
#   deploy/aws/v2/worker-run.sh --help           # any other scripts/ingest_worker.py arguments
# The queue-driven service (0-2 tasks from queue depth) keeps running independently; this is for
# debugging and for forcing a run without waiting for the scaling alarm.
set -euo pipefail
. "$(dirname "$0")/common.sh"

if [ $# -gt 0 ]; then ARGS=("$@"); else ARGS=(--drain); fi
run_task "$(out WorkerTaskDef)" ingest "$(out WorkerSecurityGroup)" "/ecs/${APP}-v2-ingest" \
  python scripts/ingest_worker.py "${ARGS[@]}"
