#!/usr/bin/env bash
# Load the v1 build (catalog and source files for the version ids, parent sections, chunks with their vectors, formulary/PDL table rows and
# figure records) into the v2 database with scripts/migrate_v1_to_pg.py, as a one-off Fargate task on
# the API image. The database is private, so the files travel through the documents bucket
# (migration/v1_build.tgz), which the migration task role may read. No embedding or vision spend.
# Run from the repository root after deploy.sh:
#   deploy/aws/v2/load-v1-data.sh                 # pack + upload + run (idempotent: active versions are skipped)
#   SKIP_PACK=1 deploy/aws/v2/load-v1-data.sh     # reuse the tarball already in the bucket
#   deploy/aws/v2/load-v1-data.sh --dry-run       # extra arguments go to migrate_v1_to_pg.py
set -euo pipefail
. "$(dirname "$0")/common.sh"
[ -f scripts/migrate_v1_to_pg.py ] || { echo "run from the repository root" >&2; exit 1; }

ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
BUCKET=${BUCKET:-${APP}-docs-${ACCOUNT}}
KEY=migration/v1_build.tgz

if [ "${SKIP_PACK:-0}" != 1 ]; then
  TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
  tar czf "$TMP/v1_build.tgz" docs \
    index/docling_sections/chunks.jsonl index/docling_sections/parents.jsonl \
    index/docling_sections/vectors.npy index/docling_sections/manifest.json \
    index/tables/va_formulary_cells.json index/tables/ny_pdl_rows.jsonl \
    storage/figures/records.json scripts/migrate_v1_to_pg.py
  echo "uploading $(du -h "$TMP/v1_build.tgz" | cut -f1) to s3://$BUCKET/$KEY" >&2
  aws s3 cp "$TMP/v1_build.tgz" "s3://$BUCKET/$KEY" --region "$REGION" --only-show-errors
fi

# The task's entrypoint composes DATABASE_URL from the RDS secret, then runs this: fetch and unpack the
# tarball, run the loader (extra arguments pass through). Single quotes only: the command travels as JSON.
CODE="import boto3, io, os, subprocess, sys, tarfile; b = boto3.client('s3', region_name='$REGION').get_object(Bucket='$BUCKET', Key='$KEY')['Body'].read(); tarfile.open(fileobj=io.BytesIO(b), mode='r:gz').extractall('/tmp/v1'); sys.exit(subprocess.call([sys.executable, 'scripts/migrate_v1_to_pg.py', '--source-root', '/tmp/v1', *sys.argv[1:]], cwd='/tmp/v1', env={**os.environ, 'PYTHONPATH': '/app/src'}))"
run_task "$(out MigrationTaskDef)" migrate "$(out MigrateSecurityGroup)" "/ecs/${APP}-v2-migrate" python -c "$CODE" "$@"
