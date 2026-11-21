"""Hybrid search over the store: v1's `index.search()` behaviour (dense + keyword, reciprocal rank
fusion, optional cross-encoder rerank, one result per parent section) with PostgreSQL doing the two
halves instead of numpy and BM25 files.

Result dicts keep v1's keys so the agent's tools, the evals and the traces work unchanged:
    rank, score, chunk_id, doc_id, page, pages, text, program, doc_type, authority, date, parent_id,
    section, source_sha256, printed_pages, content_types, extraction, bboxes, figure_ids, verification,
    + dense_rank / keyword_rank (hybrid), fused_rank (reranked), matched_child (parent results),
    + v2: version_id.
`embed` is any `str -> list[float]` (the LLM router's embedding in production, a fake in tests), so
this module never touches a model client. The keyword half runs while the question is embedded.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from functools import cache
from typing import Callable, Sequence

from pharmassist.store.protocols import ChunkRecord, ParentRecord, SearchHit, SearchRepo, Store

MODES = ("dense", "keyword", "hybrid")
DEFAULTS = {"mode": "hybrid", "rrf_k": 60, "fusion_depth": 100, "return_parents": True, "rerank": None}

_pool = ThreadPoolExecutor(max_workers=4)
last_timings: dict = {}   # the latest search's stage timings (seconds), for the retrieval evals
# searches may run concurrently, but the cross-encoder may not: PyTorch's MPS backend crashes on
# simultaneous predict calls (same rule as v1)
_rerank_lock = threading.Lock()


def default_config() -> dict:
    """config.yaml `search:` over the built-in defaults."""
    from pharmassist.config import load_config
    return {**DEFAULTS, **(load_config().get("search") or {})}


def _pages(start, end, meta: dict) -> list[int]:
    if meta.get("pages"):
        return list(meta["pages"])
    return list(range(start, end + 1)) if start is not None and end is not None else ([start] if start else [])


def chunk_result(c: ChunkRecord) -> dict:
    """A chunk as v1's chunk dict (the Chunk dataclass fields), from the columns plus `metadata`."""
    m = c.metadata or {}
    return {"chunk_id": c.chunk_id, "doc_id": c.document_id, "page": m.get("page", c.page_start), "text": c.text,
            "program": c.program, "doc_type": m.get("doc_type", ""), "authority": c.authority, "date": c.doc_date,
            "pages": _pages(c.page_start, c.page_end, m), "parent_id": c.parent_id,
            "source_sha256": m.get("source_sha256"), "printed_pages": m.get("printed_pages", []),
            "section": " > ".join(c.section_path) if c.section_path else m.get("section"),
            "content_types": list(c.content_types),
            "extraction": m.get("extraction", [c.extraction] if c.extraction else []),
            "bboxes": m.get("bboxes", []), "figure_ids": list(c.figure_ids), "verification": c.verification,
            "version_id": c.version_id}


def parent_result(p: ParentRecord, child: ChunkRecord) -> dict:
    """A parent as v1's parents.jsonl record; document-level fields fall back to the matched child's."""
    m = p.metadata or {}
    return {"parent_id": p.parent_id, "doc_id": p.document_id, "page": m.get("page", p.page_start),
            "pages": _pages(p.page_start, p.page_end, m),
            "section": " > ".join(p.section_path) if p.section_path else m.get("section"), "text": p.text,
            "program": m.get("program", child.program), "doc_type": m.get("doc_type", (child.metadata or {}).get("doc_type", "")),
            "authority": m.get("authority", child.authority), "date": m.get("date", child.doc_date),
            "source_sha256": m.get("source_sha256", (child.metadata or {}).get("source_sha256")),
            "printed_pages": m.get("printed_pages", []), "content_types": m.get("content_types", list(child.content_types)),
            "extraction": m.get("extraction", []), "figure_ids": m.get("figure_ids", []),
            "verification": m.get("verification"), "version_id": p.version_id}


def rrf(dense: Sequence[SearchHit], keyword: Sequence[SearchHit], rrf_k: int) -> list[tuple[SearchHit, float, dict]]:
    """Reciprocal rank fusion: rank-based, so cosine and ts_rank scales never need calibrating.
    Ties break on the (document_id, chunk_id) key, like v1 broke them on chunk position."""
    key = lambda h: (h.chunk.version_id, h.chunk.chunk_id)  # noqa: E731
    dense_rank = {key(h): h.rank for h in dense}
    kw_rank = {key(h): h.rank for h in keyword}
    hits = {key(h): h for h in [*keyword, *dense]}       # dense last: its hit (with cosine) is kept when both found it
    fused = {k: sum(1 / (rrf_k + ranks[k]) for ranks in (dense_rank, kw_rank) if k in ranks) for k in hits}
    top = sorted(fused, key=lambda k: (-fused[k], k))
    return [(hits[k], fused[k], {"dense_rank": dense_rank.get(k), "keyword_rank": kw_rank.get(k)}) for k in top]


def search(query: str, k: int = 8, *, store: Store, embed: Callable[[str], Sequence[float]] | None = None,
           mode: str | None = None, program: str | None = None, cfg: dict | None = None) -> list[dict]:
    """Top-k results for a query. Each result: rank, score, the chunk (or parent) fields; hybrid adds
    per-half ranks. `program` restricts results to that program before ranking, so a filtered
    search still returns k results when the program has them. `cfg` defaults to config.yaml `search:`."""
    cfg = {**DEFAULTS, **(cfg if cfg is not None else default_config())}
    mode = mode or cfg["mode"]
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    if mode != "keyword" and embed is None:
        raise ValueError("an `embed` callable is required for dense and hybrid search")
    depth = int(cfg["fusion_depth"])
    rerank = cfg.get("rerank")                    # {model, depth}: cross-encoder over the fused top
    by_parent = bool(cfg.get("return_parents"))   # one result per parent section
    want = k
    if rerank or by_parent:
        k = max(k, rerank["depth"] if rerank else depth)   # rank more children, then cut to `want`
    timings: dict = {"backend": type(store).__name__}
    repo: SearchRepo = store.search

    kw_future = None
    if mode in ("keyword", "hybrid"):
        def keyword_half():
            t0 = time.perf_counter()
            hits = repo.keyword(query, k if mode == "keyword" else depth, program=program)
            timings["keyword_s"] = time.perf_counter() - t0
            return hits
        kw_future = _pool.submit(keyword_half)   # runs while the question is embedded
    dense_hits: list[SearchHit] = []
    if mode in ("dense", "hybrid"):
        t0 = time.perf_counter()
        qvec = embed(query)
        timings["embed_s"] = time.perf_counter() - t0
        t0 = time.perf_counter()
        dense_hits = repo.dense(qvec, k if mode == "dense" else depth, program=program)
        timings["dense_s"] = time.perf_counter() - t0
    kw_hits = kw_future.result() if kw_future is not None else []

    if mode == "dense":
        ranked = [(h, h.score, {}) for h in dense_hits[:k]]
    elif mode == "keyword":
        ranked = [(h, h.score, {}) for h in kw_hits[:k]]
    else:
        ranked = rrf(dense_hits, kw_hits, int(cfg["rrf_k"]))[:k]

    if rerank and ranked:
        t0 = time.perf_counter()
        ranked = ranked[:rerank["depth"]]
        scores = _rerank_scores(rerank, query, [h.chunk.text for h, _, _ in ranked])
        if scores is not None:
            ranked = [(h, float(s), {**extra, "fused_rank": r})
                      for (h, _, extra), s, r in sorted(zip(ranked, scores, range(1, len(ranked) + 1)), key=lambda x: -x[1])]
        else:                                     # timed out: the fused order stands (the 30 s rule wins)
            timings["rerank_timed_out"] = True
        timings["rerank_s"] = time.perf_counter() - t0

    if not by_parent:
        out = [{"rank": r, "score": round(float(score), 4), **chunk_result(h.chunk), **extra}
               for r, (h, score, extra) in enumerate(ranked[:want], 1)]
    else:
        # the best child of each parent stands for the parent; later children of it free their slot
        picked, seen = [], set()
        for h, score, extra in ranked:
            pid = (h.chunk.version_id, h.chunk.parent_id)
            if h.chunk.parent_id is None or pid in seen:
                continue
            seen.add(pid)
            picked.append((pid, h, score, extra))
            if len(picked) == want:
                break
        t0 = time.perf_counter()
        parents = store.content.parents_by_ids([pid for pid, *_ in picked]) if picked else {}
        timings["parents_s"] = time.perf_counter() - t0
        out = []
        for pid, h, score, extra in picked:
            p = parents.get(pid)
            if p is None:        # a child without its parent row: fall back to the chunk itself
                out.append({"rank": len(out) + 1, "score": round(float(score), 4), **chunk_result(h.chunk), **extra})
                continue
            out.append({"rank": len(out) + 1, "score": round(float(score), 4), **parent_result(p, h.chunk),
                        "matched_child": h.chunk.chunk_id, **extra})
    last_timings.clear()
    last_timings.update(timings)
    return out


def dense_only(query: str, k: int, *, store: Store, embed, program: str | None = None, cfg: dict | None = None) -> list[dict]:
    return search(query, k, store=store, embed=embed, mode="dense", program=program, cfg=cfg)


def keyword_only(query: str, k: int, *, store: Store, program: str | None = None, cfg: dict | None = None) -> list[dict]:
    return search(query, k, store=store, mode="keyword", program=program, cfg=cfg)


_rerank_pool = ThreadPoolExecutor(max_workers=1)   # one scorer: the model is CPU-bound, so callers queue


def _rerank_scores(rerank: dict, query: str, texts: list[str]) -> list[float] | None:
    """Cross-encoder scores for (query, text) pairs, or None when `rerank.timeout_s` passes first
    (the search then keeps its fused order). Scoring is serialised: a second search waits for the
    first, and its wait counts against its own timeout."""
    def score():
        model = _reranker(rerank["model"])
        with _rerank_lock:
            return list(model.predict([(query, t) for t in texts], show_progress_bar=False))
    timeout = rerank.get("timeout_s")
    if not timeout:
        return score()
    try:
        return _rerank_pool.submit(score).result(timeout=float(timeout))
    except FuturesTimeout:
        return None


def warm(cfg: dict | None = None) -> dict:
    """Load the configured cross-encoder and score one pair, so the first search doesn't pay for it
    (seconds for a large model). Returns the timings; {} when no reranker is configured."""
    cfg = {**DEFAULTS, **(cfg if cfg is not None else default_config())}
    rerank = cfg.get("rerank")
    if not rerank:
        return {}
    t0 = time.perf_counter()
    model = _reranker(rerank["model"])
    load_s = time.perf_counter() - t0
    t0 = time.perf_counter()
    with _rerank_lock:
        model.predict([("warm up", "warm up")], show_progress_bar=False)
    return {"model": rerank["model"], "depth": rerank["depth"], "load_s": round(load_s, 2),
            "predict_s": round(time.perf_counter() - t0, 3)}


@cache
def _reranker(model: str):
    from sentence_transformers import CrossEncoder
    return CrossEncoder(model, max_length=512)
