"""Semantic cache on Valkey vector search (valkey-search module; ElastiCache for Valkey 8.2).

Layout (all keys share the prefix so a cluster hash tag could be added later):
    pa:ans:<id>      HASH  entry fields (citations/conflicts as JSON) + `embedding` (3072 float32 LE)
    pa:ans-lru       ZSET  id -> last_hit_at (or created_at) epoch seconds; drives max_entries eviction
    pa:ans-stats     HASH  hits, misses, generation (global counters shared by both app instances);
                     deliberately outside the `pa:ans:` prefix so the index never sees it
    <index_name>     FT index ON HASH PREFIX pa:ans: with `embedding` VECTOR HNSW COSINE, `generation`
                     NUMERIC. Only the two fields the lookup uses are indexed.

The lookup is one FT.SEARCH: `@generation:[g g]=>[KNN 1 @embedding $v AS score]`. valkey-search returns
the cosine *distance* (1 - cos), so similarity = 1 - score; a hit needs similarity >= threshold.
That query is the common subset of valkey-search and RediSearch (Redis Stack): no SORTBY (Valkey
rejects it; KNN results are already distance-ordered), no pure-filter queries (Valkey requires the
`=>` KNN clause), RESP2 pinned (RediSearch returns a different shape under RESP3).

Why there is a registry sorted set: valkey-search cannot list keys by a filter alone, and SCAN over
20k entries on every put would be wasteful; the ZSET gives O(log n) least-recently-hit eviction and a
bounded iteration for invalidate(). Keys that expired (TTL) leave the index automatically but stay
in the ZSET until the next eviction/invalidate pass notices the hash is gone.

Everything fails soft: a Valkey outage makes lookups miss, puts drop (the caller still gets the id)
and stats/ping report what they can; the API never waits longer than the socket timeout (1 s). The
first failure logs a warning (no question/answer content), later ones log at DEBUG until a call
succeeds again.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Sequence

import numpy as np

from pharmassist.cache.base import CacheEntry, CacheHit
from pharmassist.cache.memory import SIMILARITY_DECIMALS, utcnow, validate_entry

log = logging.getLogger("pharmassist.cache")

DEFAULT_URL = "redis://localhost:6379/0"
KEY_PREFIX = "pa:ans:"
EMBEDDING_FIELD = "embedding"
TEXT_FIELDS = ("id", "question", "answer", "status", "assumption", "source_message_id", "model", "provider")
JSON_FIELDS = ("citations", "conflicts")


def _redis_module():
    import redis  # imported lazily so the memory/null caches don't need redis installed
    return redis


def _epoch(dt: datetime | None) -> float:
    if dt is None:
        return time.time()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _from_epoch(s: bytes | str | None) -> datetime | None:
    return datetime.fromtimestamp(float(s), tz=timezone.utc) if s not in (None, b"", "") else None


def _to_float32_bytes(embedding: Sequence[float], dim: int) -> bytes:
    v = np.asarray(embedding, dtype=np.float32)
    if v.ndim != 1 or v.size != dim:
        raise ValueError(f"embedding must have {dim} dimensions, got shape {v.shape}")
    if not np.isfinite(v).all() or not np.any(v):
        raise ValueError("embedding must be finite and non-zero")
    return v.tobytes()   # little-endian float32, what FT.SEARCH's PARAMS expects


def entry_to_fields(entry: CacheEntry, embedding: bytes) -> dict:
    fields = {k: (getattr(entry, k) or "") for k in TEXT_FIELDS}
    fields.update({k: json.dumps(getattr(entry, k) or [], ensure_ascii=False) for k in JSON_FIELDS})
    fields.update({
        "generation": int(entry.generation),
        "created_at": repr(_epoch(entry.created_at)),
        "hits": int(entry.hits),
        "last_hit_at": repr(_epoch(entry.last_hit_at)) if entry.last_hit_at else "",
        EMBEDDING_FIELD: embedding,
    })
    return fields


def fields_to_entry(raw: dict) -> CacheEntry:
    def text(k):
        v = raw.get(k.encode())
        v = v.decode("utf-8") if isinstance(v, bytes) else v
        return v or None
    return CacheEntry(
        id=text("id") or "", question=text("question") or "", answer=text("answer") or "",
        status=text("status") or "", citations=json.loads(text("citations") or "[]"),
        generation=int(text("generation") or 0), created_at=_from_epoch(text("created_at")) or utcnow(),
        assumption=text("assumption"), conflicts=json.loads(text("conflicts") or "[]"),
        source_message_id=text("source_message_id"), model=text("model"), provider=text("provider"),
        hits=int(text("hits") or 0), last_hit_at=_from_epoch(text("last_hit_at")),
    )


class ValkeyCache:
    name = "valkey"

    def __init__(self, url: str | None = None, *, index_name: str = "pa_answers", threshold: float = 0.90,
                 max_entries: int = 20000, ttl_days: float = 30, dim: int = 3072, key_prefix: str = KEY_PREFIX,
                 socket_timeout: float = 1.0, client=None):
        self.url = url or DEFAULT_URL
        self.index_name = index_name
        self.threshold = float(threshold)
        self.max_entries = int(max_entries)
        self.ttl_seconds = int(float(ttl_days) * 86400)
        self.dim = int(dim)
        self.prefix = key_prefix
        # Bookkeeping keys live *outside* the index prefix: a HASH under it would be indexed as an entry.
        meta = key_prefix.rstrip(":")
        self.lru_key = f"{meta}-lru"
        self.stats_key = f"{meta}-stats"
        self._index_ready = False
        self._degraded = False
        self._lock = threading.Lock()
        redis = _redis_module()
        # RESP2 pinned: RediSearch returns maps under RESP3, valkey-search returns the flat list in both.
        self._r = client or redis.from_url(self.url, socket_timeout=socket_timeout,
                                            socket_connect_timeout=socket_timeout, protocol=2,
                                            decode_responses=False, health_check_interval=30)
        self._errors = (redis.exceptions.RedisError, OSError)

    # ------------------------------------------------------------ keys / index

    def key(self, entry_id: str) -> str:
        return f"{self.prefix}{entry_id}"

    def ensure_index(self) -> bool:
        """Creates the vector index once; an existing index (any engine's wording) is fine."""
        if self._index_ready:
            return True
        with self._lock:
            if self._index_ready:
                return True
            try:
                self._r.execute_command(
                    "FT.CREATE", self.index_name, "ON", "HASH", "PREFIX", "1", self.prefix, "SCHEMA",
                    EMBEDDING_FIELD, "VECTOR", "HNSW", "10", "TYPE", "FLOAT32", "DIM", str(self.dim),
                    "DISTANCE_METRIC", "COSINE", "M", "16", "EF_CONSTRUCTION", "200",
                    "generation", "NUMERIC")
            except self._errors as e:
                if "already exists" not in str(e).lower():
                    self._failed("index create", e)
                    return False
            self._index_ready = True
            self._degraded = False
            return True

    def drop_index(self) -> None:
        """Test helper: removes the index (not the keys)."""
        try:
            self._r.execute_command("FT.DROPINDEX", self.index_name)
        except self._errors:
            pass
        self._index_ready = False

    # ------------------------------------------------------------ contract

    def lookup(self, embedding, generation):
        try:
            vec = _to_float32_bytes(embedding, self.dim)
            if not self.ensure_index():
                return None
            found = self._knn(vec, generation)
            if found is None:
                return self._miss(generation)
            key, similarity = found
            if similarity < self.threshold:
                return self._miss(generation)
            raw = self._r.hgetall(key)
            if not raw:                       # expired between the search and the read
                return self._miss(generation)
            now = time.time()
            with self._r.pipeline(transaction=False) as p:
                p.hincrby(key, "hits", 1)
                p.hset(key, "last_hit_at", repr(now))
                p.zadd(self.lru_key, {raw[b"id"].decode(): now})
                p.hincrby(self.stats_key, "hits", 1)
                p.hset(self.stats_key, "generation", int(generation))
                p.execute()
            self._degraded = False
            entry = fields_to_entry(raw)
            entry.hits += 1
            entry.last_hit_at = datetime.fromtimestamp(now, tz=timezone.utc)
            return CacheHit(entry=entry, similarity=similarity)
        except self._errors as e:
            self._failed("lookup", e)
            return None

    def put(self, entry, embedding):
        validate_entry(entry)
        vec = _to_float32_bytes(embedding, self.dim)
        if not entry.id:
            entry.id = uuid.uuid4().hex
        if entry.created_at is None:
            entry.created_at = utcnow()
        try:
            self.ensure_index()
            fields = entry_to_fields(entry, vec)
            # Never MULTI/EXEC an indexed write: on valkey-search 1.0.x a hash written inside a transaction
            # makes the next DEL/EXPIRE of that key block the whole server (measured: >30 s, i.e. a hang).
            with self._r.pipeline(transaction=False) as p:
                p.hset(self.key(entry.id), mapping=fields)
                p.expire(self.key(entry.id), self.ttl_seconds)
                p.zadd(self.lru_key, {entry.id: _epoch(entry.last_hit_at or entry.created_at)})
                p.hset(self.stats_key, "generation", int(entry.generation))
                p.execute()
            self._evict()
            self._degraded = False
        except self._errors as e:
            self._failed("put", e)
        return entry.id

    def get(self, entry_id):
        try:
            raw = self._r.hgetall(self.key(entry_id))
            return fields_to_entry(raw) if raw else None
        except self._errors as e:
            self._failed("get", e)
            return None

    def delete(self, entry_id):
        try:
            with self._r.pipeline(transaction=False) as p:
                p.delete(self.key(entry_id))
                p.zrem(self.lru_key, entry_id)
                deleted, _ = p.execute()
            return bool(deleted)
        except self._errors as e:
            self._failed("delete", e)
            return False

    def invalidate(self, *, before_generation=None, batch: int = 500):
        """Walks the registry in batches, reading each entry's generation; a hash that is gone (TTL)
        is just dropped from the registry. Bounded by the registry size, not by the keyspace."""
        removed = 0
        try:
            cursor = 0
            while True:
                ids = [i.decode() for i in self._r.zrange(self.lru_key, cursor, cursor + batch - 1)]
                if not ids:
                    break
                with self._r.pipeline(transaction=False) as p:
                    for i in ids:
                        p.hget(self.key(i), "generation")
                    gens = p.execute()
                doomed, stale = [], []
                for i, g in zip(ids, gens):
                    if g is None:
                        stale.append(i)
                    elif before_generation is None or int(g) < before_generation:
                        doomed.append(i)
                if doomed or stale:
                    with self._r.pipeline(transaction=False) as p:
                        for i in doomed:
                            p.delete(self.key(i))
                        p.zrem(self.lru_key, *(doomed + stale))
                        p.execute()
                removed += len(doomed)
                cursor += len(ids) - len(doomed) - len(stale)    # removed members shift the range down
            self._degraded = False
        except self._errors as e:
            self._failed("invalidate", e)
        return removed

    def stats(self):
        out = {"entries": 0, "hits": 0, "misses": 0, "hit_rate": 0.0, "threshold": self.threshold,
               "generation": None, "backend": self.name, "cleared_at": None}
        try:
            counters = self._r.hgetall(self.stats_key)
            out["hits"] = int(counters.get(b"hits", 0))
            out["misses"] = int(counters.get(b"misses", 0))
            gen = counters.get(b"generation")
            out["generation"] = int(gen) if gen else None
            cleared = counters.get(b"cleared_at")
            out["cleared_at"] = cleared.decode() if cleared else None
            out["entries"] = self._count_entries()
            total = out["hits"] + out["misses"]
            out["hit_rate"] = round(out["hits"] / total, 4) if total else 0.0
            self._degraded = False
        except self._errors as e:
            self._failed("stats", e)
        return out

    def reset_stats(self):
        """Zero the shared hit/miss counters (both app instances read them) and stamp the clear time;
        the generation field stays."""
        import datetime as _dt
        try:
            self._r.hset(self.stats_key, mapping={"hits": 0, "misses": 0,
                                                  "cleared_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")})
        except self._errors as e:
            self._failed("reset_stats", e)

    def ping(self):
        try:
            return bool(self._r.ping())
        except self._errors as e:
            self._failed("ping", e)
            return False

    # ------------------------------------------------------------ internals

    def _knn(self, vec: bytes, generation: int) -> tuple[bytes, float] | None:
        query = f"@generation:[{int(generation)} {int(generation)}]=>[KNN 1 @{EMBEDDING_FIELD} $v AS score]"
        try:
            res = self._r.execute_command("FT.SEARCH", self.index_name, query, "PARAMS", "2", "v", vec,
                                          "RETURN", "1", "score", "DIALECT", "2", "TIMEOUT", "800")
        except _redis_module().exceptions.ResponseError as e:
            if "index" in str(e).lower():
                self._index_ready = False          # someone dropped it (e.g. a flush); recreate next time
            raise
        if not res or int(res[0]) == 0 or len(res) < 3:
            return None
        key, fields = res[1], res[2]
        pairs = dict(zip(fields[0::2], fields[1::2]))
        distance = float(pairs.get(b"score", b"1"))
        return key, min(1.0, round(1.0 - distance, SIMILARITY_DECIMALS))   # float32 drift can exceed 1

    def _miss(self, generation: int):
        with self._r.pipeline(transaction=False) as p:
            p.hincrby(self.stats_key, "misses", 1)
            p.hset(self.stats_key, "generation", int(generation))
            p.execute()
        self._degraded = False
        return None

    def _count_entries(self) -> int:
        """The registry size. FT.INFO's num_docs lags behind HSETs on valkey-search (observed 0 for
        hundreds of ms while KNN already found the key), so the ZSET is the count we control; it can
        overstate by entries that expired since the last eviction/invalidate pass."""
        return int(self._r.zcard(self.lru_key))

    def _evict(self, step: int = 100):
        """Least recently hit first: pop registry members with the oldest score until under the cap.
        A popped id whose hash already expired costs nothing but frees the registry slot."""
        while self._r.zcard(self.lru_key) > self.max_entries:
            popped = self._r.zpopmin(self.lru_key, min(step, self._r.zcard(self.lru_key) - self.max_entries))
            if not popped:
                break
            self._r.delete(*[self.key(i.decode()) for i, _ in popped])

    def _failed(self, op: str, exc: Exception) -> None:
        level = logging.DEBUG if self._degraded else logging.WARNING
        log.log(level, "semantic cache %s failed (%s); treating as a miss", op, type(exc).__name__)
        self._degraded = True
