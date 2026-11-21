"""VA National Formulary rows and lookup, against the real spreadsheet (it loads in under a second)."""

import openpyxl
import pytest

from pharmassist.tables import match
from pharmassist.tables import va_formulary as v


def rows_of(result):
    return [r["row"] for r in result.get("rows", [])]


def test_header_and_notes_are_found_by_content_not_position():
    f = v.load()
    assert (f.header_row, f.rule_row, f.pa_row) == (16, 7, 9)
    assert "dosage form specific" in f.notes[7] and "PA-F" in f.notes[9]
    assert len(f.rows) == 1982 and f.rows.index.min() == 17


def test_exact_match_keeps_original_values_and_provenance():
    r = v.lookup("semaglutide")
    assert r["result"] == match.EXACT and rows_of(r) == [1697]
    row = r["rows"][0]
    assert row["Generic"] == "SEMAGLUTIDE (EQV-OZEMPIC)" and row["Restriction"] == "PA-F"
    assert row["Dosage Form"] == "INJ,SOLN" and row["Clinical Guidance"] == "Criteria"
    assert row["row_id"] == "va_national_formulary_2026_09#Formulary#row-1697"
    assert row["cite"] == {"doc_id": "va_national_formulary_2026_09", "row": 1697}
    # the row number is the spreadsheet's own: check the cell directly
    ws = openpyxl.load_workbook(v._path(), read_only=True)["Formulary"]
    assert next(ws.iter_rows(min_row=1697, max_row=1697, max_col=3, values_only=True))[2] == row["Generic"]


@pytest.mark.parametrize("query", ["SEMAGLUTIDE", "  semaglutide ", "Semaglutide\xa0"])
def test_case_and_whitespace_dont_matter(query):
    assert rows_of(v.lookup(query)) == [1697]


def test_brand_matches_only_where_the_row_states_it():
    r = v.lookup("Ozempic")
    assert rows_of(r) == [1697] and r["rows"][0]["matched_on"].startswith("brand stated in the row")
    assert v.lookup("Victoza")["result"] != match.EXACT  # no EQV-VICTOZA row: never mapped silently


def test_multiple_formulations_are_all_returned():
    r = v.lookup("buprenorphine")
    assert r["result"] == match.MULTIPLE
    assert rows_of(r) == [301, 302, 303, 304, 305, 306]
    combo = next(x for x in r["rows"] if x["row"] == 306)
    assert combo["matched_on"] == "combination product containing buprenorphine"


def test_dosage_form_narrows_and_unlisted_form_cites_the_rule():
    assert rows_of(v.lookup("buprenorphine", dosage_form="patch")) == [304]
    r = v.lookup("buprenorphine/naloxone", dosage_form="film")
    assert r["result"] == match.FORM_NOT_LISTED and rows_of(r) == [306]
    assert "row 7" in r["note"] and "non-formulary" in r["note"]
    assert r["rule"]["cite"] == {"doc_id": "va_national_formulary_2026_09", "row": 7}


def test_strength_is_checked_against_the_row_not_used_to_filter():
    r = v.lookup("buprenorphine 8 mg", dosage_form="sublingual tablet")
    by_row = {x["row"]: x["strength"] for x in r["rows"]}
    assert by_row[305] == "8 mg stated in this row"            # 'Yes 2mg and 8mg only'
    assert by_row[306].startswith("8 mg not stated")            # '8mg/2mg' is a combination strength


def test_salt_names_match_and_say_so():
    r = v.lookup("metformin")
    assert 1231 in rows_of(r)
    salt = next(x for x in r["rows"] if x["row"] == 1231)
    assert salt["matched_on"].startswith("same drug, salt named in the row")


def test_missing_drug_is_no_match_not_a_negative_finding():
    r = v.lookup("zzzzolam")
    assert r["result"] == match.NO_MATCH and "rows" not in r
    assert "doesn't mean the drug is non-formulary" in r["note"]


def test_no_silent_fuzzy_pick():
    r = v.lookup("metfromin")
    assert r["result"] == match.FUZZY and r["suggestions"] == ["metformin"]
    assert "rows" not in r and "not matches" in r["note"]


def test_row_text_for_the_judge():
    assert "Restriction: PA-F" in v.row_text(1697)
    assert v.row_text(7).startswith("Note row 7: The VANF is dosage form specific")
    assert v.row_text(16).startswith("Header row: VA Class")
