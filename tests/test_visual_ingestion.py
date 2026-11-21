"""Docling ingestion: figure decisions and checks, table and figure chunking, provenance, and the
built index's visual content. No model or network call: vision records come from the cache.
Index/cache-dependent tests skip when those artifacts aren't built."""

import json

import pytest

from pharmassist.chunkers.docling_sections import (DoclingSectionChunker, fill_group_labels, is_toc,
                                                   printed_page_labels)
from pharmassist.chunkers.sections import SectionChunker, Unit
from pharmassist.config import PROJECT_ROOT
from pharmassist.parsers import figures as F
from pharmassist.parsers.base import Block

FLOWCHART_PAGES = [("va_dod_cpg_diabetes_2023", 21), ("va_dod_cpg_diabetes_2023", 22),
                   ("va_dod_cpg_opioids_2022", 25), ("va_dod_cpg_opioids_2022", 26), ("va_dod_cpg_opioids_2022", 27)]
RECORDS = PROJECT_ROOT / "storage" / "figures" / "records.json"
INDEX = PROJECT_ROOT / "index" / "docling_sections"
FLOW = {"kind": "flowchart", "title": "", "unreadable": [],
        "nodes": [{"id": "1", "shape": "start", "text": "Patient with chronic pain"},
                  {"id": "2", "shape": "decision", "text": "Is the patient on opioids?"},
                  {"id": "3", "shape": "end", "text": "Proceed to Module C"},
                  {"id": "4", "shape": "action", "text": "Reassess in 1-3 months"}],
        "edges": [{"from": "1", "to": "2"}, {"from": "2", "to": "3", "label": "Yes"},
                  {"from": "2", "to": "4", "label": "No"}, {"from": "4", "to": "1", "label": ""}]}


def words(n=5):
    return lambda text: [(i, i + 1) for i in range(len(text.split()))]


# ---- figure decisions, checks and rendering ----

def test_decorative_classes_and_tiny_images_are_inventoried_not_sent_to_vision():
    assert F.decide({"source": "docling", "classes": [["logo", 0.9]], "crop": "x.png"}) == "decorative"
    assert F.decide({"source": "docling", "classes": [["icon", 0.6]], "crop": "x.png"}) == "decorative"
    assert F.decide({"source": "pdf_image", "classes": [], "frac": 0.01, "crop": None}) == "decorative"
    assert F.decide({"source": "docling", "classes": [["flow_chart", 0.98]], "crop": "x.png"}) == "vision"
    assert F.decide({"source": "pdf_image", "classes": [], "frac": 0.4, "crop": "x.png"}) == "vision"


def test_flowchart_checks_catch_unknown_nodes_unlabelled_branches_and_text_not_in_the_image():
    ok = F.check(FLOW, ["Patient with chronic pain", "Is the patient on opioids?", "Yes", "No",
                        "Proceed to Module C", "Reassess in 1-3 months"])
    assert ok["passed"] and ok["ocr_match"] == 1.0
    bad = json.loads(json.dumps(FLOW))
    bad["edges"][2]["label"] = ""                         # a decision exit without its label
    bad["edges"].append({"from": "4", "to": "9"})          # an arrow to a box that doesn't exist
    bad["nodes"][3]["text"] = "Start methadone maintenance"  # text the OCR never saw
    r = F.check(bad, ["Patient with chronic pain", "Is the patient on opioids?", "Proceed to Module C"])
    assert not r["passed"]
    joined = " ".join(r["problems"])
    assert "not all labelled" in joined and "unknown node '9'" in joined and "node 4 text" in joined
    assert F.check(FLOW, [])["problems"] == ["no OCR text to cross-check against"]


def test_rendering_keeps_branch_labels_outcomes_and_loops_and_labels_it_machine_generated():
    head, lines = F.render(FLOW, "ocr_checked", 26)
    assert "Machine-generated visual interpretation" in head and "(PDF page 26)" in head
    assert "untitled in the image" in head          # no invented title
    assert "Box 2 (decision): Is the patient on opioids? -> if Yes: box 3; if No: box 4" in lines
    assert "Decision path: 1 -> 2 -> [Yes] 3" in lines
    assert "Decision path: 1 -> 2 -> [No] 4 -> back to box 1" in lines   # the loop is stated, not dropped
    _, lines = F.render({**FLOW, "unreadable": ["arrow from box 4 is cut off"]}, "machine_interpreted", 26)
    assert lines[-1] == "Unreadable or ambiguous (not interpreted): arrow from box 4 is cut off"


def test_a_model_supplied_title_is_kept_only_when_printed_in_the_image():
    ocr = ["Figure 5.", "Using basal insulin*1,2", "Titrate basal insulin"]
    assert F.title_supported("Figure 5. Using basal insulin", ocr)
    # every word appears somewhere, but not as the printed title
    assert not F.title_supported("Basal insulin titration figure", ocr + ["titration figure"][:0])
    assert not F.title_supported("", ocr)


def test_review_status_requires_a_matching_review_entry():
    assert F.status_for("nope:p1:f0", {"passed": True}) == "ocr_checked"
    assert F.status_for("nope:p1:f0", {"passed": False}) == "machine_interpreted"


# ---- tables and chunking ----

def test_group_label_columns_fill_down_but_ordinary_blanks_stay_blank():
    rows = [["Topic", "Sub", "#"], ["Diabetes", "a", "1"], ["", "b", "2"], ["", "", "3"], ["", "c", "4"]]
    out = fill_group_labels(rows, 1)
    assert [r[0] for r in out[1:]] == ["Diabetes"] * 4
    assert [r[1] for r in out[1:]] == ["a", "b", "", "c"]   # mostly filled: not a label column
    assert fill_group_labels(rows[:3], 1) == rows[:3]        # too short to judge


def test_tables_of_contents_are_recognised():
    assert is_toc([["Research Priorities ..........", "71"], ["A. Complementary ......", "72"]])
    assert not is_toc([["Drug", "Dose"], ["metformin", "500 mg"]])


def test_split_tables_repeat_their_header_and_keep_rows_whole():
    ch = DoclingSectionChunker.__new__(DoclingSectionChunker)
    SectionChunker.__init__(ch, words(), child_tokens=40, overlap_tokens=0, parent_max_tokens=1500)
    ch.records, ch.printed, ch.source_sha256 = {}, {}, "abc"
    rows = [["Drug", "Dose", "Note"]] + [[f"drug{i}", f"{i} mg", "with food"] for i in range(12)]
    table = Block(3, "table", rows=rows, bbox=(0, 0, 1, 1), header_rows=1, caption="Table 2. Doses",
                  footnotes=["a: renal dosing differs"], extraction="tableformer")
    [unit] = ch.units_for(table, "")
    assert unit.header.startswith("[Table: Table 2. Doses] (PDF page 3)\nColumns: Drug | Dose | Note")
    assert unit.text.splitlines()[-1] == "Table note: a: renal dosing differs"
    pieces = ch._sentences([unit])
    assert all(p.header == unit.header for p in pieces) and len(pieces) == 13
    # two windows cut from the same table both start with the header
    first, second = SectionChunker._with_pages(pieces[:5]), SectionChunker._with_pages(pieces[5:9])
    for w in (first, second):
        assert w.splitlines()[1].startswith("[Table: Table 2. Doses]")
        assert "Columns: Drug | Dose | Note" in w
    assert "drug5 | 5 mg | with food" in second


def test_plain_text_units_render_as_before():
    units = [Unit(1, "First sentence."), Unit(2, "Second.")]
    assert SectionChunker._with_pages(units) == "[p 1]\nFirst sentence.\n[p 2]\nSecond."


def test_printed_page_labels_come_from_the_page_itself():
    labels = printed_page_labels(PROJECT_ROOT / "docs" / "va_dod_cpg_diabetes_2023.pdf")
    assert labels[21] == "21" and labels[145] == "145"


# ---- the parse cache and figure inventory (skip if not built) ----

def _cached(doc_id):
    files = sorted((PROJECT_ROOT / "storage" / "parse_cache" / doc_id).glob("*.json"))
    if not files:
        pytest.skip("parse cache not built (scripts/parse_docs.py)")
    return json.loads(files[-1].read_text())


def test_every_embedded_image_is_inventoried_including_figures_docling_missed():
    import pymupdf
    r = _cached("va_dod_cpg_diabetes_2023")
    with pymupdf.open(PROJECT_ROOT / "docs" / "va_dod_cpg_diabetes_2023.pdf") as pdf:
        n_images = sum(1 for page in pdf for b in page.get_text("dict")["blocks"] if b["type"] == 1)
    assert len(r["figures"]) >= n_images
    p21 = [f for f in r["figures"] if f["page"] == 21]
    assert p21 and p21[0]["source"] == "pdf_image"   # docling's layout model drops this flowchart


def test_figure_inventory_gives_every_image_a_decision():
    rep = PROJECT_ROOT / "reports" / "parsing" / "FIGURES.json"
    if not rep.exists():
        pytest.skip("figure inventory not built (scripts/extract_figures.py)")
    data = json.loads(rep.read_text())
    assert all(f["decision"] in ("decorative", "vision") for f in data["figures"])
    assert all(f.get("decorative_reason") for f in data["figures"] if f["decision"] == "decorative")
    assert data["summary"]["images"] == len(data["figures"])


# ---- the built index (skip if not built) ----

def _chunks():
    if not (INDEX / "chunks.jsonl").exists():
        pytest.skip("docling index not built")
    return [json.loads(line) for line in (INDEX / "chunks.jsonl").open()]


def test_the_five_flowcharts_are_indexed_as_reviewed_decision_paths_with_provenance():
    chunks = _chunks()
    for doc_id, page in FLOWCHART_PAGES:
        fig = [c for c in chunks if c["doc_id"] == doc_id and page in c["pages"] and "figure" in c["content_types"]]
        assert fig, (doc_id, page)
        c = fig[0]
        assert c["verification"] == "reviewed" and "vision" in c["extraction"]
        assert c["source_sha256"] and c["printed_pages"] == [str(page)] and c["section"]
        assert c["bboxes"] and c["bboxes"][0][0] == page
        assert "Machine-generated visual interpretation" in c["text"]
        assert any("Decision path:" in x["text"] for x in fig) or any("-> if " in x["text"] for x in fig)


def test_flowchart_branches_survive_into_the_index():
    text = "\n".join(c["text"] for c in _chunks() if "va_dod_cpg_opioids_2022:p27:f0" in c["figure_ids"])
    assert "Box 35 (decision): Is there evidence of diversion?** -> if Yes: box 36; if No: box 37" in text
    text = "\n".join(c["text"] for c in _chunks() if "va_dod_cpg_diabetes_2023:p21:f0" in c["figure_ids"])
    assert "if Yes: box 9; if No: box 10" in text


def test_chart_values_keep_their_series():
    text = "\n".join(c["text"] for c in _chunks() if c["doc_id"] == "va_pbm_t2dm_pharmacotherapy_2025" and 5 in c["pages"])
    assert "Series SGLT2 inhibitors: MACE composite: -14; Heart failure composite: -31; Kidney composite: -45" in text


def test_recommendation_table_rows_stay_aligned_with_repeated_headers():
    rows = [c for c in _chunks() if c["doc_id"] == "va_dod_cpg_diabetes_2023" and 25 in c["pages"]
            and "table" in c["content_types"]]
    assert rows and all("Columns: Topic | Sub- topic | # | Recommendation | Strength a | Category b" in c["text"] for c in rows)
    joined = "\n".join(c["text"] for c in rows)
    # row 10's cells, in order, as printed on the page (merged Topic filled down)
    assert ("Management of Type 2 Diabetes Mellitus | Glycemic Management | 10. | We suggest an HbA1c range of "
            "7.0-8.5% for most patients, if it can be safely achieved. | Weak for | Not reviewed, Amended") in joined
