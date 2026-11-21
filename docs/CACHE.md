# Semantic answer cache (v2, stream D)

Contract: `src/pharmassist/cache/base.py`. Implementations: `valkey.py` (production), `memory.py`
(tests of other streams), `NullCache` (disabled). `open_cache(cfg)` in `factory.py` picks from the
`cache:` block of `config.yaml`; `REDIS_URL` comes from the environment (`.env` locally).

## How a lookup works

1. The API embeds the normalized question once (`text-embedding-3-large`, 3072 dims) and calls
   `lookup(embedding, generation)`.
2. One `FT.SEARCH pa_answers "@generation:[g g]=>[KNN 1 @embedding $v AS score]" PARAMS 2 v <3072×float32 LE>
   RETURN 1 score DIALECT 2 TIMEOUT 800`. valkey-search returns the cosine **distance** (1 − cos);
   similarity = 1 − score, rounded to 4 decimals (the server computes in float32; measured error ≈ 1e-6).
3. Similarity ≥ `cache.threshold` (0.90) → `HGETALL` the entry, bump `hits`/`last_hit_at`, update the
   LRU registry and the global `hits` counter; else count a miss. Entries of other generations are never
   candidates because the filter is part of the query; they are deleted by `invalidate(before_generation=g)`
   after a reindex.

Keys: `pa:ans:<uuid>` HASH (entry fields, `citations`/`conflicts` as JSON, `embedding` bytes), TTL
`ttl_days`. Bookkeeping lives outside the indexed prefix on purpose: `pa:ans-lru` ZSET (id → last hit
epoch; `max_entries` eviction pops the smallest scores) and `pa:ans-stats` HASH (`hits`, `misses`,
`generation`). A HASH *under* `pa:ans:` would be indexed as an entry. The index is created lazily by the
first call (`FT.CREATE … ON HASH PREFIX 1 pa:ans: SCHEMA embedding VECTOR HNSW 10 TYPE FLOAT32 DIM 3072
DISTANCE_METRIC COSINE M 16 EF_CONSTRUCTION 200 generation NUMERIC`); "already exists" is swallowed, so
two app instances can start together. `stats()["entries"]` is the registry size (`FT.INFO num_docs` lags
HSETs by hundreds of ms on valkey-search).

Only `status == "answered"` entries with ≥ 1 citation are stored (`put` raises `ValueError` otherwise).
Everything else fails soft: a Valkey outage makes lookups miss, puts drop (the caller still gets the id),
`ping()` returns False for `/health/ready`. Socket and connect timeouts are 1 s. Logs never contain the
question or answer; the first failure is a WARNING, repeats are DEBUG until a call succeeds.

## Engine compatibility (measured 2026-10-18)

The query above is the common subset of **valkey-search** (Valkey 8.1/9.0 `valkey/valkey-bundle`, module
1.0.3) and **RediSearch** (`redis/redis-stack-server`, search 2.10): the integration suite passes on all
three (`CACHE_TEST_REDIS_URLS=redis://localhost:6380/0,redis://localhost:6381/0,redis://localhost:6382/0`).
Differences that shaped the code:

| | valkey-search | RediSearch |
|---|---|---|
| `SORTBY` on a KNN query | rejected (`Unexpected argument`) — results are distance-ordered anyway | accepted |
| Pure filter query without `=>[KNN …]` | rejected (`Missing =>`), so `invalidate` walks the registry, not the index | accepted |
| Result shape under RESP3 | flat list | map → the client pins `protocol=2` |
| Field order in results | `answer, score` | `score, answer` → parsed as a dict |
| "index exists" error text | `Index X already exists.` | `Index already exists` → matched case-insensitively on "already exists" |
| `FT.INFO num_docs` | lags writes | immediate |

**valkey-search 1.0.3 hazard (the reason for `pipeline(transaction=False)` everywhere):** an indexed HASH
written inside `MULTI`/`EXEC` makes the next `DEL`/`PEXPIRE` of that key block the whole server
(measured > 30 s on Valkey 8.1.10 and 9.0.6, identical commands outside a transaction ≈ 1 ms). Keep it
that way in any code that writes `pa:ans:*` keys. Expired keys leave the index on their own; HSETs are
indexed asynchronously (a KNN sees a new key after a few ms, so a second identical question milliseconds
later may miss once — harmless).

## Amazon ElastiCache for Valkey: does it support this?

Yes, on node-based clusters. AWS's docs state "ElastiCache Valkey version 8.2 provides support for Vector
Search on node-based clusters" in all regions at no additional cost (vector search only; 9.0+ adds
non-vector/hybrid search and aggregations) — https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/search-features-limits.html,
announcement https://aws.amazon.com/about-aws/whats-new/2025/10/amazon-elasticache-vector-search/,
getting started https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/vector-search.html. AWS's own
semantic-cache walkthrough uses the same `FT.CREATE … HNSW … COSINE` / `FT.SEARCH … KNN … PARAMS … DIALECT 2`
/ `HSET` / `EXPIRE` commands — https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/semantic-caching-implementation.html.

What stream G must set (CloudFormation `AWS::ElastiCache::ReplicationGroup`):

- `Engine: valkey`, `EngineVersion: "8.2"` (the search module is built into the 8.2 engine; nothing to
  enable). Not serverless: the docs only name node-based clusters.
- Limits that apply to 8.2: 32,768 max dimensions (we use 3,072), 10 indexes (we use 1), 50 fields per
  index, `FT.SEARCH TIMEOUT` ≤ 60,000 ms — https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/vector-search-features-limits.html.
- Node type: "available on all ElastiCache instance types other than nodes with data tiering"; for
  burstable nodes "Using search on t3 and t4g instances requires increasing the memory reserve to at least
  50% for micro and 30% for small instances" (same page). So `cache.t4g.micro` works **only with a custom
  parameter group** (family `valkey8`) setting `reserved-memory-percent = 50` (default 25; default groups
  cannot be edited) — https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/redis-memory-management.html.
  That leaves ≈ 0.25 GB of a t4g.micro's 0.5 GB for data; 20,000 entries × (3072 × 4 B vector + ~4 KB
  text + HNSW graph) ≈ 350–400 MB, so either lower `cache.max_entries` to ≈ 8,000 on t4g.micro or use
  `cache.t4g.small` (1.37 GB, 30 % reserve) — recommended, ≈ $12/month more.
- Replicas: index backfill "isn't synchronized between primaries and replicas"; a single node (the plan's
  default) avoids reading from a replica that is still backfilling. Scaling events temporarily reduce recall.
- Cluster mode off (one shard). Index names are cluster-wide without a hash tag; nothing to change.
- Local parity: `valkey/valkey-bundle:8.1` or `9.0` in docker-compose (no `8.2` image exists; AWS's 8.2
  engine bundles the same valkey-search module family). Redis Stack also works.

Fallback if the account cannot create Valkey 8.2 with search (not implemented): keep `ValkeyCache` for the
entries (`pa:ans:*`, TTL, LRU, counters) and move the nearest-neighbour step to pgvector —
`cache_vectors(id text, generation int, embedding halfvec(3072))` with an HNSW cosine index, filtered by
generation, `1 - (embedding <=> $1)` as similarity. Same interface, same behaviour, one more Postgres round
trip (~5 ms). MemoryDB for Valkey also offers vector search but costs ≈ 3× more than ElastiCache.

## Tests

```
docker run -d --name pa-valkey -p 6379:6379 valkey/valkey-bundle:8.1      # or :9.0, or redis/redis-stack-server
pytest tests/test_cache_memory.py tests/test_cache_factory.py              # 25 unit tests, no server
pytest -m integration tests/test_cache_valkey.py                           # skips cleanly without a server
CACHE_TEST_REDIS_URLS=redis://localhost:6380/0,redis://localhost:6381/0 pytest tests/test_cache_valkey.py
```

The integration suite covers index idempotence, 3072-d round trip with citations verbatim, the
0.89/0.90/0.91 boundary with seeded vectors, nearest-neighbour precision, generation isolation and
invalidation, rejection of unanswered/uncited/wrong-dimension entries, least-recently-hit eviction,
counters, 64 concurrent puts, TTL expiry leaving the index, index recreation after a drop, and fail-soft
behaviour against an unreachable server.
