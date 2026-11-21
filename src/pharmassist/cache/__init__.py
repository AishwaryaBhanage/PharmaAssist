"""Semantic answer cache (v2): a question whose embedding is within `cache.threshold` cosine
similarity of a stored question gets that stored answer and citations back. Stream D implements
`valkey.py` (Valkey/Redis vector search) and `memory.py` (tests); `open_cache()` picks from config."""

from pharmassist.cache.base import CacheEntry, CacheHit, SemanticCache  # noqa: F401


def open_cache(cfg: dict | None = None) -> "SemanticCache":
    """The configured cache (config.yaml `cache:`; REDIS_URL from the environment). A disabled cache
    returns `pharmassist.cache.base.NullCache`, which never hits."""
    from pharmassist.cache.factory import open_cache as _open
    return _open(cfg)
