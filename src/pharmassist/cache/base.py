"""Semantic cache contract (v2).

Behaviour every implementation must have:
- `lookup` returns the single nearest entry with the same `generation` whose cosine similarity is
  >= threshold (config cache.threshold, 0.90), else None. Entries from older generations are never
  returned (the corpus changed) and are purged lazily.
- Only answered, cited answers are stored (the caller enforces this; `put` rejects status != answered).
- The cache is global (not per user): answers don't depend on who asks.
- Each hit increments `hits` on the entry and the global counters; `stats()` reports them.
- Entries expire after cache.ttl_days; `max_entries` evicts the least recently hit first.
- No implementation logs question or answer text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, Sequence


@dataclass
class CacheEntry:
    id: str                              # uuid4 hex, assigned by `put`
    question: str                        # the normalized question that produced the answer (shown on a hit)
    answer: str
    status: str                          # always "answered"
    citations: list[dict]                # CitationOut dicts, returned verbatim on a hit
    generation: int                      # index_state.generation at answer time
    created_at: datetime
    assumption: str | None = None
    conflicts: list[str] = field(default_factory=list)
    source_message_id: str | None = None # the message that produced it
    model: str | None = None
    provider: str | None = None
    hits: int = 0
    last_hit_at: datetime | None = None


@dataclass
class CacheHit:
    entry: CacheEntry
    similarity: float                    # cosine, 0..1


class SemanticCache(Protocol):
    name: str

    def lookup(self, embedding: Sequence[float], generation: int) -> CacheHit | None: ...

    def put(self, entry: CacheEntry, embedding: Sequence[float]) -> str:
        """Stores and returns the entry id. Raises ValueError for status != 'answered' or no citations."""

    def get(self, entry_id: str) -> CacheEntry | None: ...

    def delete(self, entry_id: str) -> bool: ...

    def invalidate(self, *, before_generation: int | None = None) -> int:
        """Removes entries older than `before_generation` (all entries when None). Returns the count."""

    def stats(self) -> dict:
        """{"entries": n, "hits": n, "misses": n, "hit_rate": f, "threshold": f, "generation": n|None,
        "backend": name, "cleared_at": iso|None}; hits and misses count since the last reset_stats()."""

    def reset_stats(self) -> None:
        """Zero the hit/miss counters and stamp cleared_at (the admin's Clear cache does this after
        invalidate(), so the hit rate shown is the rate since the clear)."""

    def ping(self) -> bool: ...


def normalize_question(text: str) -> str:
    """The text that is embedded for cache lookups and storage: trimmed, single-spaced, lower-cased
    first letter preserved otherwise (embeddings are case-tolerant; this only removes noise)."""
    return " ".join(text.strip().split())


class NullCache:
    """A cache that is switched off: every lookup misses, puts are dropped."""
    name = "null"

    def lookup(self, embedding, generation):
        return None

    def put(self, entry, embedding):
        return entry.id

    def get(self, entry_id):
        return None

    def delete(self, entry_id):
        return False

    def invalidate(self, *, before_generation=None):
        return 0

    def stats(self):
        return {"entries": 0, "hits": 0, "misses": 0, "hit_rate": 0.0, "threshold": None, "generation": None,
                "backend": self.name, "cleared_at": None}

    def reset_stats(self):
        return None

    def ping(self):
        return True
