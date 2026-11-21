"""pharmassist.search.hybrid over the store: v1's search() behaviour (modes, RRF, program filter,
parent expansion, reranking, result keys), on MemoryStore and (integration) PgStore."""

import numpy as np
import pytest

from pharmassist.search import hybrid
from test_store_fixtures import DIM, build_corpus, pg_dsn, pg_store, seeded_vectors, store  # noqa: F401

CFG = {"mode": "hybrid", "rrf_k": 60, "fusion_depth": 100, "return_parents": False, "rerank": None}
V1_CHUNK_KEYS = {"rank", "score", "chunk_id", "doc_id", "page", "text", "program", "doc_type", "authority", "date", "pages",
                 "parent_id", "source_sha256", "printed_pages", "section", "content_types", "extraction", "bboxes",
                 "figure_ids", "verification"}
V1_PARENT_KEYS = {"rank", "score", "parent_id", "doc_id", "page", "pages", "section", "text", "program", "doc_type", "authority",
                  "date", "source_sha256", "printed_pages", "content_types", "extraction", "figure_ids", "verification",
                  "matched_child"}


def embedder(vectors: dict, target: str):
    """A fake embedder: every query lands next to `target`'s vector (plus a little noise)."""
    noise = 0.05 * seeded_vectors(1, 777)[0]

    def embed(text):
        return (vectors[target] + noise).tolist()
    return embed


def test_hybrid_result_dicts_keep_v1s_keys(store):
    c = build_corpus(store)
    res = hybrid.search("buprenorphine split dosing", k=3, store=store, embed=embedder(c["vectors"], "va_guide:s0:c1"), cfg=CFG)
    assert [r["rank"] for r in res] == [1, 2, 3]
    top = res[0]
    assert V1_CHUNK_KEYS | {"dense_rank", "keyword_rank", "version_id"} <= set(top)
    assert top["chunk_id"] == "va_guide:s0:c1" and top["doc_id"] == "va_guide" and top["dense_rank"] == 1 and top["keyword_rank"] == 1
    assert top["page"] == 2 and top["pages"] == [2] and top["section"] == "Pain > Buprenorphine" and top["doc_type"] == "guide"
    assert top["extraction"] == ["docling_text"] and top["content_types"] == ["text"] and top["date"] == "2024-01"
    assert "embedding" not in top and isinstance(top["score"], float)
    assert hybrid.last_timings["backend"] == type(store).__name__
    assert {"embed_s", "dense_s", "keyword_s"} <= set(hybrid.last_timings)


def test_rrf_fuses_both_halves(store):
    c = build_corpus(store)
    # dense points at the NY GLP-1 chunk; the words point at the VA semaglutide chunk: both must surface
    res = hybrid.search("semaglutide GLP-1 once weekly", k=9, store=store, embed=embedder(c["vectors"], "ny_pdl:s0:c1"), cfg=CFG)
    ids = [r["chunk_id"] for r in res]
    assert {"ny_pdl:s0:c1", "va_guide:s1:c1"} <= set(ids[:2])
    by_id = {r["chunk_id"]: r for r in res}
    assert by_id["ny_pdl:s0:c1"]["dense_rank"] == 1
    assert by_id["va_guide:s1:c1"]["keyword_rank"] == 1
    kw_only = [r for r in res if r["dense_rank"] is None]
    assert kw_only == [] or all(r["keyword_rank"] is not None for r in kw_only)
    assert res[0]["score"] >= res[1]["score"] >= res[-1]["score"]


def test_single_modes(store):
    c = build_corpus(store)
    dense = hybrid.search("anything", k=2, store=store, embed=embedder(c["vectors"], "cms_memo:s0:c0"), mode="dense", cfg=CFG)
    assert dense[0]["chunk_id"] == "cms_memo:s0:c0" and "dense_rank" not in dense[0] and 0.9 < dense[0]["score"] <= 1.0
    kw = hybrid.search("naloxone", k=5, store=store, mode="keyword", cfg=CFG)      # no embedder needed
    assert [r["chunk_id"] for r in kw] == ["va_guide:s1:c0"] and "keyword_rank" not in kw[0]
    assert hybrid.keyword_only("reject code 22", 3, store=store, cfg=CFG)[0]["doc_id"] == "ny_pdl"
    assert hybrid.dense_only("x", 1, store=store, embed=embedder(c["vectors"], "va_guide:s0:c0"), cfg=CFG)[0]["chunk_id"] == "va_guide:s0:c0"
    with pytest.raises(ValueError):
        hybrid.search("x", store=store, mode="semantic", cfg=CFG)
    with pytest.raises(ValueError):
        hybrid.search("x", store=store, mode="dense", cfg=CFG)             # dense without an embedder


@pytest.mark.parametrize("mode", ["dense", "keyword", "hybrid"])
def test_program_filter_returns_k_results_from_that_program(store, mode):
    c = build_corpus(store)
    res = hybrid.search("buprenorphine", k=2, store=store, embed=embedder(c["vectors"], "va_guide:s0:c1"), mode=mode,
                        program="NY Medicaid", cfg=CFG)
    assert res and {r["program"] for r in res} == {"NY Medicaid"}
    assert len(res) == (1 if mode == "keyword" else 2)      # only one NY chunk mentions buprenorphine
    assert hybrid.search("buprenorphine", k=2, store=store, embed=embedder(c["vectors"], "va_guide:s0:c1"), mode=mode,
                         program="Atlantis Medicaid", cfg=CFG) == []


def test_return_parents_gives_one_result_per_parent_with_the_parent_text(store):
    c = build_corpus(store)
    cfg = {**CFG, "return_parents": True}
    res = hybrid.search("metformin diabetes", k=3, store=store, embed=embedder(c["vectors"], "va_guide:s0:c0"), cfg=cfg)
    assert [r["rank"] for r in res] == [1, 2, 3]
    top = res[0]
    assert V1_PARENT_KEYS | {"dense_rank", "keyword_rank", "version_id"} <= set(top)
    assert top["parent_id"] == "va_guide:s0" and top["matched_child"] == "va_guide:s0:c0"
    assert "Metformin" in top["text"] and "Buprenorphine" in top["text"]        # both children's text
    assert top["pages"] == [1, 2] and top["page"] == 1 and top["program"] == "VA" and top["date"] == "2024-01"
    assert top["extraction"] == ["docling_text"] and top["doc_type"] == "guide"
    assert len({r["parent_id"] for r in res}) == len(res)
    assert "parents_s" in hybrid.last_timings
    # parents are the unit: k counts parents, so asking for all of them returns every parent once
    everything = hybrid.search("metformin", k=50, store=store, embed=embedder(c["vectors"], "va_guide:s0:c0"), cfg=cfg)
    assert len(everything) == len(c["parents"])


def test_rerank_reorders_the_fused_top_and_records_fused_rank(store, monkeypatch):
    c = build_corpus(store)

    class FakeCrossEncoder:
        def predict(self, pairs, show_progress_bar=False):
            # prefer the NY PDL text whatever the fused order was
            return np.array([1.0 if "non-preferred" in text else 0.1 for _, text in pairs])

    monkeypatch.setattr(hybrid, "_reranker", lambda model: FakeCrossEncoder())
    cfg = {**CFG, "rerank": {"model": "fake/cross-encoder", "depth": 5}}
    res = hybrid.search("buprenorphine", k=2, store=store, embed=embedder(c["vectors"], "va_guide:s0:c1"), cfg=cfg)
    assert res[0]["chunk_id"] == "ny_pdl:s1:c0" and res[0]["score"] == 1.0
    assert res[0]["fused_rank"] > 1 and res[1]["fused_rank"] == 1 and "rerank_s" in hybrid.last_timings
    assert len(res) == 2


def test_rerank_timeout_keeps_the_fused_order(store, monkeypatch):
    import time as _time

    class SlowCrossEncoder:
        def predict(self, pairs, show_progress_bar=False):
            _time.sleep(0.5)
            return [1.0] * len(pairs)
    c = build_corpus(store)
    monkeypatch.setattr(hybrid, "_reranker", lambda model: SlowCrossEncoder())
    cfg = {**CFG, "rerank": {"model": "slow/cross-encoder", "depth": 5, "timeout_s": 0.05}}
    fused = hybrid.search("naloxone", k=3, store=store, embed=embedder(c["vectors"], "va_guide:s1:c0"), cfg={**CFG})
    res = hybrid.search("naloxone", k=3, store=store, embed=embedder(c["vectors"], "va_guide:s1:c0"), cfg=cfg)
    assert [r["chunk_id"] for r in res] == [r["chunk_id"] for r in fused]
    assert hybrid.last_timings.get("rerank_timed_out") is True and "fused_rank" not in res[0]


def test_config_defaults_come_from_config_yaml(store):
    cfg = hybrid.default_config()
    assert cfg["mode"] == "hybrid" and cfg["rrf_k"] == 60 and cfg["fusion_depth"] == 100 and cfg["return_parents"] is True
    assert cfg["rerank"] is None            # off: measured best under the 30 s rule (see config.yaml)
    c = build_corpus(store)
    res = hybrid.search("naloxone", k=1, store=store, embed=embedder(c["vectors"], "va_guide:s1:c0"))
    assert res[0]["parent_id"] == "va_guide:s1" and "matched_child" in res[0]


def test_pg_dense_uses_the_configured_ef_search(store):
    if type(store).__name__ != "PgStore":
        pytest.skip("PgStore only")
    assert store.ef_search == 80 and store.dim == DIM
    c = build_corpus(store)
    hits = store.search.dense(c["vectors"]["cms_memo:s0:c1"], 3)
    assert hits[0].chunk.chunk_id == "cms_memo:s0:c1"
