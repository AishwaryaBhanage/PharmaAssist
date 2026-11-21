"""POST /ask: the agent path, the semantic cache hit path, the no-answer rule, timeouts and failures,
limits (per minute, per day, spend cap, fail-closed), conversations, persistence and privacy. The
agent, cache, store and limiter are fakes; nothing calls a model."""

import json
import logging

import pytest

from app.api.schemas import NO_ANSWER_TEXT
from fakes_api import (ANSWER, PDL_URL, QUESTION, FakeAgent, FakeCache, agent_result, build_app, client, make_user,
                       login)


@pytest.fixture
def http(tmp_path):
    def make(**kw):
        app, deps = build_app(tmp_path, **kw)
        deps.store.add_document()
        deps.store.add_document("va_national_formulary_2026_09", title="VA National Formulary", program="VA",
                                file_name="va_national_formulary_2026_09.xlsx", pages=None, sha="b" * 64,
                                source_url="https://www.va.gov/formularyadvisor/DOC_PDFS/VANF.xlsx")
        deps.store.add_figure("ny_medicaid_pdl", 34)
        make_user(deps, "s@example.com")
        c = client(app).__enter__()
        c.deps, c.hdrs = deps, login(c, "s@example.com")
        made.append(c)
        return c
    made = []
    yield make
    for c in made:
        c.__exit__(None, None, None)


def ask(http, question=QUESTION, **extra):
    return http.post("/api/v1/ask", json={"question": question, **extra}, headers=http.hdrs)


def test_ask_requires_sign_in(http):
    c = http()
    r = c.post("/api/v1/ask", json={"question": QUESTION})
    assert r.status_code == 401 and c.deps.answers.ask_fn.calls == []


def test_the_agent_path_returns_the_answer_as_given_and_persists_it(http):
    agent = FakeAgent()
    c = http(agent=agent)
    r = ask(c, f"  {QUESTION}   extra   spaces ")
    assert r.status_code == 200, r.text
    body = r.json()
    call = agent.calls[0]
    assert call["question"] == f"{QUESTION} extra spaces"       # normalized once
    assert call["request_id"] == body["request_id"] == r.headers["x-request-id"]
    assert call["save_trace"] is False and call["context"]["user_id"] and call["context"]["conversation_id"]
    assert body["answer"] == ANSWER and body["status"] == "answered" and body["cached"] is False
    assert body["provider"] == "openai" and body["model"] == "gpt-5.5" and body["fallback_used"] is False
    assert body["latency_seconds"] == 12.34 and body["assumption"] == "Assuming NY Medicaid"
    assert body["matched_question"] is None and body["cache_similarity"] is None
    page, row, flagged = body["citations"]
    assert page == {"id": "ny_medicaid_pdl:p34", "doc_id": "ny_medicaid_pdl", "document": "NYRx Medicaid Preferred Drug List",
                    "label": "Page 34", "page": 34, "sheet": None, "row": None, "url": f"{PDL_URL}#page=34",
                    "local_url": "/api/v1/sources/ny_medicaid_pdl/p34.pdf", "flagged": False, "flag_reason": None,
                    "figures": [{"figure_id": "ny_medicaid_pdl:p034_f1", "kind": "flowchart", "title": "Step therapy",
                                 "status": "ocr_checked",
                                 "status_text": "machine-interpreted from the page image by a vision model; structure "
                                                "and OCR cross-check passed",
                                 "crop_url": "/api/v1/figures/ny_medicaid_pdl/p034_f1.png"}]}
    assert row["label"] == "Formulary sheet, row 1697" and row["row"] == 1697 and row["url"] is None
    assert row["local_url"] is None                                  # a spreadsheet has no page file
    assert flagged["flagged"] is True and flagged["url"] is None and flagged["figures"] == []
    # persisted with the same ids, under a conversation titled with the question
    msg = c.deps.store.conversations.message(body["message_id"])
    assert msg.request_id == body["request_id"] and msg.question == f"{QUESTION} extra spaces"
    assert msg.citations == body["citations"] and msg.cost_usd == 0.05 and msg.tokens == {"input": 1200, "output": 300}
    assert msg.trace_id == "trace-1" and msg.agent_status == "answered" and msg.generation == 3
    conv = c.deps.store.conversations.get(body["conversation_id"])
    assert conv.title == QUESTION + " extra spaces" and conv.message_count == 1
    assert c.deps.store.stats.usage_day(c.deps.clock().date()) == {"day": str(c.deps.clock().date()), "questions": 1,
                                                                   "spend_usd": 0.05}


def test_a_link_that_is_not_the_documents_source_is_dropped(http):
    cites = [{"doc_id": "ny_medicaid_pdl", "page": 34, "link": "https://evil.example/x.pdf#page=34", "flag": None,
              "locator": "ny_medicaid_pdl:p34"},
             {"doc_id": "ny_medicaid_pdl", "page": 35, "link": "file:///Users/me/docs/pdl.pdf", "flag": None,
              "locator": "ny_medicaid_pdl:p35"}]
    c = http(agent=FakeAgent(agent_result(citations=cites)))
    body = ask(c).json()
    assert [x["url"] for x in body["citations"]] == [None, None] and "/Users/" not in json.dumps(body)


def test_a_cache_hit_skips_the_agent_and_is_marked(http):
    agent = FakeAgent()
    c = http(agent=agent)
    first = ask(c).json()
    second = ask(c, QUESTION.upper()).json()          # same bag of words: a near-identical embedding
    assert len(agent.calls) == 1
    assert second["cached"] is True and second["provider"] == "cache" and second["model"] == "gpt-5.5"
    assert second["cache_similarity"] >= 0.9 and second["matched_question"] == QUESTION
    assert second["answer"] == first["answer"] and second["citations"] == first["citations"]
    assert second["assumption"] == first["assumption"] and second["status"] == "answered"
    assert second["message_id"] != first["message_id"] and second["conversation_id"] != first["conversation_id"]
    msg = c.deps.store.conversations.message(second["message_id"])
    entry_id = next(iter(c.deps.cache.entries))
    assert msg.cached and msg.cache_hit_id == entry_id and msg.cost_usd == 0.0 and msg.provider == "cache"
    assert c.deps.cache.stats()["hits"] == 1 and c.deps.cache.get(entry_id).hits == 1
    assert c.deps.cache.get(entry_id).source_message_id == first["message_id"]


def test_the_cache_is_only_written_for_answered_cited_answers(http):
    c = http(agent=FakeAgent(agent_result(status="no_answer")))
    body = ask(c).json()
    assert body["status"] == "no_answer" and body["answer"] == NO_ANSWER_TEXT and body["citations"] == []
    assert c.deps.cache.entries == {}
    c2 = http(agent=FakeAgent(agent_result(status="answered", citations=[])))
    body = ask(c2).json()
    assert body["status"] == "no_answer" and body["answer"] == NO_ANSWER_TEXT   # answered without a citation: a miss
    assert c2.deps.cache.entries == {}


def test_a_non_canonical_no_answer_wording_is_replaced(http, caplog):
    c = http(agent=FakeAgent(agent_result(status="no_answer", answer="I couldn't find that in the documents.")))
    with caplog.at_level(logging.WARNING, logger="pharmassist.app"):
        body = ask(c).json()
    assert body["answer"] == NO_ANSWER_TEXT and body["status"] == "no_answer"
    assert any("non-canonical" in r.message for r in caplog.records)
    msg = c.deps.store.conversations.message(body["message_id"])
    assert msg.answer == NO_ANSWER_TEXT and msg.status == "no_answer"


def test_a_cache_entry_from_an_older_generation_is_not_used(http):
    agent = FakeAgent()
    c = http(agent=agent)
    ask(c)
    c.deps.store.documents._generation += 1          # a document was re-indexed
    body = ask(c).json()
    assert body["cached"] is False and len(agent.calls) == 2


def test_cache_and_embedding_failures_fall_back_to_the_agent(http):
    agent = FakeAgent()
    c = http(agent=agent)
    c.deps.cache.fail = True
    assert ask(c).status_code == 200 and len(agent.calls) == 1 and len(c.deps.cache.entries) == 1
    c.deps.cache.fail = False
    c.deps.answers.embed_fn = lambda text: 1 / 0
    r = ask(c, "A different question about Jardiance")
    assert r.status_code == 200 and len(agent.calls) == 2 and len(c.deps.cache.entries) == 1   # nothing to store it under


def test_timeouts_and_failures_are_safe_errors_and_release_the_reservation(http):
    c = http(agent=FakeAgent(delay=3.0))
    r = ask(c)
    assert r.status_code == 504 and r.json()["code"] == "timeout"
    c2 = http(agent=FakeAgent(error=RuntimeError("boom secret")))
    r = ask(c2)
    assert r.status_code == 502 and r.json()["code"] == "answer_failed" and "secret" not in r.text
    for x in (c, c2):
        assert x.deps.limiter.usage()["spend_usd"] == 0.0 and x.deps.limiter.usage()["questions"] == 1
        assert x.deps.store.conversations.msgs == {}


@pytest.mark.parametrize("question, code", [("", "question_too_short"), ("   \n ", "question_too_short"),
                                            ("ab", "question_too_short"), ("x" * 2001, "question_too_long")])
def test_blank_and_oversized_questions_never_reach_the_agent_or_the_limits(http, question, code):
    c = http()
    r = ask(c, question)
    assert r.status_code == 422 and r.json()["code"] == code
    assert c.deps.answers.ask_fn.calls == [] and c.deps.limiter.usage()["questions"] == 0


def test_questions_extend_the_callers_own_conversation_only(http):
    c = http()
    first = ask(c).json()
    second = ask(c, "Follow-up: what about Ozempic?", conversation_id=first["conversation_id"]).json()
    assert second["conversation_id"] == first["conversation_id"]
    conv = c.get(f"/api/v1/conversations/{first['conversation_id']}", headers=c.hdrs).json()
    assert [m["question"] for m in conv["messages"]] == [QUESTION, "Follow-up: what about Ozempic?"]
    assert conv["message_count"] == 2 and conv["title"] == QUESTION
    make_user(c.deps, "other@example.com")
    other = login(c, "other@example.com")
    r = c.post("/api/v1/ask", json={"question": QUESTION, "conversation_id": first["conversation_id"]}, headers=other)
    assert r.status_code == 404 and r.json()["code"] == "not_found"
    assert c.deps.limiter.usage()["questions"] == 2          # the refused question cost nothing


def test_per_minute_limit_then_retry_after(http):
    c = http()
    for _ in range(10):
        assert ask(c).status_code == 200
    r = ask(c)
    assert r.status_code == 429 and r.json()["code"] == "rate_limited" and 0 < int(r.headers["retry-after"]) <= 61
    c.deps.clock.advance(minutes=1)
    assert ask(c).status_code == 200


def test_per_user_daily_limit(http):
    from fakes_api import test_config
    c = http(cfg=test_config(limits_v2={"per_user_per_minute": 1000, "per_user_per_day": 3}))
    for _ in range(3):
        assert ask(c).status_code == 200
    r = ask(c)
    assert r.status_code == 429 and r.json()["code"] == "daily_limit" and int(r.headers["retry-after"]) <= 86401
    make_user(c.deps, "other@example.com")               # another user still has their own allowance
    assert c.post("/api/v1/ask", json={"question": QUESTION}, headers=login(c, "other@example.com")).status_code == 200


def test_global_daily_question_limit(http):
    from fakes_api import test_config
    c = http(cfg=test_config(limits_v2={"per_user_per_minute": 1000, "per_user_per_day": 1000, "questions_per_day": 2}))
    assert ask(c).status_code == 200 and ask(c).status_code == 200
    make_user(c.deps, "other@example.com")
    r = c.post("/api/v1/ask", json={"question": QUESTION}, headers=login(c, "other@example.com"))
    assert r.status_code == 429 and r.json()["code"] == "daily_limit"


def test_spend_cap_uses_measured_cost_and_a_reservation(http):
    from fakes_api import test_config
    cfg = test_config(limits_v2={"per_user_per_minute": 1000, "spend_usd_per_day": 0.20, "estimate_usd": 0.08})
    c = http(cfg=cfg, agent=FakeAgent(agent_result(cost_usd=0.09)), cache=FakeCache(threshold=1.01))
    assert ask(c).status_code == 200 and ask(c).status_code == 200         # 0.18 spent
    r = ask(c)                                                           # 0.18 + 0.08 reserved > 0.20
    assert r.status_code == 429 and r.json()["code"] == "spend_cap"
    assert c.deps.limiter.usage()["spend_usd"] == 0.18


def test_limiter_errors_fail_closed(http):
    c = http()

    def down(user_id):
        raise ConnectionError("redis down")
    c.deps.limiter.admit = down
    r = ask(c)
    assert r.status_code == 503 and r.json()["code"] == "limits_unavailable" and r.headers["retry-after"] == "5"
    assert c.deps.answers.ask_fn.calls == []


def test_logs_never_contain_the_question_or_the_answer(http, caplog):
    c = http(agent=FakeAgent(error=RuntimeError(QUESTION)))
    with caplog.at_level(logging.DEBUG):
        ask(c)
        ask(c, "second distinctive question about Jardiance")
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "Trulicity" not in text and "Jardiance" not in text and "RuntimeError" in text
