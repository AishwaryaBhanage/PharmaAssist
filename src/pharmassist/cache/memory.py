"""In-memory semantic cache: the ValkeyCache behaviour on numpy, for unit tests of other streams.

Same rules as base.py: nearest entry of the same generation at cosine >= threshold is a hit; only
answered, cited entries are stored; TTL and max_entries (least recently hit first) apply. A `clock`
callable can be injected so tests drive expiry without sleeping. Similarity is rounded to 4 decimals
before the threshold comparison, like the Valkey backend: the server computes cosine in float32 over
3072 dims (error ~1e-6..1e-5), so a 1e-4 grain is the finest boundary both implementations can agree on,
and 0.89995 vs 0.9000 is not a meaningful clinical distinction.
"""

from __future__ import annotations

import threading
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Callable, Sequence

import numpy as np

from pharmassist.cache.base import CacheEntry, CacheHit

SIMILARITY_DECIMALS = 4


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def validate_entry(entry: CacheEntry) -> None:
    """The contract's `put` preconditions, shared by every backend."""
    if entry.status != "answered":
        raise ValueError(f"only answered entries are cached (status={entry.status!r})")
    if not entry.citations:
        raise ValueError("an entry without citations is never cached")


def unit_vector(embedding: Sequence[float]) -> np.ndarray:
    v = np.asarray(embedding, dtype=np.float32).astype(np.float64)
    norm = np.linalg.norm(v)
    if v.ndim != 1 or v.size == 0 or norm == 0.0:
        raise ValueError("embedding must be a non-empty, non-zero vector")
    return v / norm


class MemoryCache:
    name = "memory"

    def __init__(self, *, threshold: float = 0.90, max_entries: int = 20000, ttl_days: float = 30,
                 clock: Callable[[], datetime] | None = None):
        self.threshold = float(threshold)
        self.max_entries = int(max_entries)
        self.ttl = timedelta(days=float(ttl_days))
        self._clock = clock or utcnow
        self._entries: dict[str, CacheEntry] = {}
        self._vectors: dict[str, np.ndarray] = {}
        self._hits = 0
        self._misses = 0
        self._generation: int | None = None
        self._lock = threading.RLock()

    # ------------------------------------------------------------ contract

    def lookup(self, embedding, generation):
        q = unit_vector(embedding)
        with self._lock:
            self._generation = generation
            self._purge_expired()
            ids = [i for i, e in self._entries.items() if e.generation == generation]
            if not ids:
                self._misses += 1
                return None
            matrix = np.stack([self._vectors[i] for i in ids])
            sims = matrix @ q
            best = int(np.argmax(sims))
            similarity = min(1.0, round(float(sims[best]), SIMILARITY_DECIMALS))
            if similarity < self.threshold:
                self._misses += 1
                return None
            entry = self._entries[ids[best]]
            entry.hits += 1
            entry.last_hit_at = self._clock()
            self._hits += 1
            return CacheHit(entry=replace(entry, citations=list(entry.citations), conflicts=list(entry.conflicts)),
                            similarity=similarity)

    def put(self, entry, embedding):
        validate_entry(entry)
        v = unit_vector(embedding)
        with self._lock:
            self._generation = entry.generation
            stored = replace(entry, citations=list(entry.citations), conflicts=list(entry.conflicts))
            if stored.created_at is None:
                stored.created_at = self._clock()
            self._entries[stored.id] = stored
            self._vectors[stored.id] = v
            self._purge_expired()
            self._evict()
            return stored.id

    def get(self, entry_id):
        with self._lock:
            self._purge_expired()
            e = self._entries.get(entry_id)
            return replace(e, citations=list(e.citations), conflicts=list(e.conflicts)) if e else None

    def delete(self, entry_id):
        with self._lock:
            if entry_id not in self._entries:
                return False
            del self._entries[entry_id]
            del self._vectors[entry_id]
            return True

    def invalidate(self, *, before_generation=None):
        with self._lock:
            doomed = [i for i, e in self._entries.items()
                      if before_generation is None or e.generation < before_generation]
            for i in doomed:
                del self._entries[i]
                del self._vectors[i]
            return len(doomed)

    def stats(self):
        with self._lock:
            self._purge_expired()
            total = self._hits + self._misses
            return {"entries": len(self._entries), "hits": self._hits, "misses": self._misses,
                    "hit_rate": round(self._hits / total, 4) if total else 0.0, "threshold": self.threshold,
                    "generation": self._generation, "backend": self.name,
                    "cleared_at": getattr(self, "_cleared_at", None)}

    def reset_stats(self):
        import datetime as _dt
        with self._lock:
            self._hits = 0
            self._misses = 0
            self._cleared_at = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")

    def ping(self):
        return True

    # ------------------------------------------------------------ housekeeping

    def _purge_expired(self):
        cutoff = self._clock() - self.ttl
        for i in [i for i, e in self._entries.items() if e.created_at <= cutoff]:
            del self._entries[i]
            del self._vectors[i]

    def _evict(self):
        """Drop least recently hit entries (never-hit entries rank by creation time) past max_entries."""
        excess = len(self._entries) - self.max_entries
        if excess <= 0:
            return
        by_recency = sorted(self._entries.values(), key=lambda e: e.last_hit_at or e.created_at)
        for e in by_recency[:excess]:
            del self._entries[e.id]
            del self._vectors[e.id]
