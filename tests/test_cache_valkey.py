"""ValkeyCache against a real server (docker). Skipped cleanly when nothing answers.

    docker run -d --name pa-valkey -p 6379:6379 valkey/valkey-bundle:8.1
    CACHE_TEST_REDIS_URLS=redis://localhost:6379/0 pytest -m integration tests/test_cache_valkey.py

Several URLs separated by commas run the suite against each (e.g. Valkey and Redis Stack). Each test
gets its own index and key prefix so parallel runs and leftovers don't interfere.
"""

import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

from pharmassist.cache.valkey import ValkeyCache
from test_cache_support import DIM, at_cosine, entry, unit

pytestmark = pytest.mark.integration

URLS = [u.strip() for u in os.environ.get("CACHE_TEST_REDIS_URLS", "redis://localhost:6379/0").split(",") if u.strip()]


def _reachable(url: str) -> bool:
    try:
        import redis
        r = redis.from_url(url, socket_timeout=0.5, socket_connect_timeout=0.5, decode_responses=True)
        return bool(r.ping()) and any(m.get("name") == "search" for m in r.module_list())
    except Exception:
        return False


@pytest.fixture(params=URLS, ids=lambda u: u.rsplit(":", 1)[-1])
def url(request):
    if not _reachable(request.param):
        pytest.skip(f"no Valkey/Redis with a search module at {request.param}")
    return request.param


@pytest.fixture
def make_cache(url):
    made = []

    def _make(**kw):
        tag = uuid.uuid4().hex[:8]
        kw.setdefault("threshold", 0.90)
        kw.setdefault("max_entries", 20000)
        kw.setdefault("ttl_days", 30)
        kw.setdefault("socket_timeout", 3.0)     # production uses 1 s; docker on a laptop stalls on FT.CREATE
        c = ValkeyCache(url, index_name=f"pa_test_{tag}", key_prefix=f"pa:test:{tag}:", **kw)
        made.append(c)
        return c

    yield _make
    for c in made:
        c.invalidate()
        c._r.delete(c.lru_key, c.stats_key)
        c.drop_index()


@pytest.fixture
def cache(make_cache):
    return make_cache()


@pytest.fixture
def rng():
    return np.random.default_rng(7)


def _indexed(cache) -> int:
    """How many vectors KNN can see right now (valkey-search indexes HSETs asynchronously)."""
    probe = np.zeros(DIM, dtype=np.float32); probe[0] = 1.0
    res = cache._r.execute_command("FT.SEARCH", cache.index_name, "*=>[KNN 1000 @embedding $v]", "PARAMS", "2",
                                   "v", probe.tobytes(), "NOCONTENT", "LIMIT", "0", "1000", "DIALECT", "2")
    return int(res[0])


def _settle(cache=None, expected=None, timeout=3.0):
    if cache is None:
        time.sleep(0.1)
        return
    deadline = time.time() + timeout
    while time.time() < deadline and _indexed(cache) != expected:
        time.sleep(0.02)


def test_ping_and_index_idempotent(cache):
    assert cache.ping() is True
    assert cache.ensure_index() is True
    cache._index_ready = False
    assert cache.ensure_index() is True, "FT.CREATE on an existing index is swallowed"
    assert cache.stats()["entries"] == 0


def test_roundtrip_3072d_with_citations_verbatim(cache, rng):
    base = unit(rng)
    e = entry("Max dose of tramadol?", generation=3, assumption="adult", conflicts=["NY vs VA"],
              source_message_id="m1", model="gpt-5.5", provider="openai")
    assert cache.put(e, base) == e.id
    _settle(cache, 1)
    hit = cache.lookup(base, 3)
    assert hit is not None and hit.similarity == pytest.approx(1.0, abs=1e-5)
    got = hit.entry
    assert (got.id, got.question, got.answer, got.status) == (e.id, e.question, e.answer, "answered")
    assert got.citations == e.citations and got.conflicts == ["NY vs VA"] and got.assumption == "adult"
    assert (got.source_message_id, got.model, got.provider) == ("m1", "gpt-5.5", "openai")
    assert got.hits == 1 and got.last_hit_at is not None
    assert abs((got.created_at - e.created_at).total_seconds()) < 0.001
    assert cache.get(e.id).hits == 1
    assert cache._r.ttl(cache.key(e.id)) > 29 * 86400


@pytest.mark.parametrize("cosine, expect_hit", [(0.89, False), (0.90, True), (0.91, True)])
def test_threshold_boundary(cache, rng, cosine, expect_hit):
    base = unit(rng)
    cache.put(entry(generation=1), base)
    _settle(cache, 1)
    hit = cache.lookup(at_cosine(base, cosine, rng), 1)
    assert (hit is not None) is expect_hit
    if hit:
        assert hit.similarity == pytest.approx(cosine, abs=1e-4)


def test_precision_nearest_neighbour(cache, rng):
    a, b = unit(rng), unit(rng)
    ea, eb = entry("A", 1), entry("B", 1)
    cache.put(ea, a)
    cache.put(eb, b)
    _settle(cache, 2)
    assert cache.lookup(at_cosine(a, 0.91, rng), 1).entry.id == ea.id
    assert cache.lookup(at_cosine(b, 0.89, rng), 1) is None


def test_generation_isolation_and_invalidate(cache, rng):
    base = unit(rng)
    old = entry(generation=1)
    cache.put(old, base)
    cache.put(entry(generation=2), unit(rng))
    cache.put(entry(generation=3), unit(rng))
    _settle(cache, 3)
    assert cache.lookup(base, 2) is None
    assert cache.lookup(base, 1).entry.id == old.id
    assert cache.invalidate(before_generation=3) == 2
    assert cache.get(old.id) is None and cache.stats()["entries"] == 1
    assert cache.invalidate() == 1 and cache.stats()["entries"] == 0


def test_put_rejects_bad_entries_and_dims(cache, rng):
    with pytest.raises(ValueError):
        cache.put(entry(status="no_answer"), unit(rng))
    with pytest.raises(ValueError):
        cache.put(entry(citations=[]), unit(rng))
    with pytest.raises(ValueError):
        cache.put(entry(), unit(rng, dim=1536))
    assert cache.stats()["entries"] == 0


def test_eviction_least_recently_hit(make_cache, rng):
    cache = make_cache(max_entries=3)
    vecs = [unit(rng) for _ in range(4)]
    entries = [entry(f"q{i}", 1) for i in range(3)]
    for e, v in zip(entries, vecs):
        cache.put(e, v)
        time.sleep(0.01)
    _settle(cache, 3)
    assert cache.lookup(vecs[0], 1) is not None        # q0 most recently hit; q1 least
    cache.put(entry("q3", 1), vecs[3])
    assert cache.get(entries[1].id) is None
    assert cache.get(entries[0].id) is not None and cache.get(entries[2].id) is not None
    assert cache._r.zcard(cache.lru_key) == 3


def test_stats_counters(cache, rng):
    v = unit(rng)
    e = entry(generation=5)
    cache.put(e, v)
    _settle(cache, 1)
    cache.lookup(v, 5)
    cache.lookup(unit(rng), 5)
    cache.lookup(v, 6)
    s = cache.stats()
    assert (s["entries"], s["hits"], s["misses"], s["hit_rate"]) == (1, 1, 2, 0.3333)
    assert s["generation"] == 6 and s["threshold"] == 0.9 and s["backend"] == "valkey"
    assert cache.delete(e.id) is True and cache.delete(e.id) is False


def test_concurrent_puts(cache, rng):
    vecs = [unit(rng) for _ in range(64)]
    entries = [entry(f"q{i}", 1) for i in range(64)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(lambda p: cache.put(*p), zip(entries, vecs)))
    assert sorted(ids) == sorted(e.id for e in entries)
    _settle(cache, 64)
    assert cache.stats()["entries"] == 64
    with ThreadPoolExecutor(max_workers=8) as pool:
        hits = list(pool.map(lambda v: cache.lookup(v, 1), vecs))
    assert [h.entry.id for h in hits] == [e.id for e in entries]


def test_expired_entry_leaves_index(cache, rng):
    v = unit(rng)
    e = entry()
    cache.put(e, v)
    _settle(cache, 1)
    cache._r.pexpire(cache.key(e.id), 200)
    time.sleep(0.4)
    assert cache.lookup(v, 1) is None
    assert cache.get(e.id) is None


def test_index_recreated_after_drop(cache, rng):
    v = unit(rng)
    cache.put(entry(), v)
    cache.drop_index()
    cache._index_ready = True                           # pretend we didn't notice
    assert cache.lookup(v, 1) is None                   # fails soft, marks the index missing
    _settle()
    hit = cache.lookup(v, 1)                            # recreated; backfill picks the key up
    assert hit is None or hit.entry is not None


def test_unreachable_server_fails_soft(rng, caplog):
    cache = ValkeyCache("redis://127.0.0.1:1/0", socket_timeout=0.2)
    assert cache.ping() is False
    assert cache.lookup(unit(rng), 1) is None
    e = entry()
    assert cache.put(e, unit(rng)) == e.id
    assert cache.get(e.id) is None and cache.delete(e.id) is False and cache.invalidate() == 0
    assert cache.stats()["backend"] == "valkey" and cache.stats()["entries"] == 0
    assert not any(e.question in r.message for r in caplog.records)
