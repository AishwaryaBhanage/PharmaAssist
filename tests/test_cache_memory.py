"""MemoryCache: the contract in cache/base.py, checked without a server. These scenarios are rerun
against Valkey in test_cache_valkey.py."""

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from pharmassist.cache.memory import MemoryCache
from test_cache_support import DIM, at_cosine, entry, unit


@pytest.fixture
def rng():
    return np.random.default_rng(42)


@pytest.fixture
def cache():
    return MemoryCache(threshold=0.90, max_entries=20000, ttl_days=30)


def test_exact_question_hits_with_citations_verbatim(cache, rng):
    base = unit(rng)
    e = entry("Max dose of tramadol?", generation=3, assumption="adult", conflicts=["NY vs VA"])
    cache.put(e, base)
    hit = cache.lookup(base, 3)
    assert hit is not None and hit.similarity == pytest.approx(1.0)
    assert hit.entry.id == e.id and hit.entry.citations == e.citations
    assert hit.entry.assumption == "adult" and hit.entry.conflicts == ["NY vs VA"]
    assert hit.entry.hits == 1 and hit.entry.last_hit_at is not None


@pytest.mark.parametrize("cosine, expect_hit", [(0.89, False), (0.90, True), (0.91, True)])
def test_threshold_boundary(cache, rng, cosine, expect_hit):
    base = unit(rng)
    cache.put(entry(generation=1), base)
    hit = cache.lookup(at_cosine(base, cosine, rng), 1)
    assert (hit is not None) is expect_hit
    if hit:
        assert hit.similarity == pytest.approx(cosine, abs=1e-6)


def test_precision_nearest_neighbour_wins(cache, rng):
    """Two stored questions; the query sits at 0.91 of one and 0.89 of the other: only the first hits."""
    a, b = unit(rng), unit(rng)
    ea, eb = entry("A", 1), entry("B", 1)
    cache.put(ea, a)
    cache.put(eb, b)
    assert cache.lookup(at_cosine(a, 0.91, rng), 1).entry.id == ea.id
    assert cache.lookup(at_cosine(b, 0.89, rng), 1) is None


def test_generation_isolation(cache, rng):
    base = unit(rng)
    cache.put(entry(generation=1), base)
    assert cache.lookup(base, 2) is None, "an older generation's answer is never returned"
    assert cache.lookup(base, 1) is not None


def test_put_rejects_unanswered_or_uncited(cache, rng):
    v = unit(rng)
    with pytest.raises(ValueError):
        cache.put(entry(status="no_answer"), v)
    with pytest.raises(ValueError):
        cache.put(entry(citations=[]), v)
    with pytest.raises(ValueError):
        cache.put(entry(), np.zeros(DIM))
    assert cache.stats()["entries"] == 0


def test_eviction_drops_least_recently_hit(rng):
    now = datetime(2026, 10, 18, tzinfo=timezone.utc)
    clock = {"t": now}
    cache = MemoryCache(threshold=0.9, max_entries=3, ttl_days=30, clock=lambda: clock["t"])
    vecs = [unit(rng) for _ in range(4)]
    entries = [entry(f"q{i}", 1, created_at=now + timedelta(seconds=i)) for i in range(3)]
    for e, v in zip(entries, vecs):
        cache.put(e, v)
    clock["t"] = now + timedelta(minutes=1)
    cache.lookup(vecs[0], 1)                       # q0 is now the most recently hit; q1 the least
    cache.put(entry("q3", 1, created_at=clock["t"]), vecs[3])
    assert cache.get(entries[1].id) is None
    assert cache.get(entries[0].id) is not None and cache.get(entries[2].id) is not None
    assert cache.stats()["entries"] == 3


def test_ttl_expiry_with_fake_clock(rng):
    clock = {"t": datetime(2026, 10, 18, tzinfo=timezone.utc)}
    cache = MemoryCache(threshold=0.9, ttl_days=30, clock=lambda: clock["t"])
    v = unit(rng)
    e = entry(created_at=clock["t"])
    cache.put(e, v)
    clock["t"] += timedelta(days=29, hours=23)
    assert cache.lookup(v, 1) is not None
    clock["t"] += timedelta(hours=2)
    assert cache.lookup(v, 1) is None and cache.get(e.id) is None


def test_invalidate_by_generation_and_all(cache, rng):
    for g in (1, 1, 2, 3):
        cache.put(entry(generation=g), unit(rng))
    assert cache.invalidate(before_generation=2) == 2
    assert cache.stats()["entries"] == 2
    assert cache.invalidate() == 2
    assert cache.stats()["entries"] == 0


def test_get_delete_and_stats(cache, rng):
    v = unit(rng)
    e = entry(generation=5)
    cache.put(e, v)
    assert cache.get(e.id).question == e.question
    cache.lookup(v, 5)
    cache.lookup(unit(rng), 5)
    cache.lookup(v, 6)
    s = cache.stats()
    assert s == {"entries": 1, "hits": 1, "misses": 2, "hit_rate": 0.3333, "threshold": 0.9, "generation": 6,
                 "backend": "memory", "cleared_at": None}
    assert cache.delete(e.id) is True and cache.delete(e.id) is False
    assert cache.get(e.id) is None and cache.ping() is True


def test_hit_returns_a_copy(cache, rng):
    v = unit(rng)
    e = entry()
    cache.put(e, v)
    cache.lookup(v, 1).entry.citations.append({"id": "tampered"})
    assert len(cache.lookup(v, 1).entry.citations) == 1
