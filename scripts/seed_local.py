"""Everything the local docker-compose stack needs to answer questions, in one idempotent step:

  1. the 11 source files (docs/) into the local S3 bucket under sources/<doc_id>/<sha16>/<file>,
     where the API fetches them for `read_page` and the citation links;
  2. the figure crops (storage/figures/<doc_id>/*.png) under figures/<doc_id>/<name>;
  3. the v1 build (sections, chunks with their vectors, table rows, figure records) into PostgreSQL
     with scripts/migrate_v1_to_pg.py (no embedding or vision spend; already-active versions are skipped);
  4. the demo accounts: admin@pharmassist.local and staff1..3@pharmassist.local with the passwords in
     DEMO_ADMIN_PASSWORD / DEMO_STAFF_PASSWORD (defaults below; the API refuses passwords under 10 chars).

Run by the `seed` service in deploy/docker-compose.yml with the repository mounted at /src:
    python /src/scripts/seed_local.py --source-root /src
or from the host .venv against the compose services (see the compose file header for the env values):
    PYTHONPATH=src .venv/bin/python scripts/seed_local.py
Needs DATABASE_URL, S3_ENDPOINT_URL, PHARMASSIST_BUCKET and the AWS_* dummies in the environment.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))                       # migrate_v1_to_pg, seed_users
sys.path.insert(0, str(HERE.parent / "src"))        # pharmassist, when not installed

DEFAULT_ADMIN_PASSWORD = "admin-password-1"
DEFAULT_STAFF_PASSWORD = "staff-password-1"
CONTENT_TYPES = {".pdf": "application/pdf", ".png": "image/png",
                 ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}


def upload_sources(root: Path, log=print) -> int:
    import yaml
    from pharmassist import cloud
    s3 = cloud._s3()
    n = 0
    for e in yaml.safe_load((root / "docs" / "catalog.yaml").read_text())["documents"]:
        path = root / "docs" / e["file"]
        if not path.exists():
            raise SystemExit(f"missing source file {path} (the corpus must be in docs/)")
        key = cloud.source_key(e["id"], cloud.sha16(path), e["file"])
        if cloud.exists(key, s3=s3):
            continue
        cloud.put_file(path, key, s3=s3, content_type=CONTENT_TYPES.get(path.suffix.lower()))
        n += 1
    log(f"sources: {n} uploaded")
    return n


def upload_figures(root: Path, log=print) -> int:
    from pharmassist import cloud
    s3 = cloud._s3()
    n = 0
    figures = root / "storage" / "figures"
    for png in sorted(figures.glob("*/*.png")):
        if png.parent.name.startswith("e2e_"):          # test fixtures, not corpus documents
            continue
        key = cloud.figure_key(png.parent.name, png.name)
        if cloud.exists(key, s3=s3):
            continue
        cloud.put_file(png, key, s3=s3, content_type="image/png")
        n += 1
    log(f"figure crops: {n} uploaded")
    return n


def wait_for_bucket(attempts: int = 30, log=print) -> None:
    """The bucket is created by the `createbuckets` service; give it a moment on a cold start."""
    from pharmassist import cloud
    for i in range(attempts):
        try:
            cloud.list_keys("sources/")
            return
        except Exception as e:                        # noqa: BLE001 - any S3 error: not ready yet
            if i == attempts - 1:
                raise SystemExit(f"bucket {cloud.bucket()} not reachable: {type(e).__name__}") from e
            time.sleep(2)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--source-root", type=Path, default=HERE.parent, help="the project root (docs/, index/, storage/)")
    ap.add_argument("--dsn", default=None, help="PostgreSQL DSN (default: DATABASE_URL)")
    ap.add_argument("--skip-upload", action="store_true", help="only the database (sources already in the bucket)")
    a = ap.parse_args(argv)
    root = a.source_root.resolve()

    if not a.skip_upload:
        wait_for_bucket()
        upload_sources(root)
        upload_figures(root)

    from migrate_v1_to_pg import migrate
    from seed_users import seed
    from pharmassist.store.pg import PgStore

    store = PgStore.connect(a.dsn or os.environ.get("DATABASE_URL"))
    try:
        store.migrate()
        migrate(store, root)
        admin_pw = os.environ.get("DEMO_ADMIN_PASSWORD") or DEFAULT_ADMIN_PASSWORD
        staff_pw = os.environ.get("DEMO_STAFF_PASSWORD") or DEFAULT_STAFF_PASSWORD
        passwords = {"admin@pharmassist.local": admin_pw,
                     **{f"staff{i}@pharmassist.local": staff_pw for i in (1, 2, 3)}}
        results = seed(store, passwords)
    finally:
        store.close()
    print("Demo accounts (local only):")
    for email, outcome, password in results:
        print(f"  {email:<32} {outcome:<8} {password or '(unchanged)'}")
    print("ready: http://localhost:8000")
    return 0


if __name__ == "__main__":
    sys.exit(main())
