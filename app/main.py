"""The production entry point: `uvicorn app.main:app`. Builds the real dependencies from config.yaml
and the environment, then hands them to `create_app`.

Environment (secrets never logged; SSM_PARAMETER_PREFIX loads them from SSM first):
  DATABASE_URL         PostgreSQL DSN (config database.url_env)          -> pharmassist.store.open_store
  REDIS_URL            Valkey/Redis URL (cache.url_env)                   -> semantic cache + usage counters
  PHARMASSIST_BUCKET   S3 bucket for sources, figures, uploads; S3_ENDPOINT_URL for MinIO
  JWT_SECRET           256-bit random (auth.jwt_secret_env)
  INGEST_QUEUE_URL     SQS queue for uploads (queue.queue_url_env); unset -> submit_upload gets queue=None
  RATE_LIMIT_SALT      salt for the hashed user ids in the limiter's keys (default: derived from JWT_SECRET)
  APP_CORS_ORIGINS     comma-separated dev origins (http://localhost:5173); APP_INSECURE_COOKIES=1 for http
Without REDIS_URL the limiter is in-memory and the cache is whatever `open_cache` returns for the
config (NullCache when disabled). Nothing heavy is loaded here; the reranker (config.yaml
search.rerank) is warmed by the app's startup only when APP_WARM_MODELS=1, as in the Docker image.
"""

from __future__ import annotations

import hashlib
import logging
import os

from dotenv import load_dotenv

from app.answer_service import AnswerService
from app.deps import Deps, LocalStorage, S3Storage
from app.limits import Limits, MemoryGuard, RedisGuard
from app.runtime_env import load_ssm_secrets
from app.server import create_app
from pharmassist.config import PROJECT_ROOT, load_config

log = logging.getLogger("pharmassist.app")


def build_deps() -> Deps:
    load_dotenv(PROJECT_ROOT / ".env")
    try:
        load_ssm_secrets()
    except Exception as e:
        log.error("loading secrets failed: %s", type(e).__name__)
    cfg = load_config()
    secret = os.environ.get((cfg.get("auth") or {}).get("jwt_secret_env", "JWT_SECRET")) or ""
    if len(secret) < 32:
        raise RuntimeError("JWT_SECRET must be set to at least 32 random characters")

    from pharmassist.store import open_store
    store = open_store(os.environ.get((cfg.get("database") or {}).get("url_env", "DATABASE_URL")))

    from pharmassist.cache import open_cache
    cache = open_cache(cfg)

    limits = Limits.from_config(cfg.get("limits_v2"))
    salt = os.environ.get("RATE_LIMIT_SALT") or hashlib.sha256(secret.encode()).hexdigest()[:16]
    redis_url = os.environ.get((cfg.get("cache") or {}).get("url_env", "REDIS_URL"))
    if redis_url:
        import redis
        limiter = RedisGuard(redis.Redis.from_url(redis_url, socket_timeout=2, socket_connect_timeout=2,
                                                  decode_responses=True), limits, salt)
    else:
        log.warning("REDIS_URL is not set: usage limits are per process")
        limiter = MemoryGuard(limits, salt)

    st = cfg.get("storage") or {}
    bucket = os.environ.get(st.get("bucket_env", "PHARMASSIST_BUCKET"))
    storage = (S3Storage(bucket, os.environ.get(st.get("endpoint_env", "S3_ENDPOINT_URL")) or None,
                         int(st.get("presign_seconds", 600))) if bucket else LocalStorage())

    queue = None
    queue_url = os.environ.get((cfg.get("queue") or {}).get("queue_url_env", "INGEST_QUEUE_URL"))
    if queue_url:
        try:
            from pharmassist.ingest.queue import open_queue
            queue = open_queue(cfg)
        except Exception as e:   # the API still answers; uploads report the failure when they try to enqueue
            log.error("ingestion queue unavailable: %s", type(e).__name__)

    answers = AnswerService(cfg, store=store, storage=storage)
    return Deps(cfg=cfg, store=store, cache=cache, answers=answers, limiter=limiter, storage=storage,
                jwt_secret=secret, queue=queue, version=os.environ.get("APP_VERSION"))


app = create_app(build_deps())
