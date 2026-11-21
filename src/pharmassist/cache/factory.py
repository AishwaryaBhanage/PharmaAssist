"""Builds the configured semantic cache from config.yaml's `cache:` block.

`open_cache` never raises because of the cache server: a Valkey that is down (or a REDIS_URL that
is not set) still yields a `ValkeyCache`, which logs once and misses until the server is reachable,
so /health/ready can report `cache: false` instead of the API failing to start.
"""

from __future__ import annotations

import logging
import os

from pharmassist.cache.base import NullCache, SemanticCache

log = logging.getLogger("pharmassist.cache")


def _cache_block(cfg: dict | None) -> dict:
    if cfg is None:
        from pharmassist.config import load_config
        cfg = load_config()
    return dict(cfg.get("cache", cfg) or {})


def _load_dotenv_once() -> None:
    try:
        from dotenv import load_dotenv
        from pharmassist.config import PROJECT_ROOT
        load_dotenv(PROJECT_ROOT / ".env")
    except ImportError:
        pass


def open_cache(cfg: dict | None = None) -> SemanticCache:
    """`cfg` is the whole config dict (or just its `cache` block); None loads config.yaml."""
    c = _cache_block(cfg)
    backend = (c.get("backend") or "null")
    if not c.get("enabled", True) or backend in (None, "null", "none", "off"):
        return NullCache()
    common = {"threshold": c.get("threshold", 0.90), "max_entries": c.get("max_entries", 20000),
              "ttl_days": c.get("ttl_days", 30)}
    if backend == "memory":
        from pharmassist.cache.memory import MemoryCache
        return MemoryCache(**common)
    if backend == "valkey":
        from pharmassist.cache.valkey import DEFAULT_URL, ValkeyCache
        _load_dotenv_once()
        url_env = c.get("url_env", "REDIS_URL")
        url = os.environ.get(url_env)
        if not url:
            log.warning("%s is not set; semantic cache will try %s", url_env, DEFAULT_URL)
            url = DEFAULT_URL
        cache = ValkeyCache(url, index_name=c.get("index_name", "pa_answers"), dim=c.get("dim", 3072),
                            socket_timeout=min(float(c.get("socket_timeout_s", 1.0)), 1.0), **common)
        if not cache.ping():
            log.warning("semantic cache (valkey) unreachable at start-up; lookups miss until it is")
        return cache
    raise ValueError(f"unknown cache backend {backend!r} (valkey | memory | null)")
