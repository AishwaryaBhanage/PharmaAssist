"""The ingestion worker: a separate process that consumes the ingestion queue (the Fargate service's
entrypoint; also runs on a laptop against ElasticMQ, the SQLite queue or a local folder).

Run (from the repository root):
  python scripts/ingest_worker.py                 # long-running consumer; SIGTERM finishes the current job
  python scripts/ingest_worker.py --once          # one receive, then exit (cron-style)
  python scripts/ingest_worker.py --max-jobs 3    # exit after three jobs

Environment (config.yaml's *_env keys; .env is loaded, then SSM when SSM_PARAMETER_PREFIX is set):
  DATABASE_URL                 PostgreSQL (pharmassist.store.pg)
  PHARMASSIST_BUCKET           source files, figure crops, parse cache (S3_ENDPOINT_URL for MinIO)
  INGEST_QUEUE_URL, INGEST_DLQ_URL   with queue.backend: sqs (SQS_ENDPOINT_URL for ElasticMQ)
  OPENAI_API_KEY               embeddings; ANTHROPIC_API_KEY for figure vision
Exit status is non-zero only for a configuration error; job failures are recorded on the job.
"""

import argparse
import logging
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))   # app/ (runtime_env) isn't on the path when run as a script

log = logging.getLogger("pharmassist.ingest.main")


class ConfigError(RuntimeError):
    pass


def build_store(cfg: dict, kind: str):
    """Stream A's PostgreSQL store from DATABASE_URL; `memory` is stream A's MemoryStore (smoke tests)."""
    if kind == "memory":
        from pharmassist.store.memory import MemoryStore
        return MemoryStore()
    from pharmassist.store import open_store
    dsn = os.environ.get(cfg["database"]["url_env"])
    if not dsn:
        raise ConfigError(f"set {cfg['database']['url_env']}")
    return open_store(dsn)


def build_embed(cfg: dict):
    """Stream B's router (`router_from_config(cfg).embed`) when present, else the OpenAI embedder."""
    try:
        from pharmassist.llm.router import router_from_config
        return router_from_config(cfg).embed   # `embed(texts) -> list[list[float]]`
    except ImportError:
        from pharmassist.ingest.pipeline import default_embed_fn
        return default_embed_fn(cfg)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--once", action="store_true", help="one receive, then exit")
    ap.add_argument("--max-jobs", type=int, default=None, help="exit after this many jobs")
    ap.add_argument("--store", choices=["pg", "memory"], default="pg")
    ap.add_argument("--log-level", default=os.environ.get("LOG_LEVEL", "INFO"))
    args = ap.parse_args()
    logging.basicConfig(level=args.log_level.upper(),
                        format="%(asctime)s %(levelname)s %(name)s %(message)s", stream=sys.stdout)
    logging.getLogger("botocore").setLevel(logging.WARNING)

    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
    from app.runtime_env import load_ssm_secrets
    load_ssm_secrets()   # in the Fargate task, keys come from SSM; locally a no-op

    from pharmassist.config import load_config
    from pharmassist.ingest.queue import QueueConfigError, queue_from_config
    from pharmassist.ingest.storage import StorageConfigError, storage_from_config
    from pharmassist.ingest.worker import run_forever
    cfg = load_config()
    try:
        queue = queue_from_config(cfg)
        storage = storage_from_config(cfg)
        store = build_store(cfg, args.store)
        embed = build_embed(cfg)
    except (QueueConfigError, StorageConfigError, ConfigError, ImportError) as e:
        log.error("configuration error: %s", e)
        return 2
    if not store.ping():
        log.error("configuration error: the database doesn't answer")
        return 2
    try:
        run_forever(store, queue, embed_fn=embed, cfg=cfg, once=args.once, max_jobs=args.max_jobs, storage=storage)
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
