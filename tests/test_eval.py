"""Eval scoring, rows and the judge's request shape, with no API calls."""

import json
from types import SimpleNamespace as NS

import pytest

from pharmassist.eval import report, scoring
from pharmassist.eval.judge import ACCURACY_SCHEMA, judge_accuracy, judge_groundedness

ECFG = {"judge_model": "claude-opus-5-5", "judge_effort": "medium", "judge_max_tokens": 8000,
        "page_chars": 8000, "prices_per_mtok": {"input": 4.0, "output": 20.0, "cache_read": 0.2,
                                                "cache_write": 5.0}}

Q11 = {"id": "Q11", "type": "coverage", "program": "unspecified (assumed NY Medicaid)",
       "question": "Ozempic pen: preferred or PA?", "expected_answer": "Preferred ...", "notes": "",
       "must_include": ["Assuming NY Medicaid", "preferred", "DPP-4 concurrently"], "answerable": True,
       "gold": [{"doc_id": "ny_medicaid_pdl", "page": 34},
                {"doc_id": "va_national_formulary_2026_09", "sheet": "Formulary", "cells": "A9"}]}


def result(**kw):
    base = {"status": "answered", "assumption": "Assuming NY Medicaid",
            "answer": "Assuming NY Medicaid: **Ozempic pen is preferred**; PA if a DPP-4 is used concurrently.",
            "citations": [{"doc_id": "ny_medicaid_pdl", "page": 34, "flag": None},
                          {"doc_id": "ny_medicaid_pdl", "page": 78, "flag": None}],
            "pages_seen": ["ny_medicaid_pdl:p34", "ny_medicaid_pdl:p78"], "flags": [],
            "timing_s": {"total": 6.0, "search": 0.1, "read_page": 0.0, "model_calls": [2.0, 3.9]},
            "index_warm_at_start": True, "lookups": 1, "cost_usd": 0.02, "trace_path": "traces/x.json"}
    return {**base, **kw}


def test_gold_becomes_page_and_row_locators():
    gold = Q11["gold"] + [{"doc_id": "va_national_formulary_2026_09", "sheet": "Formulary", "cells": "C304:D306"}]
    loc = scoring.gold_locators(gold)
    assert loc == {"ny_medicaid_pdl:p34", "va_national_formulary_2026_09:r9",
                   "va_national_formulary_2026_09:r304", "va_national_formulary_2026_09:r305",
                   "va_national_formulary_2026_09:r306"}
    assert scoring.pages_only(loc) == {"ny_medicaid_pdl:p34"}


def test_retrieval_and_citation_scores():
    gold = {"a:p1", "a:p2"}
    assert scoring.retrieval(gold, {"a:p1", "b:p9"})["recall"] == 0.5
    assert scoring.citation_scores(gold, {"a:p1", "b:p9"}) == {"precision": 0.5, "recall": 0.5}
    assert scoring.citation_scores(set(), set()) == {"precision": None, "recall": None}


def test_recall_at_k_counts_the_pages_of_the_top_units():
    ranked = [["a:p1"], ["a:p1"], ["b:p2"], ["c:p3"], ["d:p4"], ["e:p5", "a:p2"]]
    assert scoring.recall_at_k({"a:p1", "a:p2"}, ranked, 5) == 0.5   # a:p2 is in the 6th unit
    assert scoring.recall_at_k({"a:p1", "a:p2"}, ranked, 10) == 1.0  # a section covers 2 pages
    assert scoring.recall_at_k(set(), ranked, 5) is None


@pytest.mark.parametrize("grades, expected", [
    (["correct", "correct", "partial"], "correct"), (["partial", "incorrect", "incorrect"], "incorrect"),
    (["correct", "partial", "incorrect"], "partial"), (["correct"], "correct")])
def test_majority_grade(grades, expected):
    assert scoring.majority_grade(grades) == expected


@pytest.mark.parametrize("accuracy, seen, cited, rows_ingested, expected", [
    ("partial", {"a:p1"}, set(), False, scoring.NOT_INGESTED),     # the row can't be read
    ("partial", {"a:p1"}, set(), True, scoring.NOT_RETRIEVED),     # readable, never returned
    ("incorrect", {"a:p1", "f:r9"}, set(), True, scoring.ANSWERED_WRONG),
    ("correct", {"a:p1", "f:r9"}, {"a:p1"}, True, scoring.CITED_WRONG),
    ("correct", {"a:p1", "f:r9"}, {"a:p1", "f:r9"}, True, None),
])
def test_failure_classes(accuracy, seen, cited, rows_ingested, expected):
    assert scoring.classify(accuracy, {"a:p1", "f:r9"}, seen, cited, rows_ingested)[0] == expected


@pytest.mark.parametrize("answerable, status, ok", [
    (True, "answered", True), (True, "not_in_documents", False), (True, "out_of_scope", False),
    (False, "not_in_documents", True), (False, "answered", False)])
def test_abstention(answerable, status, ok):
    assert scoring.abstention_ok(answerable, status) is ok


def test_assumption_check():
    p = Q11["program"]
    # the agent's fixed header, with claims that name the program, passes
    assert scoring.assumption_ok(p, "Coverage program not specified\n\n- Under NY Medicaid, the Ozempic pen is "
                                    "preferred. [ny_medicaid_pdl p34]", "Coverage program not specified")
    # the fixed header alone doesn't: the claims must say which program they apply to
    assert not scoring.assumption_ok(p, "Coverage program not specified\n\n- The pen is preferred.", None)
    # older runs' "Assuming <program>" openings still pass
    assert scoring.assumption_ok(p, "**Assuming NYRx (NY Medicaid):** preferred.", "NY Medicaid")
    assert not scoring.assumption_ok(p, "Ozempic is preferred. Assuming NY Medicaid.", "NY Medicaid")
    assert scoring.assumption_ok("VA", "anything", None) is None


@pytest.mark.parametrize("answerable, status, over", [
    (True, "unverified", True), (True, "not_in_documents", True), (True, "answered", False),
    (False, "unverified", False), (False, "not_in_documents", False)])
def test_over_abstention(answerable, status, over):
    assert scoring.over_abstained(answerable, status) is over


def test_word_count_ignores_markdown_tables():
    md = "Two words\n\n| Drug | PA |\n|---|---|\n| Ozempic | no |"
    assert scoring.word_count(md) == 6


def test_must_include_substring_is_case_and_quote_insensitive():
    assert scoring.must_include_substring(["Don't bill NYRx", "DAW 9"], "don’t bill nyrx; use daw 1") == [True, False]


def test_build_row_scores_a_question():
    acc = {"grade": "partial", "reason": "Misses the DPP-4 rule.",
           "must_include": [{"term": t, "present": t != "DPP-4 concurrently"} for t in Q11["must_include"]]}
    grounded = {"claims": [{"claim": "preferred", "verdict": "supported", "page": "ny_medicaid_pdl:p34", "note": ""},
                           {"claim": "no QL", "verdict": "unsupported", "page": None, "note": "not on p34"}]}
    calls = [{"name": "search_documents", "pages": ["ny_medicaid_pdl:p34", "ny_medicaid_pdl:p78"]}]
    row = report.build_row(Q11, result(), acc, grounded, 0.05, (60, 120), tool_calls=calls,
                           ranked=[["x:p1"], ["ny_medicaid_pdl:p34"]])
    # gold: PDL p34 and formulary row 9, which no tool returned
    assert row["retrieval_recall"] == 0.5 and row["retrieval_recall_pages"] == 1.0
    assert row["gold_rows"] == 1 and row["recall_at_5"] == 1.0
    assert row["citation_precision"] == 0.5 and row["citation_recall"] == 0.5
    assert row["citation_recall_pages"] == 1.0
    assert row["evidence_tools"].startswith("ny_medicaid_pdl:p34 <- search_documents")
    assert row["failure_class"] == scoring.NOT_INGESTED  # partial, and row 9 is unreadable here
    assert row["groundedness"] == 0.5 and "no QL (unsupported: not on p34)" in row["unsupported_claims"]
    assert row["must_include_judge"] == "2/3" and row["missing_terms"] == "DPP-4 concurrently"
    assert row["assumption_ok"] is True and row["abstention_ok"] is True
    assert row["words_in_range"] is False and set(row) <= set(report.CSV_FIELDS)


def test_groundedness_labels_uncited_and_abstained():
    acc = {"grade": "correct", "reason": "ok", "must_include": []}
    assert report.build_row(Q11, result(citations=[]), acc, None, 0, (60, 120))["groundedness"] == "uncited"
    abstained = report.build_row(Q11, result(status="not_in_documents", citations=[]), acc, None, 0, (60, 120))
    assert abstained["groundedness"] == "n/a" and abstained["abstention_ok"] is False


def test_lowest_ranks_accuracy_then_groundedness():
    rows = [{"id": "A", "accuracy": "correct", "groundedness": 0.2},
            {"id": "B", "accuracy": "partial", "groundedness": 1.0},
            {"id": "C", "accuracy": "correct", "groundedness": "n/a"},
            {"id": "D", "accuracy": "correct", "groundedness": "uncited"},
            {"id": "E", "accuracy": "error"}]
    assert [r["id"] for r in report.lowest(rows, 5)] == ["E", "B", "D", "A", "C"]


def test_citable_drops_unknown_docs_and_pages():
    cites = [{"doc_id": "ny_medicaid_pdl", "page": 34}, {"doc_id": "ny_medicaid_pdl", "page": 999},
             {"doc_id": "made_up", "page": 1}, {"doc_id": "va_national_formulary_2026_09", "page": 1}]
    assert report.citable(cites) == ["ny_medicaid_pdl:p34"]
    rows = [{"doc_id": "va_national_formulary_2026_09", "page": None, "row": r} for r in (1697, 7, 99999)]
    assert report.citable(rows) == ["va_national_formulary_2026_09:r1697", "va_national_formulary_2026_09:r7"]


class FakeJudge:
    def __init__(self, payload):
        self.payload, self.requests = payload, []
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kw):
        self.requests.append(kw)
        usage = NS(input_tokens=1000, output_tokens=100, cache_read_input_tokens=0,
                   cache_creation_input_tokens=0)
        return NS(stop_reason="end_turn", usage=usage,
                  content=[NS(type="thinking"), NS(type="text", text=json.dumps(self.payload))])


def test_accuracy_judge_uses_structured_output_and_sees_the_reference():
    payload = {"grade": "correct", "reason": "Matches.", "must_include": []}
    client = FakeJudge(payload)
    out, cost = judge_accuracy(client, ECFG, Q11, result(), "2026-10-14")
    req = client.requests[0]
    assert out == payload and cost == pytest.approx(0.006)  # 1000*4 + 100*20 per million
    assert req["model"] == "claude-opus-5-5" and "tool_choice" not in req
    assert req["output_config"]["format"] == {"type": "json_schema", "schema": ACCURACY_SCHEMA}
    user = req["messages"][0]["content"]
    assert "Reference answer: Preferred" in user and "2026-10-14" in user


def test_groundedness_judge_sees_page_text_but_not_the_reference():
    client = FakeJudge({"claims": []})
    judge_groundedness(client, ECFG, result(), ["ny_medicaid_pdl:p34", "va_national_formulary_2026_09:r1697"],
                       "2026-10-14")
    req = client.requests[0]
    user = req["messages"][0]["content"]
    assert "=== ny_medicaid_pdl:p34 ===" in user and "Ozempic" in user
    # catalog details and the formulary row's columns are there; the reference answer isn't
    assert "authority: binding | date: 2026-09-14" in user and "Today's date: 2026-10-14" in user
    assert "Generic: SEMAGLUTIDE (EQV-OZEMPIC)" in user and "Restriction: PA-F" in user
    assert "Reference" not in user and Q11["expected_answer"] not in user
    assert "precedence rules" in req["system"] and "no outside knowledge" in req["system"]


def test_accuracy_judge_is_told_to_use_no_outside_knowledge():
    from pharmassist.eval.judge import ACCURACY_SYSTEM
    assert "Use no outside knowledge" in ACCURACY_SYSTEM


def test_abstaining_on_an_answerable_question_is_over_abstention_and_not_correct():
    acc = {"grade": "correct", "reason": "declined appropriately", "must_include": []}
    r = report.build_row(Q11, result(status="unverified", citations=[], verification={"outcome": "abstained"}),
                         acc, None, 0, (60, 120))
    assert r["over_abstention"] is True and r["accuracy"] == "incorrect"
    assert r["safe"] is True and r["useful"] is False


def test_abstaining_on_an_unanswerable_question_is_correct():
    q = {**Q11, "answerable": False}
    acc = {"grade": "partial", "reason": "x", "must_include": []}
    r = report.build_row(q, result(status="unverified", citations=[]), acc, None, 0, (60, 120))
    assert r["over_abstention"] is False and r["accuracy"] == "correct"


def test_safe_and_useful_follow_the_judge_and_the_outcome():
    acc = {"grade": "correct", "reason": "ok", "must_include": []}
    clean = {"claims": [{"claim": "preferred", "verdict": "supported", "page": "ny_medicaid_pdl:p34", "note": ""}]}
    dirty = {"claims": [{"claim": "no QL", "verdict": "unsupported", "page": None, "note": "x"}]}
    ok = report.build_row(Q11, result(verification={"outcome": "answered", "direct_label": "values_checked"}),
                          acc, clean, 0, (60, 120))
    unsafe = report.build_row(Q11, result(verification={"outcome": "answered", "direct_label": "values_checked"}),
                              acc, dirty, 0, (60, 120))
    abstained = report.build_row(Q11, result(status="unverified", citations=[], verification={"outcome": "abstained"}),
                                 acc, None, 0, (60, 120))
    assert (ok["safe"], ok["useful"]) == (True, True)
    assert (unsafe["safe"], unsafe["useful"]) == (False, True)
    assert (abstained["safe"], abstained["useful"], abstained["over_abstention"]) == (True, False, True)
    s = report.summarize([ok, unsafe, abstained])
    assert s["safe"] == "2/3" and s["useful"] == "2/3" and s["over_abstention"] == 1
    assert s["direct_labels"] == {"verified": 0, "values_checked": 2, "unchecked": 0}


def _run_eval_module():
    import importlib.util

    from pharmassist.config import PROJECT_ROOT
    spec = importlib.util.spec_from_file_location("run_eval", PROJECT_ROOT / "scripts" / "run_eval.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_offline_checks_are_off_by_default_and_stored_without_touching_the_answer(tmp_path, monkeypatch):
    import json as _json
    from types import SimpleNamespace as NS

    from pharmassist.config import load_config
    re_ = _run_eval_module()
    ecfg = load_config()["eval"]
    assert ecfg["claim_audit"]["enabled"] is False and ecfg["offline_checks"]["enabled"] is False
    monkeypatch.setattr(re_, "PROJECT_ROOT", tmp_path)
    answer = "Under NY Medicaid, Trulicity is preferred.\n\n- Under NY Medicaid, check eGFR >=30 first."
    evidence = "ny_medicaid_pdl (NY Medicaid, binding, 2026-09-14)\nTrulicity preferred"
    trace = {"question": "Is Trulicity preferred?", "answer": answer, "status": "answered",
             "started_at": "2026-10-17T10:00:00+00:00",
             "citations": [{"doc_id": "ny_medicaid_pdl", "page": 34, "locator": "ny_medicaid_pdl:p34"}],
             "cited_evidence": {"ny_medicaid_pdl:p34": evidence},
             "cited_evidence_parts": {"ny_medicaid_pdl:p34": [evidence]}}
    (tmp_path / "t.json").write_text(_json.dumps(trace))
    result = {"trace_path": "t.json", "answer": answer, "status": "answered"}
    off = {"claim_audit": {"enabled": False}, "offline_checks": {"enabled": False}}
    assert re_.run_audit(None, off, Q11, result, trace) is None

    # deterministic checks only: no client is used
    out = re_.run_audit(None, {**off, "offline_checks": {"enabled": True}}, Q11, result, trace)
    assert out["offline_check_flagged"] == 1 and out["offline_checks"].startswith("sentence 2: ")
    assert "claim_audit" not in out

    verdicts = [{"claim": n, "verdict": v, "unsupported_words": "", "self_contained": True, "reason": "ok"}
                for n, v in ((1, "supported"), (2, "unsupported"))]
    def create(**kw):
        return NS(content=[NS(type="text", text=_json.dumps({"verdicts": verdicts}))], stop_reason="end_turn",
                  model=kw["model"], usage=NS(input_tokens=1000, output_tokens=100, cache_read_input_tokens=0,
                                              cache_creation_input_tokens=0))
    client = NS(beta=NS(messages=NS(create=create)))
    acfg = {"enabled": True, "model": "claude-sonnet-5-5", "prices_per_mtok": {"input": 2, "output": 10, "cache_read": 0.2,
                                                                                "cache_write": 2.5}}
    out = re_.run_audit(client, {**off, "claim_audit": acfg}, Q11, result, trace)
    assert out["claim_audit"] == "sentence 1: supported; sentence 2: unsupported"
    assert out["audit_cost_usd"] == pytest.approx(0.003) and out["offline_check_flagged"] == 1
    assert (out["audit_shown"], out["audit_shown_unsupported"], out["audit_shown_partial"]) == (2, 1, 0)
    saved = _json.loads((tmp_path / "t.json").read_text())
    assert [v["verdict"] for v in saved["claim_audit"]["verdicts"]] == ["supported", "unsupported"]
    assert saved["answer"] == answer and result["answer"] == answer      # the answer is untouched

    def boom(**kw):
        raise TimeoutError("audit timed out")
    broken = NS(beta=NS(messages=NS(create=boom)))
    out = re_.run_audit(broken, {**off, "claim_audit": acfg}, Q11, result, trace)
    assert out["claim_audit"].startswith("audit error: TimeoutError") and out["audit_cost_usd"] == 0.0
    assert result["answer"] == answer and _json.loads((tmp_path / "t.json").read_text())["answer"] == answer


def test_run_eval_warms_up_before_the_first_question_and_reports_startup_separately(tmp_path, monkeypatch):
    import sys
    re_ = _run_eval_module()
    order = []
    startup = {"steps_s": {"index": 0.1}, "total_s": 0.1, "error": None, "index_warm": True}
    monkeypatch.setattr(re_, "make_client", lambda: None)
    monkeypatch.setattr(re_, "build_stack", lambda cfg, label, dsn=None: re_.Stack(cfg, None, None, label))
    monkeypatch.setattr(re_, "warm_up", lambda stack: order.append("warmup") or startup)

    def run_agent(questions, *a):
        order.append("questions")
        yield from ()

    monkeypatch.setattr(re_, "run_agent", run_agent)
    from pharmassist.config import PROJECT_ROOT, load_config
    golden = load_config()["eval"]["golden"]
    (tmp_path / golden).parent.mkdir(parents=True)
    (tmp_path / golden).write_text((PROJECT_ROOT / golden).read_text())
    monkeypatch.setattr(re_, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(re_, "project_path", lambda name: tmp_path)
    monkeypatch.setattr(sys, "argv", ["run_eval.py", "--ids", "Q01"])
    re_.main()
    assert order == ["warmup", "questions"]
    summary = next(tmp_path.glob("evals/*/summary.md")).read_text()
    assert "Startup warmup before timing (not in any latency) | 0.1 s (index 0.1 s)" in summary
