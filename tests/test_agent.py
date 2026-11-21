"""Agent loop tests over a real Router with scripted fake providers, an in-memory store and a search
stub: no API calls, no index, no database."""

import hashlib
import json

import pytest

from pharmassist.agent import loop, offline, tools
from pharmassist.agent import verify as V
from pharmassist.agent.loop import (BUDGET_SPENT, COMPLETENESS_CHECK, LOOKUPS_CLOSED, MIN_LOOKUPS_NUDGE, SUBMIT_NUDGE,
                                    SUBMIT_RECEIVED, ask)
from pharmassist.llm.base import AllProvidersFailed, Message, TextPart, ToolResult
from pharmassist.store.protocols import NO_ANSWER_TEXT
from tests.test_agent_fakes import (CFG, COMPLETE_CFG, PRICES, QUESTION, REFUSAL, STRUCTURED_CFG, TABLES, FakeSearch,
                                    FakeStore, error, make_router, make_tools, pdf, reply, submit, submit_rows, text, tool)

_ = pdf  # the fixture
NUDGE_CFG = {**CFG, "agent": {**CFG["agent"], "min_lookups": 2}}          # the min-lookups nudge alone
PASS_CFG = {**CFG, "agent": {**CFG["agent"], "completeness_pass": True}}  # the completeness pass alone
P34 = [("ny_medicaid_pdl", 34)]
FIRST = "Ozempic pen is preferred."
FULLER = "Ozempic pen is preferred. A trial of metformin is required first."


def run(router, box=None, cfg=CFG, **kw):
    box = box or make_tools(cfg=cfg)
    r = ask(QUESTION, router=router, tools=box, cfg=cfg, save_trace=False, **kw)
    r["_tools"] = box
    return r


def sent(router, i=0):
    """The i-th request the primary saw."""
    return router.fake_primary.requests[i]


# ---- citations and the no-answer rule ----

def test_submit_with_seen_citation_is_answered_with_link_provider_and_model():
    router = make_router(reply(tool("search_documents", query="Ozempic", program="NY Medicaid")),
                         reply(submit([("ny_medicaid_pdl", 34)])))
    r = run(router)
    assert r["status"] == r["agent_status"] == "answered" and r["flags"] == []
    assert r["_tools"].fake_search.calls[0]["program"] == "NY Medicaid"
    c = r["citations"][0]
    assert c["flag"] is None and c["link"].endswith("NYRx_PDP_PDL.pdf#page=34")
    assert (r["provider"], r["model"], r["fallback_used"]) == ("openai", "gpt-5.5", False)
    assert r["answered_by"] == "gpt-5.5" and r["trace_id"] is None and r["request_id"]


def test_citation_to_page_no_tool_returned_is_flagged_but_a_supported_one_keeps_the_answer():
    router = make_router(reply(tool("search_documents", query="Ozempic")),
                         reply(submit([("ny_medicaid_pdl", 34), ("ny_medicaid_pdl", 77), ("made_up_doc", 1)])))
    r = run(router)
    flags = {(c["doc_id"], c["page"]): c["flag"] for c in r["citations"]}
    assert flags[("ny_medicaid_pdl", 34)] is None
    assert flags[("ny_medicaid_pdl", 77)] == "not returned by any tool during this question"
    assert flags[("made_up_doc", 1)] == "unknown doc_id"
    assert "unverified_citation" in r["flags"] and r["status"] == "answered" and r["needs_review"] is True


def test_no_answer_rule_when_the_model_did_not_answer():
    """Branch 1: agent_status != answered, even with a returned citation."""
    router = make_router(reply(tool("search_documents", query="Ozempic")),
                         reply(submit([("ny_medicaid_pdl", 34)], status="not_in_documents", answer="Not covered here.")))
    r = run(router)
    assert r["status"] == "no_answer" and r["agent_status"] == "not_in_documents"
    assert r["answer"] == NO_ANSWER_TEXT and r["citations"] == [] and r["assumption"] is None
    assert r["conflicts_noted"] == [] and r["needs_review"] is True and "no_answer_rule" in r["flags"]


def test_no_answer_rule_when_no_citation_survives_the_check():
    """Branch 2: the model answered, but every citation is flagged."""
    router = make_router(reply(tool("search_documents", query="Ozempic")),
                         reply(submit([("ny_medicaid_pdl", 77), ("made_up_doc", 1)], answer="Preferred.")))
    r = run(router)
    assert r["status"] == "no_answer" and r["agent_status"] == "answered" and r["answer"] == NO_ANSWER_TEXT
    assert r["citations"] == [] and {"unverified_citation", "no_answer_rule"} <= set(r["flags"])


def test_no_answer_rule_when_the_model_cites_nothing():
    """Branch 3: answered without citations."""
    r = run(make_router(reply(submit([], answer="Preferred."))))
    assert r["status"] == "no_answer" and r["agent_status"] == "answered" and r["answer"] == NO_ANSWER_TEXT
    assert r["citations"] == [] and r["flags"] == ["no_answer_rule"]


def test_out_of_scope_is_a_no_answer_with_the_fixed_text():
    r = run(make_router(reply(submit([], status="out_of_scope", answer="Not a pharmacy question."))))
    assert r["status"] == "no_answer" and r["agent_status"] == "out_of_scope" and r["answer"] == NO_ANSWER_TEXT


def test_read_page_counts_as_seen_for_citations(pdf):
    router = make_router(reply(tool("read_page", doc_id="ny_medicaid_pdl", page=78)),
                         reply(submit([("ny_medicaid_pdl", 78)])))
    r = run(router, make_tools(pdf_path=lambda d: pdf))
    assert r["citations"][0]["flag"] is None and r["status"] == "answered"
    result = sent(router, 1)["messages"][-1].parts[0]
    assert isinstance(result, ToolResult) and result.content.startswith("ny_medicaid_pdl page 78 (NY Medicaid, binding,")
    assert "(page 78)" in result.content


# ---- budget, deadline, nudge ----

def test_tool_call_cap_stops_lookups_and_tells_model_to_submit():
    # the model asks for 4 searches per turn; only 6 may run in total
    many = lambda: reply(*[tool("search_documents", query=f"q{i}") for i in range(4)])
    router = make_router(many(), many(), many(), reply(submit([("ny_medicaid_pdl", 34)])))
    r = run(router)
    search = r["_tools"].fake_search
    assert len(search.agent_calls()) == 6 and r["lookups"] == 6
    assert len(search.calls) == 7  # plus the original question, searched once and then cached
    # second turn: 2 run, 2 refused with an error result; the budget note follows those results as a user turn
    *_, second_results, note = sent(router, 2)["messages"]
    assert [x.is_error for x in second_results.parts] == [False, False, True, True]
    assert note == Message("user", [TextPart(BUDGET_SPENT)])
    # the third turn's lookups all get the budget error, and the note isn't repeated
    third_results = sent(router, 3)["messages"][-1].parts
    assert all(x.is_error and x.content == BUDGET_SPENT for x in third_results)
    assert sum(m.text == BUDGET_SPENT for m in sent(router, 3)["messages"]) == 1
    assert "budget_spent:tool_cap" in r["flags"] and r["status"] == "answered"


def test_deadline_sends_budget_note_and_refuses_further_lookups():
    now = [0.0]

    def slow_model():
        now[0] += 26.0  # one slow call pushes past the 25 s deadline

    router = make_router(reply(tool("search_documents", query="a")), reply(tool("search_documents", query="b")),
                         reply(submit([("ny_medicaid_pdl", 34)])), on_call=slow_model)
    r = run(router, clock=lambda: now[0])
    assert len(r["_tools"].fake_search.agent_calls()) == 1  # the search requested after the deadline never ran
    assert sent(router, 1)["messages"][-1] == Message("user", [TextPart(BUDGET_SPENT)])
    assert "budget_spent:deadline" in r["flags"]
    # each request's timeout is what's left of the 30 s, capped at llm.call_timeout_s and floored at 5 s
    assert sent(router, 0)["timeout_s"] == 25 and sent(router, 1)["timeout_s"] == 5.0


def test_request_prefix_is_append_only():
    router = make_router(reply(tool("search_documents", query="a")),
                         reply(tool("read_page", doc_id="ny_medicaid_pdl", page=34)), reply(submit()))
    run(router, make_tools(pdf_path=lambda d: None))
    first = sent(router, 0)
    for later in router.fake_primary.requests[1:]:
        assert later["tools"] == first["tools"] and later["system"] == first["system"]
    for a, b in zip(router.fake_primary.requests, router.fake_primary.requests[1:]):
        assert b["messages"][: len(a["messages"])] == a["messages"]


def test_plain_text_reply_is_nudged_once_and_submit_keeps_citations():
    router = make_router(reply(tool("search_documents", query="Ozempic")), reply(text("It's preferred.")),
                         reply(submit([("ny_medicaid_pdl", 34)])))
    r = run(router)
    assert sent(router, 2)["messages"][-1] == Message("user", [TextPart(SUBMIT_NUDGE)])
    assert r["citations"][0]["flag"] is None and r["citations"][0]["page"] == 34
    assert "nudged_to_submit" in r["flags"] and "no_submit" not in r["flags"] and r["status"] == "answered"


def test_plain_text_after_nudge_is_kept_in_the_trace_but_is_a_no_answer():
    router = make_router(reply(text("It's preferred.")), reply(text("")))
    r = run(router)
    assert len(router.fake_primary.requests) == 2  # one nudge only
    assert r["flags"] == ["nudged_to_submit", "no_submit", "no_answer_rule"]
    assert r["status"] == "no_answer" and r["agent_status"] == "answered" and r["answer"] == NO_ANSWER_TEXT


def test_no_nudge_after_the_deadline():
    now = [0.0]

    def slow_model():
        now[0] += 26.0

    r = run(make_router(reply(text("It's preferred.")), on_call=slow_model), clock=lambda: now[0])
    assert r["flags"] == ["no_submit", "no_answer_rule"]


# ---- minimum lookups before the first submit ----

def test_an_early_answered_submit_is_refused_once_with_the_nudge_and_the_next_submit_is_accepted(pdf):
    router = make_router(reply(tool("search_documents", query="Ozempic")), reply(submit(P34, answer=FIRST)),
                         reply(tool("read_page", doc_id="ny_medicaid_pdl", page=34)), reply(submit(P34, answer=FULLER)))
    r = run(router, make_tools(pdf_path=lambda d: pdf), cfg=NUDGE_CFG)
    assert r["status"] == "answered" and r["answer"] == FULLER and r["lookups"] == 2
    assert r["flags"] == ["min_lookups_nudge"] and len(router.fake_primary.requests) == 4
    # the refused submit_answer call got an error result carrying the nudge, and nothing else was appended
    refused = sent(router, 2)["messages"][-1]
    submit_id = sent(router, 2)["messages"][-2].tool_calls[0].id
    assert refused == Message("tool", [ToolResult(call_id=submit_id, content=MIN_LOOKUPS_NUDGE, is_error=True)])
    assert r["_tools"].fake_search.agent_calls() == [{"query": "Ozempic", "k": 8, "program": None}]


def test_the_second_submit_is_accepted_whatever_the_lookup_count():
    router = make_router(reply(submit(P34, answer=FIRST)), reply(submit(P34, answer=FIRST)))
    r = run(router, cfg=NUDGE_CFG)
    assert r["flags"] == ["min_lookups_nudge", "unverified_citation", "no_answer_rule"]  # p34 was never returned
    assert r["agent_status"] == "answered" and r["lookups"] == 0 and len(router.fake_primary.requests) == 2


def test_lookups_requested_beside_an_early_submit_still_run():
    router = make_router(reply(tool("search_documents", query="a"), submit(P34, answer=FIRST)),
                         reply(submit(P34, answer=FULLER)))
    r = run(router, cfg=NUDGE_CFG)
    results = sent(router, 1)["messages"][-1].parts
    assert [(x.is_error, x.content == MIN_LOOKUPS_NUDGE) for x in results] == [(False, False), (True, True)]
    assert r["lookups"] == 1 and r["answer"] == FULLER and r["flags"] == ["min_lookups_nudge"]


def test_no_nudge_when_the_submit_is_not_answered():
    for status in ("not_in_documents", "out_of_scope"):
        router = make_router(reply(tool("search_documents", query="Ozempic")), reply(submit(P34, status=status, answer="No.")))
        r = run(router, cfg=COMPLETE_CFG)
        assert r["agent_status"] == status and len(router.fake_primary.requests) == 2
        assert "min_lookups_nudge" not in r["flags"] and r["completeness"] is None  # nor a completeness pass


def test_no_nudge_when_time_is_short_or_the_cap_is_reached():
    now = [0.0]

    def tick():
        now[0] += 10.0   # the submit arrives at 20 s: past deadline_s - 6

    router = make_router(reply(tool("search_documents", query="Ozempic")), reply(submit(P34)), on_call=tick)
    r = run(router, cfg=NUDGE_CFG, clock=lambda: now[0])
    assert r["status"] == "answered" and r["flags"] == [] and len(router.fake_primary.requests) == 2
    # the cap: one lookup allowed, so no second one could run
    cfg = {**NUDGE_CFG, "agent": {**NUDGE_CFG["agent"], "max_tool_calls": 1}}
    router = make_router(reply(tool("search_documents", query="Ozempic")), reply(submit(P34)))
    r = run(router, cfg=cfg)
    assert r["status"] == "answered" and "min_lookups_nudge" not in r["flags"] and len(router.fake_primary.requests) == 2


def test_min_lookups_of_zero_or_one_changes_nothing():
    for n in (0, 1):
        cfg = {**CFG, "agent": {**CFG["agent"], "min_lookups": n}}
        router = make_router(reply(tool("search_documents", query="Ozempic")), reply(submit(P34)))
        r = run(router, cfg=cfg)
        assert r["flags"] == [] and len(router.fake_primary.requests) == 2
    r = run(make_router(reply(submit(P34))), cfg={**CFG, "agent": {**CFG["agent"], "min_lookups": 0}})
    assert "min_lookups_nudge" not in r["flags"]


# ---- the completeness pass ----

def test_completeness_pass_replaces_the_answer_and_is_costed_like_any_call(monkeypatch):
    traces = []
    monkeypatch.setattr(loop.telemetry, "emit", lambda trace, cfg: traces.append(trace))
    router = make_router(reply(tool("search_documents", query="Ozempic")), reply(submit(P34, answer=FIRST)),
                         reply(submit(P34, answer=FULLER)))
    r = run(router, cfg=PASS_CFG)
    assert r["status"] == "answered" and r["answer"] == FULLER and r["citations"][0]["flag"] is None
    assert r["flags"] == ["completeness_pass"]
    assert {k: r["completeness"][k] for k in ("ran", "changed", "added_words", "outcome")} == \
        {"ran": True, "changed": True, "added_words": 7, "outcome": "replaced"}
    # the third request: the submit's result, then the note as a user turn, with submit_answer forced
    third = sent(router, 2)
    submit_id = third["messages"][-3].tool_calls[0].id
    assert third["messages"][-2] == Message("tool", [ToolResult(call_id=submit_id, content=SUBMIT_RECEIVED, is_error=False)])
    assert third["messages"][-1] == Message("user", [TextPart(COMPLETENESS_CHECK)])
    assert third["tool_choice"] == "submit_answer" and sent(router, 1)["tool_choice"] == "auto"
    assert third["timeout_s"] == 25  # min(call_timeout, 30 - elapsed) like every other call
    # the extra call is costed and timed like the others
    assert r["tokens"] == {"input": 3000, "output": 300, "cache_read": 1500, "cache_write": 0}
    assert r["cost_usd"] == pytest.approx(0.0093) and len(r["timing_s"]["model_calls"]) == 3
    assert r["answered_by"] == "gpt-5.5" and r["lookups"] == 1
    # the trace keeps both submits
    trace = traces[0]
    assert trace["first_submit"]["answer"] == FIRST and trace["model_answer"] == FULLER
    assert len(trace["model_calls"]) == 3 and trace["model_calls"][2]["output"]["tool_calls"][0]["name"] == "submit_answer"
    assert trace["config"]["completeness_pass"] is True and trace["config"]["min_lookups"] == 0


def test_completeness_pass_unchanged_resubmit_is_recorded_as_unchanged():
    router = make_router(reply(tool("search_documents", query="Ozempic")), reply(submit(P34, answer=FIRST)),
                         reply(submit(P34, answer=FIRST)))
    r = run(router, cfg=PASS_CFG)
    assert r["answer"] == FIRST and r["flags"] == ["completeness_pass"]
    assert (r["completeness"]["changed"], r["completeness"]["added_words"], r["completeness"]["outcome"]) == (False, 0, "unchanged")


def test_citation_check_and_no_answer_rule_run_on_the_replaced_submit():
    # the pass cites a page no tool returned: the final answer is judged on that submit
    router = make_router(reply(tool("search_documents", query="Ozempic")), reply(submit(P34, answer=FIRST)),
                         reply(submit([("ny_medicaid_pdl", 77)], answer=FULLER)))
    r = run(router, cfg=PASS_CFG)
    assert r["status"] == "no_answer" and r["answer"] == NO_ANSWER_TEXT
    assert r["flags"] == ["completeness_pass", "unverified_citation", "no_answer_rule"]


def test_completeness_pass_without_a_submit_keeps_the_first_answer():
    router = make_router(reply(tool("search_documents", query="Ozempic")), reply(submit(P34, answer=FIRST)),
                         reply(text("Nothing to add.")))
    r = run(router, cfg=PASS_CFG)
    assert r["status"] == "answered" and r["answer"] == FIRST and r["flags"] == ["completeness_pass_failed"]
    assert r["completeness"]["outcome"] == "no_submit" and r["completeness"]["changed"] is False
    assert len(r["timing_s"]["model_calls"]) == 3  # the turn still ran and is costed


def test_completeness_pass_failure_or_status_change_keeps_the_first_answer_and_never_raises():
    router = make_router(reply(tool("search_documents", query="Ozempic")), reply(submit(P34, answer=FIRST)),
                         error(500, retryable=True), error(500, retryable=True), fallback_script=[error(529, retryable=True)])
    r = run(router, cfg=PASS_CFG)
    assert r["status"] == "answered" and r["answer"] == FIRST and r["flags"] == ["completeness_pass_failed"]
    assert (r["completeness"]["outcome"], r["completeness"]["error"]) == ("failed", "AllProvidersFailed")
    assert len(r["timing_s"]["model_calls"]) == 2
    # the pass withdrawing the answer is not accepted either: it may add, not remove
    router = make_router(reply(tool("search_documents", query="Ozempic")), reply(submit(P34, answer=FIRST)),
                         reply(submit([], status="not_in_documents", answer="Not covered.")))
    r = run(router, cfg=PASS_CFG)
    assert r["status"] == "answered" and r["answer"] == FIRST and r["completeness"]["outcome"] == "status_changed"


def test_a_lookup_attempted_during_the_completeness_pass_is_refused():
    router = make_router(reply(tool("search_documents", query="Ozempic")), reply(submit(P34, answer=FIRST)),
                         reply(tool("search_documents", query="metformin"), submit(P34, answer=FULLER)))
    r = run(router, cfg=PASS_CFG)
    assert r["status"] == "answered" and r["answer"] == FIRST and r["flags"] == ["completeness_pass_failed"]
    assert r["completeness"]["outcome"] == "lookup_attempted" and r["completeness"]["refused"] == ["search_documents"]
    assert r["_tools"].fake_search.agent_calls() == [{"query": "Ozempic", "k": 8, "program": None}] and r["lookups"] == 1
    assert LOOKUPS_CLOSED == "lookups are closed; call submit_answer"


def test_completeness_pass_is_skipped_when_little_time_remains():
    now = [0.0]

    def tick():
        now[0] += 12.0   # the submit is accepted at 24 s: 6 s left, under the 8 s minimum

    router = make_router(reply(tool("search_documents", query="Ozempic")), reply(submit(P34, answer=FIRST)), on_call=tick)
    r = run(router, cfg=PASS_CFG, clock=lambda: now[0])
    assert r["status"] == "answered" and r["answer"] == FIRST and r["flags"] == ["completeness_pass_skipped"]
    assert r["completeness"] == {"ran": False, "changed": False, "added_words": 0, "outcome": "skipped"}
    assert len(router.fake_primary.requests) == 2
    # just enough time: it runs, with the remaining time as its timeout
    now[0] = 0.0
    tick11 = lambda: now.__setitem__(0, now[0] + 11.0)
    router = make_router(reply(tool("search_documents", query="Ozempic")), reply(submit(P34, answer=FIRST)),
                         reply(submit(P34, answer=FIRST)), on_call=tick11)
    r = run(router, cfg=PASS_CFG, clock=lambda: now[0])
    assert r["flags"] == ["completeness_pass"] and sent(router, 2)["timeout_s"] == 8.0


def test_completeness_pass_is_off_when_disabled_or_without_an_answered_submit():
    router = make_router(reply(tool("search_documents", query="Ozempic")), reply(submit(P34, answer=FIRST)))
    r = run(router, cfg=CFG)
    assert r["completeness"] is None and r["flags"] == []
    r = run(make_router(REFUSAL), cfg=PASS_CFG)
    assert r["completeness"] is None and r["agent_status"] == "refused"
    r = run(make_router(reply(text("It's preferred.")), reply(text(""))), cfg=PASS_CFG)
    assert r["completeness"] is None and "no_submit" in r["flags"]


def test_nudge_then_completeness_pass_in_one_question():
    router = make_router(reply(tool("search_documents", query="Ozempic")), reply(submit(P34, answer=FIRST)),
                         reply(tool("search_documents", query="Ozempic PA")), reply(submit(P34, answer=FIRST)),
                         reply(submit(P34, answer=FULLER)))
    r = run(router, cfg=COMPLETE_CFG)
    assert r["status"] == "answered" and r["answer"] == FULLER and r["lookups"] == 2
    assert r["flags"] == ["min_lookups_nudge", "completeness_pass"] and len(router.fake_primary.requests) == 5


def test_config_yaml_sets_the_completeness_defaults():
    from pharmassist.config import load_config
    acfg = load_config()["agent"]
    # both off in production after the 2026-10-18 measurement (no accuracy gain, +8 s p50); the code keeps them as flags
    assert acfg["min_lookups"] == 1 and acfg["completeness_pass"] is False and acfg["completeness_min_remaining_s"] == 8
    # and the loop's own defaults match when the keys are missing
    bare = {**CFG, "agent": {k: v for k, v in CFG["agent"].items()
                             if k not in ("min_lookups", "completeness_pass", "completeness_min_remaining_s")}}
    router = make_router(reply(tool("search_documents", query="Ozempic")), reply(submit(P34, answer=FIRST)),
                         reply(tool("search_documents", query="more")), reply(submit(P34, answer=FIRST)),
                         reply(submit(P34, answer=FULLER)))
    r = run(router, cfg=bare)
    assert r["flags"] == ["min_lookups_nudge", "completeness_pass"] and r["answer"] == FULLER


# ---- providers, fallback, refusal ----

def test_refusal_is_a_no_answer_with_the_refused_agent_status():
    r = run(make_router(REFUSAL))
    assert r["status"] == "no_answer" and r["agent_status"] == "refused" and r["citations"] == []
    assert r["answer"] == NO_ANSWER_TEXT and r["needs_review"] is True


def test_fallback_serves_the_whole_thread_after_the_primary_fails():
    router = make_router(error(500, retryable=True), error(502, retryable=True),
                         fallback_script=[reply(tool("search_documents", query="Ozempic")),
                                          reply(submit([("ny_medicaid_pdl", 34)]), model="claude-sonnet-5-5")])
    r = run(router)
    assert r["status"] == "answered" and r["fallback_used"] is True
    assert (r["provider"], r["model"]) == ("anthropic", "claude-sonnet-5-5")
    # the second call went straight to the fallback: no retry of the primary mid-thread
    assert len(router.fake_primary.requests) == 2 and len(router.fake_fallback.requests) == 2


def test_fallback_mid_thread_keeps_the_earlier_openai_turn():
    router = make_router(reply(tool("search_documents", query="Ozempic")), error(429, retryable=True), error(429, retryable=True),
                         fallback_script=[reply(submit([("ny_medicaid_pdl", 34)]))])
    r = run(router)
    assert r["fallback_used"] is True and r["provider"] == "anthropic" and r["status"] == "answered"
    fb = router.fake_fallback.requests[0]["messages"]
    assert [m.role for m in fb] == ["user", "assistant", "tool"] and fb[1].tool_calls[0].name == "search_documents"
    assert r["timing_s"]["model_calls"] and len(r["timing_s"]["model_calls"]) == 2


def test_both_providers_failing_propagates():
    router = make_router(error(500, retryable=True), error(500, retryable=True), fallback_script=[error(529, retryable=True)])
    with pytest.raises(AllProvidersFailed):
        run(router)


def test_cost_and_token_totals_come_from_the_completions():
    router = make_router(reply(tool("search_documents", query="a")), reply(submit([("ny_medicaid_pdl", 34)])))
    r = run(router)
    assert r["tokens"] == {"input": 2000, "output": 200, "cache_read": 1000, "cache_write": 0}
    # 2000*2 + 200*10 + 1000*0.2 per million, at the fake's price table
    assert r["cost_usd"] == pytest.approx(0.0062)
    from pharmassist.llm.pricing import cost_usd
    assert cost_usd({"input": 1_000_000, "output": 0, "cache_read": 0, "cache_write": 0}, PRICES) == 2.0


# ---- tools ----

def test_tool_errors_reach_the_model_instead_of_crashing():
    box = make_tools()
    assert box.run("read_page", {"doc_id": "va_national_formulary_2026_09", "page": 1}) == \
        (tools.FORMULARY_UNAVAILABLE, True)
    msg, err = box.run("read_page", {"doc_id": "ny_medicaid_pdl", "page": 999})
    assert err and "pages 1–86" in msg
    msg, err = box.run("search_documents", {"query": "x", "program": "Atlantis"})
    assert err and "program must be one of" in msg
    msg, err = box.run("read_page", {"doc_id": "nope", "page": 1})
    assert err and "unknown doc_id" in msg
    assert box.seen == set()


def test_baseline_config_sends_the_baseline_tools_and_prompt_unchanged():
    from pharmassist.agent.prompt import SYSTEM
    router = make_router(reply(submit()))
    run(router)
    assert sent(router)["tools"] == tools.tool_defs(False) and sent(router)["system"] == SYSTEM
    assert [t.name for t in sent(router)["tools"]] == ["search_documents", "read_page", "list_documents", "submit_answer"]
    assert sent(router)["tools"][-1].strict is True and not sent(router)["tools"][0].strict


def test_structured_config_offers_the_lookups_and_routing_rules():
    router = make_router(reply(submit_rows([])))
    run(router, cfg=STRUCTURED_CFG)
    assert [t.name for t in sent(router)["tools"]] == ["search_documents", "read_page", "list_documents",
                                                      "lookup_va_formulary", "lookup_ny_medicaid_drug", "submit_answer"]
    system = sent(router)["system"]
    assert "the row wins" in system and "no_matching_row means the name wasn't found" in system
    assert "not searchable or readable yet" not in system
    va = next(t for t in sent(router)["tools"] if t.name == "lookup_va_formulary")
    assert "dosage form specific (row 7)" in va.description and "non-formulary" in va.description


def test_formulary_row_citation_passes_only_if_the_lookup_returned_it():
    va = "va_national_formulary_2026_09"
    router = make_router(reply(tool("lookup_va_formulary", drug="Ozempic")),
                         reply(submit_rows([{"doc_id": va, "page": None, "row": 8}, {"doc_id": va, "page": None, "row": 5},
                                            {"doc_id": va, "page": None, "row": 9}])))
    box = make_tools(FakeStore(tables=TABLES), cfg=STRUCTURED_CFG)
    r = run(router, box, cfg=STRUCTURED_CFG)
    flags = {c["row"]: c["flag"] for c in r["citations"]}
    assert flags[8] is None and flags[5] is None   # the matched row, and the dosage-form rule row
    assert flags[9] == "not returned by any tool during this question"
    assert r["citations"][0]["locator"] == f"{va}:r8" and f"{va}:r8" in r["pages_seen"]
    assert r["status"] == "answered" and box.fake_search.calls == []
    assert box.calls[0]["lookup"] == {"result": "exact_match", "rows": 1}


def test_lookup_failure_reaches_the_model_as_an_error():
    router = make_router(reply(tool("lookup_va_formulary", drug="Ozempic")), reply(submit_rows([])))
    run(router, make_tools(FakeStore(tables={}), cfg=STRUCTURED_CFG), cfg=STRUCTURED_CFG)   # a store with no rows
    result = sent(router, 1)["messages"][-1].parts[0]
    assert result.is_error is True
    assert result.content.startswith("lookup_failure") and "unavailable" in result.content


def test_no_matching_row_is_distinguished_from_a_negative_finding():
    box = make_tools(FakeStore(tables=TABLES), cfg=STRUCTURED_CFG)
    missing = json.loads(box.run("lookup_va_formulary", {"drug": "zzzzolam"})[0])
    film = json.loads(box.run("lookup_va_formulary", {"drug": "buprenorphine/naloxone", "dosage_form": "film"})[0])
    assert missing["result"] == "no_matching_row" and "doesn't mean" in missing["note"]
    assert film["result"] == "dosage_form_not_listed" and "non-formulary" in film["note"]


def test_baseline_toolbox_refuses_the_lookups():
    text_, is_error = make_tools().run("lookup_va_formulary", {"drug": "Ozempic"})
    assert is_error and "unknown tool" in text_


def test_section_results_make_every_page_citable():
    """A parent section covering pp. 18-20 lets the answer cite p19; p21 still fails the check."""
    hit = {"doc_id": "ny_medicaid_pharmacy_policy", "page": 18, "pages": [18, 19, 20],
           "section": "1.0 General Pharmacy Policy > Third Party Liability", "program": "NY Medicaid",
           "authority": "binding", "date": "2026-09", "text": "[p 18] ... [p 19] ... [p 20] ..."}
    doc = "ny_medicaid_pharmacy_policy"
    router = make_router(reply(tool("search_documents", query="dual eligible")), reply(submit([(doc, 19), (doc, 21)])))
    r = run(router, make_tools(search=FakeSearch({QUESTION: [hit], "dual eligible": [hit]})))
    flags = {c["page"]: c["flag"] for c in r["citations"]}
    assert flags[19] is None and flags[21] == "not returned by any tool during this question"
    rows = json.loads(sent(router, 1)["messages"][-1].parts[0].content)
    assert rows[0]["pages"] == [18, 19, 20] and rows[0]["section"].endswith("Third Party Liability")


def test_a_structured_only_answer_runs_no_document_search():
    router = make_router(reply(tool("lookup_ny_medicaid_drug", drug="Ozempic")), reply(submit([("ny_medicaid_pdl", 34)])))
    box = make_tools(FakeStore(tables=TABLES), cfg=STRUCTURED_CFG)
    r = run(router, box, cfg=STRUCTURED_CFG)
    assert box.fake_search.calls == [] and r["status"] == "answered" and r["citations"][0]["flag"] is None
    assert box.calls[0]["lookup"]["result"] == "exact_match"


def test_follow_up_searches_still_run_and_record_provenance():
    router = make_router(reply(tool("search_documents", query="Ozempic PA")),
                         reply(tool("search_documents", query="GLP-1 clinical criteria", program="NY Medicaid")),
                         reply(submit([("ny_medicaid_pdl", 34)])))
    r = run(router)
    search = r["_tools"].fake_search
    assert [c["query"] for c in search.agent_calls()] == ["Ozempic PA", "GLP-1 clinical criteria"]
    assert [c["program"] for c in search.calls if c["query"] == QUESTION] == [None, "NY Medicaid"]
    assert r["lookups"] == 2 and r["status"] == "answered"


# ---- the shipped path is ungated; the checks run only offline ----

def test_tools_and_prompt_are_the_evaluated_ungated_ones():
    """Snapshot of what evaluation B (d804f38) sent the model: the free-form submit_answer, the same
    search, read and lookup tools, and the same system prompt. The ToolSpecs are made from these dicts."""
    from pharmassist.agent.prompt import system_prompt
    digest = lambda x: hashlib.sha256(x.encode()).hexdigest()[:16]
    assert [digest(json.dumps(tools.tool_dicts(s), sort_keys=True)) for s in (False, True)] == \
        ["bc4b53791d8fed2d", "9ec9790cdc9ad6f0"]
    assert [digest(system_prompt(s)) for s in (False, True)] == ["894d6d875d2c4620", "8c05de6fe23a34a6"]
    # the optional sections (agent.prompt_extras), measured 2026-10-18 and left off
    assert [digest(system_prompt(s, ("multipart", "checklist"))) for s in (False, True)] == ["ca423cc3a12d74ff", "5f0c1a1051a3e957"]
    for s in (False, True):
        assert [(t.name, t.input_schema, t.strict) for t in tools.tool_defs(s)] == \
            [(d["name"], d["input_schema"], bool(d.get("strict"))) for d in tools.tool_dicts(s)]
    schema = tools.tool_defs(True)[-1].input_schema
    assert schema["required"] == ["status", "assumption", "answer", "citations", "conflicts_noted"]
    assert schema["additionalProperties"] is False   # strict-compatible for OpenAI


def test_the_default_config_has_no_live_gate_and_the_loop_imports_no_checker():
    from pharmassist.config import load_config
    cfg = load_config()
    assert "verification" not in cfg["agent"]
    assert cfg["eval"]["claim_audit"]["enabled"] is False and cfg["eval"]["offline_checks"]["enabled"] is False
    names = {getattr(v, "__name__", "") for v in vars(loop).values()}
    assert not {"pharmassist.agent.verify", "pharmassist.agent.offline", "check_claim", "audit_claims"} & names


def test_a_free_form_answer_is_returned_word_for_word():
    answer = ("Assuming NY Medicaid: Ozempic pen is **preferred**; PA required for new starts.\n\n"
              "| Drug | Status |\n|---|---|\n| Ozempic pen | Preferred |")
    sub = tool("submit_answer", status="answered", assumption="Assuming NY Medicaid", answer=answer,
               citations=[{"doc_id": "ny_medicaid_pdl", "page": 34}], conflicts_noted=["PDL vs. guide: PDL wins."])
    router = make_router(reply(tool("search_documents", query="Ozempic")), reply(sub))
    r = run(router)
    assert r["answer"] == answer and r["status"] == "answered" and r["assumption"] == "Assuming NY Medicaid"
    assert r["conflicts_noted"] == ["PDL vs. guide: PDL wins."] and r["needs_review"] is False
    assert r["words"]["displayed"] == r["words"]["rendered"] > 0
    assert len(router.fake_primary.requests) == 2


def test_no_check_or_verifier_runs_while_answering_and_the_trace_keeps_the_detail(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise AssertionError("a check ran on the live path")

    for mod, name in [(V, "check_claim"), (V, "audit_claims"), (V, "validate"), (V, "assemble"),
                      (offline, "audit_trace"), (offline, "deterministic_checks"), (offline, "audit")]:
        monkeypatch.setattr(mod, name, boom)
    monkeypatch.setattr(loop, "project_path", lambda name: tmp_path)
    monkeypatch.setattr(loop, "PROJECT_ROOT", tmp_path)
    # an answer the offline checks would flag (eGFR 30 isn't on the cited page) is still shown as written
    answer = "Under NY Medicaid, Ozempic pen needs eGFR ≥30."
    router = make_router(reply(tool("search_documents", query="Ozempic")), reply(submit([("ny_medicaid_pdl", 34)], answer=answer)))
    r = ask(QUESTION, router=router, tools=make_tools(), cfg=CFG, save_trace=True, request_id="req-1",
            context={"user_id": "u1", "conversation_id": "c1", "generation": 3})
    assert r["answer"] == answer and r["status"] == "answered" and r["request_id"] == "req-1"
    trace = json.loads((tmp_path / r["trace_path"]).read_text())
    assert "verification" not in trace and "offline_checks" not in trace and "claim_audit" not in trace
    assert trace["cited_evidence"] == {"ny_medicaid_pdl:p34": "ny_medicaid_pdl (NY Medicaid, binding, "
                                                              "2026-09-14)\nOzempic pen ..."}
    assert trace["context"] == {"user_id": "u1", "conversation_id": "c1", "generation": 3}
    assert trace["config"]["primary"] == "gpt-5.5" and trace["config"]["search"]["mode"] == "hybrid"
    calls = trace["model_calls"]
    assert [c["provider"] for c in calls] == ["openai", "openai"] and calls[0]["input_messages"][0]["role"] == "user"
    assert QUESTION in calls[0]["input_messages"][0]["text"] and calls[0]["output"]["tool_calls"][0]["name"] == "search_documents"
    assert calls[1]["input_messages"][0]["role"] == "tool" and "Ozempic pen" in calls[1]["input_messages"][0]["tool_results"][0]["content"]
    assert trace["tool_calls"][0]["result"].startswith("[{\"doc_id\"") and trace["model_answer"] == answer


def test_a_citation_no_tool_returned_is_flagged_for_review_and_the_answer_is_unchanged():
    answer = "Ozempic pen is preferred."
    router = make_router(reply(tool("search_documents", query="Ozempic")),
                         reply(submit([("ny_medicaid_pdl", 34), ("ny_medicaid_pdl", 77)], answer=answer)))
    r = run(router)
    assert [c["flag"] for c in r["citations"]] == [None, "not returned by any tool during this question"]
    assert "unverified_citation" in r["flags"] and r["needs_review"] is True and r["answer"] == answer


def test_code_written_outcomes_are_the_fixed_no_answer_text():
    r = run(make_router(REFUSAL))
    assert r["answer"] == NO_ANSWER_TEXT and r["needs_review"] is True
    r = run(make_router(*[reply(tool("search_documents", query=f"q{i}")) for i in range(CFG["agent"]["max_tool_calls"] + 4)]))
    assert r["status"] == r["agent_status"] == "no_answer" and r["answer"] == NO_ANSWER_TEXT and r["needs_review"] is True
    assert "no_answer" in r["flags"]


def test_the_search_result_the_model_sees_is_unchanged_by_evidence_capture():
    box = make_tools()
    content, is_error = box.run("search_documents", {"query": "Ozempic"})
    assert not is_error and json.loads(content) == [{"doc_id": "ny_medicaid_pdl", "page": 34, "program": "NY Medicaid",
                                                     "authority": "binding", "date": "2026-09-14",
                                                     "text": "Ozempic pen ..."}]
    assert box.seen == {"ny_medicaid_pdl:p34"} and "Ozempic pen ..." in box.evidence["ny_medicaid_pdl:p34"]


def test_ask_sets_the_toolbox_question_when_missing():
    box = make_tools(question=None)
    run(make_router(reply(tool("search_documents", query="x")), reply(submit([("ny_medicaid_pdl", 34)]))), box)
    assert box.question == QUESTION and QUESTION in [c["query"] for c in box.fake_search.calls]


# ---- the offline checks (never on the live path) ----

def _trace(answer, evidence="ny_medicaid_pdl (NY Medicaid, binding, 2026-09-14)\nOzempic pen is preferred."):
    return {"question": QUESTION, "answer": answer, "status": "answered", "started_at": "2026-10-17T10:00:00+00:00",
            "citations": [{"doc_id": "ny_medicaid_pdl", "page": 34, "locator": "ny_medicaid_pdl:p34"}],
            "cited_evidence": {"ny_medicaid_pdl:p34": evidence},
            "cited_evidence_parts": {"ny_medicaid_pdl:p34": [evidence]}}


def test_offline_deterministic_checks_flag_an_unsupported_value_without_a_model():
    t = _trace("Under NY Medicaid, the Ozempic pen is preferred.\n\n- Under NY Medicaid, check eGFR ≥30 first.")
    out = offline.audit_trace(t)
    assert "claim_audit" not in out and out["checks"]["sentences"] == 2
    assert [c["evidence_problem"] for c in out["checks"]["claims"]] == [False, True]
    assert out["checks"]["claims"][1]["text"] == "Under NY Medicaid, check eGFR ≥30 first."


def test_answer_claims_split_sentences_bullets_and_table_rows():
    a = "Assuming NY Medicaid: preferred. PA needed.\n1. Submit PA.\n\n| Drug | Status |\n|---|---|\n| Ozempic | Preferred |"
    assert [c["text"] for c in offline.answer_claims(a, [])] == [
        "Assuming NY Medicaid: preferred.", "PA needed.", "Submit PA.", "Ozempic | Preferred"]


def test_the_offline_audit_is_callable_and_its_failure_never_changes_the_answer():
    from types import SimpleNamespace as NS
    answer = "Under NY Medicaid, the Ozempic pen is preferred."
    verdict = {"claim": 1, "verdict": "supported", "unsupported_words": "", "self_contained": True, "reason": "ok"}
    seen = []

    def create(**kw):
        seen.append(kw)
        return NS(content=[NS(type="text", text=json.dumps({"verdicts": [verdict]}))], stop_reason="end_turn",
                  model=kw["model"], usage=NS(input_tokens=10, output_tokens=5, cache_read_input_tokens=0,
                                              cache_creation_input_tokens=0))
    acfg = {"model": "claude-sonnet-5-5"}
    t = _trace(answer)
    out = offline.audit_trace(t, NS(beta=NS(messages=NS(create=create))), acfg)
    assert out["claim_audit"]["verdicts"] == [{**verdict, "text": answer}] and seen[0]["system"] == V.AUDIT_SYSTEM

    def boom(**kw):
        raise TimeoutError("audit timed out")
    out = offline.audit_trace(t, NS(beta=NS(messages=NS(create=boom))), acfg)
    assert out["claim_audit"] == {"error": "TimeoutError: audit timed out"} and t["answer"] == answer
