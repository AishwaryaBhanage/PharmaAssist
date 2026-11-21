"""ToolBox over the store contracts: the original-question search (fake search; no index, no API),
the drug lookups over store.content.table_rows, read_page through the injected PDF resolver with the
store's figures, and list_documents from the store's catalog."""

import json
from types import SimpleNamespace as NS

import pytest

from pharmassist.agent import tools
from tests.test_agent_fakes import NY_ROWS, TABLES, VA_ROWS, FakeSearch, FakeStore, make_pdf, make_tools, STRUCTURED_CFG

QUESTION = "Can the prescriber start an SGLT2 inhibitor without metformin for a Veteran with ASCVD?"


def unit(uid, doc="va_pbm_t2dm_clinicians_guide", page=11):
    return {"doc_id": doc, "page": page, "pages": [page], "program": "VA", "authority": "advisory",
            "date": "2020-05", "text": f"text of {uid}", "section": f"section {uid}", "parent_id": uid,
            "matched_child": f"{uid}:c0"}


def box(question=QUESTION, results=None, store=None, cfg=STRUCTURED_CFG):
    return make_tools(store, FakeSearch(results or {}), cfg=cfg, question=question)


def queries(b):
    return [c["query"] for c in b.fake_search.calls]


# ---- the original question is always searched too ----

def test_the_original_question_is_searched_alongside_the_agent_query():
    b = box()
    b.run("search_documents", {"query": "SGLT2 ASCVD regardless of A1c"})
    assert sorted(queries(b)) == sorted([QUESTION, "SGLT2 ASCVD regardless of A1c"])
    meta = b.calls[-1]["search"]
    assert meta["original_query"] == QUESTION and meta["agent_query"] == "SGLT2 ASCVD regardless of A1c"
    assert {e["source"] for e in meta["executed"]} == {"original", "agent"}
    assert all("seconds" in e for e in meta["executed"])


def test_an_agent_query_equal_to_the_question_runs_once():
    b = box()
    b.run("search_documents", {"query": "  can the prescriber start an SGLT2 inhibitor without metformin, "
                                        "for a veteran with ASCVD  "})
    assert queries(b) == [QUESTION]
    assert [e["source"] for e in b.calls[-1]["search"]["executed"]] == ["original"]


def test_program_k_store_and_search_config_reach_the_search_function():
    seen = []

    def search(query, k, *, store, embed, program=None, cfg=None):
        seen.append((k, program, store, embed, cfg))
        return []
    st = FakeStore()
    b = tools.ToolBox(st, search, embed="EMBED", cfg=STRUCTURED_CFG, question=QUESTION)
    b.run("search_documents", {"query": "SGLT2", "program": "VA", "k": 5})
    assert len(seen) == 2 and all(s == (5, "VA", st, "EMBED", STRUCTURED_CFG["search"]) for s in seen)


def test_the_question_text_is_passed_verbatim():
    q = "Suboxone 8/2 mg films, 4 daily, #120/30 days for NYRx: is 32 mg OK?"
    b = box(q)
    b.run("search_documents", {"query": "buprenorphine max dose"})
    assert q in queries(b)


def test_a_unit_both_searches_find_takes_one_slot():
    b = box(results={QUESTION: [unit("A"), unit("B")], "agent q": [unit("B"), unit("C")]})
    text, _ = b.run("search_documents", {"query": "agent q", "k": 3})
    rows = json.loads(text)
    assert [r["section"] for r in rows] == ["section B", "section A", "section C"]   # B found by both ranks first
    meta = b.calls[-1]["search"]
    assert meta["duplicates_merged"] == 1 and meta["from_both"] == 1 and meta["returned"] == 3
    assert meta["provenance"][0] == {"unit": "B", "found_by": {"original": 2, "agent": 1}}


def test_neither_querys_top_k_is_crowded_out():
    """Disjoint results: all 8 of each come back (the union), RRF-ordered, ties to the original."""
    b = box(results={QUESTION: [unit(f"O{i}", page=i) for i in range(1, 9)],
                     "agent q": [unit(f"G{i}", page=20 + i) for i in range(1, 9)]})
    text, _ = b.run("search_documents", {"query": "agent q", "k": 8})
    sections = [r["section"] for r in json.loads(text)]
    assert len(sections) == 16 and sections[:2] == ["section O1", "section G1"]
    assert {f"section O{i}" for i in range(1, 9)} <= set(sections)       # rank 7 and 8 survive
    assert {f"va_pbm_t2dm_clinicians_guide:p{i}" for i in (7, 8)} <= b.seen   # and are citable


def test_the_union_is_capped():
    b = box(results={QUESTION: [unit(f"O{i}", page=i) for i in range(1, 16)],
                     "agent q": [unit(f"G{i}", page=20 + i) for i in range(1, 16)]})
    text, _ = b.run("search_documents", {"query": "agent q", "k": 15})
    assert len(json.loads(text)) == tools.MAX_MERGED


def test_the_original_search_is_cached_per_program_and_k_within_one_run():
    b = box()
    b.run("search_documents", {"query": "first"})
    b.run("search_documents", {"query": "second"})
    assert queries(b).count(QUESTION) == 1
    assert b.calls[-1]["search"]["executed"][0] == {"source": "original", "query": QUESTION, "program": None,
                                                    "k": 8, "seconds": 0.0, "cached": True, "results": 0}
    b.run("search_documents", {"query": "third", "program": "VA"})       # another filter: searched again
    b.run("search_documents", {"query": "fourth", "k": 4})                # another k: searched again
    assert queries(b).count(QUESTION) == 3
    assert queries(box()).count(QUESTION) == 0                            # a new run starts empty


def test_without_a_question_only_the_agent_query_runs():
    b = box(question=None)
    b.run("search_documents", {"query": "only this"})
    assert queries(b) == ["only this"]


def test_lookups_never_trigger_a_document_search():
    b = box()
    b.run("list_documents", {})
    assert b.fake_search.calls == [] and "search" not in b.calls[-1]


def test_merged_results_keep_each_units_citation_ids_and_evidence():
    from pharmassist.agent.loop import check_citations
    # Q01's shape: the question finds the clinician's guide p11-12, the agent query the CPG p58
    orig = {**unit("guide:s10", page=11), "pages": [11, 12], "text": "[p 11] metformin first [p 12] eGFR 30-45"}
    agent = unit("cpg:s61", doc="va_dod_cpg_diabetes_2023", page=58)
    shared = unit("pharm:s6", doc="va_pbm_t2dm_pharmacotherapy_2025", page=5)
    b = box(results={QUESTION: [shared, orig], "SGLT2 ASCVD": [agent, shared]})
    text, is_error = b.run("search_documents", {"query": "SGLT2 ASCVD", "program": "VA"})
    rows = json.loads(text)
    assert not is_error
    assert [(r["doc_id"], r.get("pages", [r["page"]])) for r in rows] == [
        ("va_pbm_t2dm_pharmacotherapy_2025", [5]),          # found by both
        ("va_dod_cpg_diabetes_2023", [58]),                  # agent rank 1
        ("va_pbm_t2dm_clinicians_guide", [11, 12])]          # original rank 2
    # every merged page is citable, once, with the text that came with it
    assert b.seen == {"va_pbm_t2dm_pharmacotherapy_2025:p5", "va_dod_cpg_diabetes_2023:p58",
                      "va_pbm_t2dm_clinicians_guide:p11", "va_pbm_t2dm_clinicians_guide:p12"}
    assert "eGFR 30-45" in b.evidence["va_pbm_t2dm_clinicians_guide:p12"]
    checked = check_citations([{"doc_id": "va_pbm_t2dm_clinicians_guide", "page": 12},
                               {"doc_id": "va_pbm_t2dm_clinicians_guide", "page": 13}], b.seen, b.catalog)
    assert [c["flag"] for c in checked] == [None, "not returned by any tool during this question"]
    assert checked[0]["link"].endswith("#page=12")


# ---- the store: catalog, lookups, pages, figures ----

def test_list_documents_comes_from_the_store_catalog():
    cat = {"doc_a": {"title": "Doc A", "program": "VA", "doc_type": "guide", "authority": "advisory", "date": "2024-01",
                     "source_url": "https://example.org/a.pdf", "file": "a.pdf", "pages": 3},
           "sheet_b": {"title": "Sheet B", "program": "VA", "doc_type": "formulary", "authority": "binding",
                       "date": "2026-09", "source_url": "https://example.org/b.xlsx", "file": "b.xlsx", "pages": None}}
    b = box(store=FakeStore(catalog=cat))
    rows = json.loads(b.run("list_documents", {})[0])
    assert rows == [{"id": "doc_a", "title": "Doc A", "program": "VA", "doc_type": "guide", "authority": "advisory",
                     "date": "2024-01", "pages": 3, "searchable": True},
                    {"id": "sheet_b", "title": "Sheet B", "program": "VA", "doc_type": "formulary", "authority": "binding",
                     "date": "2026-09", "pages": None, "searchable": False}]
    assert tools.page_link("doc_a", 2, b.catalog) == "https://example.org/a.pdf#page=2"
    assert tools.page_link("sheet_b", None, b.catalog) == "https://example.org/b.xlsx"


def test_va_lookup_reads_the_store_rows_and_cites_the_rule_rows():
    st = FakeStore(tables=TABLES)
    b = box(store=st)
    text, is_error = b.run("lookup_va_formulary", {"drug": "Ozempic"})
    r = json.loads(text)
    assert not is_error and r["result"] == "exact_match" and r["rows"][0]["row"] == 8
    assert r["rows"][0]["Restriction"] == "PA-F" and "prior authorization required (see row 6)" in r["rows"][0]["Restriction meaning"]
    assert r["rule"]["cite"] == {"doc_id": "va_national_formulary_2026_09", "row": 5}
    assert b.seen == {f"va_national_formulary_2026_09:r{n}" for n in (8, 5, 6, 7)}
    assert st.table_calls[0][0] == "va_formulary"
    # a second lookup on the same store and generation reuses the built table
    b.run("lookup_va_formulary", {"drug": "buprenorphine"})
    assert len(st.table_calls) == 1


def test_ny_lookup_reads_the_store_rows_and_cites_coverage_pages():
    b = box(store=FakeStore(tables=TABLES))
    text, is_error = b.run("lookup_ny_medicaid_drug", {"drug": "Rybelsus"})
    r = json.loads(text)
    assert not is_error and r["result"] == "exact_match"
    row = r["classes"][0]["rows"][0]
    assert row["listed_as"] == "non-preferred" and row["flags"] == {"ST": tools and __import__("pharmassist.tables.ny_pdl", fromlist=["FLAGS"]).FLAGS["ST"]}
    assert b.seen == {"ny_medicaid_pdl:p1", "ny_medicaid_pdl:p34", "ny_medicaid_pdl:p35"}
    assert json.loads(b.run("lookup_ny_medicaid_drug", {"drug": "GLP-1"})[0])["result"] == "class_match"


def test_a_new_index_generation_rebuilds_the_tables():
    st = FakeStore(tables=TABLES, generation=1)
    b = box(store=st)
    b.run("lookup_ny_medicaid_drug", {"drug": "Ozempic"})
    st.documents.generation = lambda: 2
    b.run("lookup_ny_medicaid_drug", {"drug": "Ozempic"})
    assert [c[0] for c in st.table_calls] == ["ny_pdl", "ny_pdl"]


def test_va_rows_keyed_by_header_labels_are_accepted():
    from pharmassist.tables.va_formulary import HEADER
    rows = [{"row": n, **dict(zip(HEADER, cells))} for n, cells in ((r["row"], r["cells"]) for r in VA_ROWS)]
    f = tools.va_formulary_from_rows(rows)
    assert f.header_row == 7 and list(f.rows.index) == [8, 9, 10]
    with pytest.raises(tools.ToolError, match="no VA formulary rows"):
        tools.va_formulary_from_rows([])


def test_read_page_uses_the_injected_pdf_and_the_stores_figures(tmp_path):
    pdf = make_pdf(tmp_path / "pdl.pdf", pages=86)
    fig = NS(figure_id="ny_medicaid_pdl:p34:f0", page=34, status="ocr_checked",
             record={"kind": "table_image", "title": "GLP-1 table", "rows": [["Ozempic", "preferred"]]})
    st = FakeStore(tables=TABLES, figures={("ny_medicaid_pdl", 34): [fig]})
    resolved = []

    def pdf_path(doc_id):
        resolved.append(doc_id)
        return pdf
    b = tools.ToolBox(st, FakeSearch(), cfg=STRUCTURED_CFG, pdf_path=pdf_path, question=QUESTION, page_figures=True)
    text, is_error = b.run("read_page", {"doc_id": "ny_medicaid_pdl", "page": 34})
    assert not is_error and text.startswith("ny_medicaid_pdl page 34 (NY Medicaid, binding, 2026-09-14)")
    assert "(page 34)" in text and "[Figures on this page, interpreted from the page image]" in text
    assert "[Figure, table_image] GLP-1 table (PDF page 34)" in text and "OCR cross-check passed" in text
    assert b.seen == {"ny_medicaid_pdl:p34"} and resolved == ["ny_medicaid_pdl"]
    b.run("read_page", {"doc_id": "ny_medicaid_pdl", "page": 35})
    assert resolved == ["ny_medicaid_pdl"]           # the open PDF is reused within the question
    plain = tools.ToolBox(st, FakeSearch(), cfg=STRUCTURED_CFG, pdf_path=pdf_path, question=QUESTION)
    assert "[Figures" not in plain.run("read_page", {"doc_id": "ny_medicaid_pdl", "page": 34})[0]   # off by default


def test_read_page_truncates_long_pages(tmp_path):
    pdf = make_pdf(tmp_path / "long.pdf", pages=1, text="\n".join(["word word word word"] * 50))
    cfg = {**STRUCTURED_CFG, "agent": {**STRUCTURED_CFG["agent"], "read_page_chars": 100}}
    b = tools.ToolBox(FakeStore(), FakeSearch(), cfg=cfg, pdf_path=lambda d: pdf, question=QUESTION)
    text, _ = b.run("read_page", {"doc_id": "ny_medicaid_pdl", "page": 1})
    assert text.endswith("[page truncated]") and len(text) < 300


def test_a_missing_pdf_is_a_tool_error_not_a_crash(tmp_path):
    b = tools.ToolBox(FakeStore(), FakeSearch(), cfg=STRUCTURED_CFG, pdf_path=lambda d: tmp_path / "missing.pdf",
                      question=QUESTION)
    text, is_error = b.run("read_page", {"doc_id": "ny_medicaid_pdl", "page": 1})
    assert is_error and "couldn't be opened" in text and b.calls[-1]["error_kind"] == "tool_error"


def test_read_page_of_the_spreadsheet_points_at_the_lookup_when_structured():
    b = box(store=FakeStore(tables=TABLES))
    text, is_error = b.run("read_page", {"doc_id": "va_national_formulary_2026_09", "page": 1})
    assert is_error and text == "Use lookup_va_formulary for the VA formulary spreadsheet."


def test_tool_results_are_recorded_for_tracing_cut_to_the_limit():
    b = box(results={QUESTION: [{**unit("big"), "text": "x" * 10_000}]})
    b.run("search_documents", {"query": QUESTION})
    assert len(b.calls[-1]["result"]) == tools.RESULT_CHARS
