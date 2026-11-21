"""NYRx PDL row extraction and lookup. Extraction runs on the real PDF pages (fast: a few pages);
lookups run on rows extracted here, so no cached artifact is needed."""

import json
from dataclasses import asdict

import pytest

from pharmassist.agent import tools
from pharmassist.tables import match, ny_pdl


@pytest.fixture(scope="module")
def p34():
    return ny_pdl.extract([34])


@pytest.fixture(scope="module")
def p37():
    return ny_pdl.extract([37])


def by_name(rows):
    return {r.drug_name: r for r in rows}


# p34, checked by hand against the PDF: (name as printed, column, flags, marker)
P34 = [
    ("Baqsimi®", "preferred", [], None),
    ("glucagon HCl emergency kit", "preferred", [], "1"),
    ("glucagon vial", "preferred", [], None),
    ("Gvoke® pen, syringe, vial", "preferred", [], "1"),
    ("Zegalogue® pen, syringe", "preferred", [], None),
    ("exenatide", "preferred", [], None),
    ("Ozempic® pen", "preferred", [], None),
    ("Trulicity®", "preferred", [], None),
    ("Victoza®", "preferred", ["BLTG"], None),
    ("liraglutide (gen Victoza® )", "non-preferred", [], None),
    ("Mounjaro®", "non-preferred", [], None),
    ("Ozempic® tablets", "non-preferred", [], None),
    ("Rybelsus®", "non-preferred", [], None),
    ("Soliqua®", "non-preferred", [], None),
    ("Xultophy®", "non-preferred", [], None),
]


def test_p34_fixture_rows_columns_flags_and_markers(p34):
    got = [(r.drug_name, r.status, r.flags, (r.marker or {}).get("code")) for r in p34]
    assert got == P34


def test_p34_classes_and_coverage_parameters(p34):
    glp1 = [r for r in p34 if r.drug_class.startswith("Glucagon-Like Peptide-1")]
    assert len(glp1) == 10
    assert glp1[0].drug_class == "Glucagon-Like Peptide-1 (GLP-1) Receptor Agonists – Type 2 Diabetes"
    assert glp1[0].class_flags == ["CC"] and glp1[0].section == "VI. Endocrine and Metabolic Agents"
    assert "PA required for patients utilizing a GLP-1 and DPP-IV concurrently" in glp1[0].coverage_parameters
    assert glp1[0].coverage_pages == [34]


def test_p37_markers_and_their_meaning(p37):
    rows = by_name(p37)
    humalog = rows["Humalog® 100 U/mL vial, pen, cartridge"]
    assert humalog.status == "preferred" and humalog.marker["code"] == "1"
    assert humalog.marker["becomes"] == "preferred" and humalog.marker["effective_date"] == "2026-10-22"
    aspart = rows["insulin aspart cartridge, vial, pen (gen Novolog® )"]
    assert aspart.status == "non-preferred" and aspart.marker["becomes"] == "non-preferred"
    assert sum(1 for r in p37 if r.marker) == 3


def test_multi_line_names_are_joined(p37):
    names = {r.drug_name for r in p37}
    assert "insulin lispro vial, pen (gen Humalog® U100)" in names
    assert "dapagliflozin/metformin (gen Xigduo® XR)" in names
    assert "Fiasp® Penfill, FlexTouch, Pumpcart, vial" in names
    assert not any(n.startswith(("cartridge", "Pumpcart", "Humalog® U100)")) for n in names)


def test_wrap_across_table_rows_and_small_flags():
    p17 = by_name(ny_pdl.extract([17]))
    assert "risperidone injection (gen Risperdal Consta® )" in p17 and "Consta® )" not in p17
    p4 = by_name(ny_pdl.extract([4]))
    assert p4["meloxicam capsule (gen Vivlodex® )"].flags == ["MR"]  # 'MR' alone on the next line, small
    assert "MR" not in p4


def test_page_provenance_and_stable_ids(p34):
    assert [r.row_id for r in p34[:2]] == ["ny_medicaid_pdl#p34#row-1", "ny_medicaid_pdl#p34#row-2"]
    assert all(r.page == 34 and r.extraction_method == ny_pdl.METHOD for r in p34)
    assert ny_pdl.extract([34])[6].row_id == p34[6].row_id  # same input, same ids


def test_class_continues_across_pages_only_when_clear():
    rows = ny_pdl.extract([14, 15, 16])
    p16 = [r for r in rows if r.page == 16 and r.drug_name.startswith("topiramate 50mg")][0]
    p14_class = [r for r in rows if r.page == 14][-1]
    assert p16.continued_from_page == 14 and p16.drug_class == p14_class.drug_class
    assert p16.coverage_pages == [14, 15, 16]
    # a new heading on p16 starts a new class, not a continuation
    aimovig = [r for r in rows if r.drug_name == "Aimovig®"][0]
    assert aimovig.drug_class == "Antimigraine Agents, Other" and aimovig.continued_from_page is None


def test_no_continuation_without_the_previous_page():
    rows = ny_pdl.extract([16])
    first = rows[0]
    assert first.drug_class == "(class heading not on this page)" and first.continued_from_page is None


def test_coverage_only_rows_on_the_next_page_join_the_class():
    rows = ny_pdl.extract([16, 17])
    other = [r for r in rows if r.drug_class == "Antimigraine Agents, Other"][0]
    assert other.coverage_pages == [16, 17] and "30 units/30 days" in other.coverage_parameters


# ---- lookup over rows extracted from p34 and p37 ----

@pytest.fixture
def pdl_rows(monkeypatch, p34, p37):
    rows = [asdict(r) for r in p34 + p37]
    monkeypatch.setattr(ny_pdl, "load", lambda: rows)
    return rows


def names(result):
    return [x["drug_name"] for c in result.get("classes", []) for x in c["rows"]]


def test_lookup_exact_and_multiple(pdl_rows):
    assert ny_pdl.lookup("Ozempic pen")["result"] == match.EXACT
    r = ny_pdl.lookup("ozempic")
    assert r["result"] == match.MULTIPLE and names(r) == ["Ozempic® pen", "Ozempic® tablets"]
    statuses = {x["drug_name"]: x["listed_as"] for c in r["classes"] for x in c["rows"]}
    assert statuses == {"Ozempic® pen": "preferred", "Ozempic® tablets": "non-preferred"}


def test_lookup_finds_the_generic_the_pdl_states(pdl_rows):
    r = ny_pdl.lookup("Victoza")
    rows = {x["drug_name"]: x for c in r["classes"] for x in c["rows"]}
    assert rows["liraglutide (gen Victoza® )"]["matched_on"].startswith("generic of Victoza")
    assert rows["Victoza®"]["flags"] == {"BLTG": "Brand Less Than Generic Program (PDL pages 77–78)"}


def test_lookup_name_plus_strength(pdl_rows):
    assert names(ny_pdl.lookup("Humalog 200")) == ["Humalog® 200 U/mL"]


def test_lookup_marker_text_says_what_applies_before_the_date(pdl_rows):
    r = ny_pdl.lookup("insulin aspart")
    marker = r["classes"][0]["rows"][0]["effective_date_marker"]
    assert "non-preferred from that date, preferred before it" in marker


def test_lookup_class_match_gives_coverage_once(pdl_rows):
    r = ny_pdl.lookup("GLP-1")
    assert r["result"] == match.CLASS and len(r["classes"]) == 1
    assert "DPP-IV concurrently" in r["classes"][0]["coverage_parameters"] and len(names(r)) == 10


def test_lookup_no_match_is_not_a_negative_finding(pdl_rows):
    r = ny_pdl.lookup("amoxicillin")
    assert r["result"] == match.NO_MATCH and "doesn't mean it isn't on the PDL or isn't covered" in r["note"]
    assert "pages 61–86" in r["note"] and "search_documents" in r["note"]  # the lookup's scope is stated


def test_lookup_fuzzy_is_only_a_suggestion(pdl_rows):
    r = ny_pdl.lookup("Ozempik")
    assert r["result"] == match.FUZZY and "classes" not in r and r["suggestions"]


def test_glp1_prior_auth_finds_ny_pdl(pdl_rows):
    """Was a strict xfail: hybrid search alone doesn't rank the PDL for this. The agent's PDL lookup
    now finds the GLP-1 class row on p34 with its PA criterion, and the page passes the citation check."""
    from pharmassist.config import PROJECT_ROOT, load_config
    from tests.test_agent_fakes import FakeStore
    rows_file = PROJECT_ROOT / "index" / "tables" / "ny_pdl_rows.jsonl"
    if not rows_file.exists():
        pytest.skip("needs the extracted PDL rows (index/tables/ny_pdl_rows.jsonl)")
    rows = [{**json.loads(line), "row": i, "drug": json.loads(line).get("drug_name")}
            for i, line in enumerate(rows_file.open(), 1)]
    box = tools.ToolBox(FakeStore(tables={"ny_pdl": rows}), embed=None, cfg=load_config(), structured=True)
    text, is_error = box.run("lookup_ny_medicaid_drug", {"drug": "GLP-1"})
    r = json.loads(text)
    assert not is_error and r["result"] == match.CLASS
    assert "PA required for patients utilizing a GLP-1 and DPP-IV concurrently" in r["classes"][0]["coverage_parameters"]
    assert "ny_medicaid_pdl:p34" in box.seen
