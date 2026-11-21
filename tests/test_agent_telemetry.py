"""Agent LangSmith tracing against a fake LangSmith client: hierarchy, the two content modes, privacy
in metadata mode, failure isolation and identical answers. No network, no paid call, no .env."""

import itertools
import json
import socket

import pytest

from pharmassist.agent import telemetry
from pharmassist.agent.loop import ask
from tests.test_agent_fakes import CFG, STRUCTURED_CFG, TABLES, FakeSearch, FakeStore, make_pdf, make_router, reply, tool

QUESTION = "Ozempic pen for a patient named Jane Roe: preferred or PA?"
AGENT_QUERY = "semaglutide pen prior authorization criteria"
ANSWER = "Assuming NY Medicaid: the Ozempic pen is preferred, no PA."
EVIDENCE = "Ozempic pen preferred; Rybelsus non-preferred."
FAKE_KEY = "lsv2_pt_" + "f00dfeed" * 4
REQUEST_ID = "7c6a0d2e-0b1a-4b7e-9f3c-2d8e4f5a6b7c"
CONTEXT = {"user_id": "user-42", "conversation_id": "conv-7", "generation": 3}
HITS = [{"doc_id": "ny_medicaid_pdl", "page": 34, "program": "NY Medicaid", "authority": "binding",
         "date": "2026-09-14", "text": EVIDENCE, "chunk_id": "ny_medicaid_pdl:p34:c2", "score": 0.91},
        {"doc_id": "ny_medicaid_pdl", "page": 35, "program": "NY Medicaid", "authority": "binding",
         "date": "2026-09-14", "text": f"{EVIDENCE} (no chunk id)", "score": 0.42}]
_pdf = {}


def scripted():
    submit = tool("submit_answer", status="answered", assumption="Assuming NY Medicaid", answer=ANSWER,
                  citations=[{"doc_id": "ny_medicaid_pdl", "page": 34, "row": None},
                             {"doc_id": "ny_medicaid_pdl", "page": 99, "row": None}], conflicts_noted=[])
    return make_router(reply(tool("search_documents", query=AGENT_QUERY, program="NY Medicaid"),
                             tool("lookup_ny_medicaid_drug", drug="Ozempic")),
                       reply(tool("read_page", doc_id="ny_medicaid_pdl", page=34)),
                       reply(submit))


class LangSmith:
    """Records the runs sent, as LangSmith's create_run/update_run receive them."""

    def __init__(self, fail=False):
        self.created, self.updated, self.fail = [], [], fail

    def create_run(self, **kw):
        if self.fail:
            raise TimeoutError(f"langsmith timed out with {FAKE_KEY}")
        self.created.append(kw)

    def update_run(self, run_id, **kw):
        self.updated.append({"run_id": run_id, **kw})

    def flush(self, timeout=None):
        pass

    def payload(self) -> str:
        return json.dumps([self.created, self.updated], default=str)


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path_factory):
    monkeypatch.setattr(telemetry, "_load_env", lambda: None)
    monkeypatch.setenv("LANGSMITH_API_KEY", FAKE_KEY)
    monkeypatch.setenv("LANGSMITH_PROJECT", "agent-test")
    monkeypatch.setenv("TRACE_HASH_SALT", "test-salt-not-a-secret")
    monkeypatch.delenv("LANGSMITH_CONTENT_MODE", raising=False)   # conftest sets metadata; the config decides here

    def no_network(*a, **k):
        raise AssertionError("network call in a telemetry test")
    monkeypatch.setattr(socket.socket, "connect", no_network)
    if "path" not in _pdf:
        _pdf["path"] = make_pdf(tmp_path_factory.mktemp("pdf") / "pdl.pdf", pages=86, text=EVIDENCE)


def traced(monkeypatch, fail=False, mode=None):
    ls = LangSmith(fail=fail)
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    if mode is not None:
        monkeypatch.setenv("LANGSMITH_CONTENT_MODE", mode)
    monkeypatch.setattr(telemetry, "_client", ls)
    return ls


def cfg_with(mode):
    return {**STRUCTURED_CFG, "tracing_v2": {"content": mode}}


def run(mode="metadata", save_trace=False, **kw):
    clock = itertools.count(step=0.25)
    cfg = cfg_with(mode)
    from pharmassist.agent import tools
    box = tools.ToolBox(FakeStore(tables=TABLES), FakeSearch({q: HITS for q in (QUESTION, AGENT_QUERY)}), cfg=cfg,
                        pdf_path=lambda d: _pdf["path"], question=QUESTION)
    r = ask(QUESTION, router=scripted(), tools=box, cfg=cfg, save_trace=save_trace, clock=lambda: next(clock),
            request_id=REQUEST_ID, context=CONTEXT, **kw)
    telemetry.flush()
    return r


def tree(ls):
    runs = {str(c["id"]): {**c, "kids": []} for c in ls.created}
    roots = []
    for c in runs.values():
        (runs[str(c["parent_run_id"])]["kids"] if c.get("parent_run_id") else roots).append(c)
    shape = lambda c: (c["name"], [shape(k) for k in c["kids"]])
    return roots, [shape(r) for r in roots]


def meta(ls, name):
    return [c["extra"]["metadata"] for c in ls.created if c["name"] == name]


def outputs(ls, name):
    ids = [str(c["id"]) for c in ls.created if c["name"] == name]
    return [u["outputs"] for u in ls.updated if str(u["run_id"]) in ids]


def inputs(ls, name):
    return [c["inputs"] for c in ls.created if c["name"] == name]


# ---- hierarchy, in both modes ----

@pytest.mark.parametrize("mode", ["metadata", "full"])
def test_one_root_per_request_with_the_documented_hierarchy(monkeypatch, mode):
    ls = traced(monkeypatch)
    r = run(mode)
    roots, shape = tree(ls)
    assert shape == [("agent_answer", [
        ("agent_model_call", []), ("agent_model_call", []), ("agent_model_call", []),
        ("search_documents", [("original_question_search", []), ("agent_query_search", []),
                              ("merge_and_rerank", [])]),
        ("structured_lookup", []), ("read_page", []), ("citation_validation", []), ("answer_complete", [])])]
    assert all(str(c["trace_id"]) == str(roots[0]["id"]) for c in ls.created)
    # every run is closed, with an end time, and none failed
    assert len(ls.updated) == len(ls.created) and all(u["end_time"] and not u["error"] for u in ls.updated)
    assert {c["run_type"] for c in ls.created if c["name"] == "agent_model_call"} == {"llm"}
    assert {c["run_type"] for c in ls.created if c["name"].endswith("_search")} == {"retriever"}
    # the root run id is the request id, and ask() hands it back as trace_id
    assert str(roots[0]["id"]) == REQUEST_ID == r["trace_id"]


# ---- metadata mode: no content ----

def test_metadata_mode_sends_no_question_query_answer_evidence_drug_or_patient_text(monkeypatch):
    ls = traced(monkeypatch)
    run("metadata")
    body = ls.payload()
    for text in (QUESTION, AGENT_QUERY, ANSWER, EVIDENCE, "Ozempic", "Rybelsus", "Jane", "Roe", "semaglutide",
                 "Assuming", FAKE_KEY, "test-salt"):
        assert text not in body, text
    assert all(c["inputs"] == {} for c in ls.created)


def test_stable_ids_and_aggregate_metrics_are_sent(monkeypatch):
    ls = traced(monkeypatch)
    r = run("metadata")
    root = ls.created[0]
    md = root["extra"]["metadata"]
    assert str(root["id"]) == md["request_id"] == REQUEST_ID and len(md["question_id"]) == 24
    assert md["question_id"] == telemetry.question_id(QUESTION) != telemetry.question_id("another question")
    assert md["question_chars_bucket"] == "50-99" and md["question_words_bucket"] == "10-19"
    assert md["programs"] == ["NY Medicaid"] and md["status"] == "answered" and md["needs_review"] is True
    assert md["agent_status"] == "answered" and md["flags"] == ["unverified_citation"]
    assert md["model_call_count"] == 3 and md["tool_call_count"] == 3
    assert md["tokens"] == r["tokens"] and md["cost_usd"] == r["cost_usd"] and md["citation_count"] == 2
    assert (md["user_id"], md["conversation_id"], md["generation"]) == ("user-42", "conv-7", 3)
    assert (md["provider"], md["model"], md["fallback_used"], md["cached"]) == ("openai", "gpt-5.5", False, False)
    assert md["latency_s"] == r["timing_s"]["total"] and md["primary_model"] == "gpt-5.5"
    assert md["fallback_model"] == "claude-sonnet-5-5" and md["search_mode"] == "hybrid" and md["rerank"] is False
    assert md["content_mode"] == "metadata"
    call = meta(ls, "agent_model_call")[0]
    assert call["call_number"] == 1 and call["model"] == "gpt-5.5" and call["stop_reason"] == "tool_use"
    assert call["provider"] == call["ls_provider"] == "openai" and call["ls_model_name"] == "gpt-5.5"
    assert call["tokens"] == {"input": 1000, "output": 100, "cache_read": 500, "cache_write": 0}
    assert call["cost_usd"] == pytest.approx(0.0031)
    assert outputs(ls, "agent_model_call")[0] == {"usage_metadata": {
        "input_tokens": 1500, "output_tokens": 100, "total_tokens": 1600,
        "input_token_details": {"cache_read": 500, "cache_creation": 0}}}
    search = meta(ls, "search_documents")[0]
    assert search["program"] == "NY Medicaid" and search["evidence_ids"] == ["ny_medicaid_pdl:p34", "ny_medicaid_pdl:p35"]
    merged = outputs(ls, "merge_and_rerank")[0]["results"]
    assert merged[0]["unit_id"] == "ny_medicaid_pdl:p34:c2" and merged[0]["source_scores"] == {"original": 0.91, "agent": 0.91}
    assert merged[1]["unit_id"].startswith("h:")              # a text-derived fallback id is hashed
    orig, agent = meta(ls, "original_question_search")[0], meta(ls, "agent_query_search")[0]
    assert orig["result_count"] == agent["result_count"] == 2 and orig["cache_hit"] is False
    hits = outputs(ls, "original_question_search")[0]["hits"]
    assert [h["rank"] for h in hits] == [1, 2] and hits[0]["unit_id"] == "ny_medicaid_pdl:p34:c2" and hits[0]["score"] == 0.91
    lookup = meta(ls, "structured_lookup")[0]
    assert lookup["program"] == "NY Medicaid" and lookup["outcome"] == "ok" and lookup["lookup_result"] == "exact_match"
    cv = meta(ls, "citation_validation")[0]
    assert cv["citation_ids"] == ["ny_medicaid_pdl:p34", "ny_medicaid_pdl:p99"] and cv["flag_categories"] == ["not_returned"]
    done = meta(ls, "answer_complete")[0]
    assert done["answer_words"] == r["words"]["displayed"] and done["needs_review"] is True


def test_without_a_salt_no_question_id_is_sent(monkeypatch):
    ls = traced(monkeypatch)
    monkeypatch.delenv("TRACE_HASH_SALT")
    run("metadata")
    assert ls.created[0]["extra"]["metadata"]["question_id"] is None


def test_the_completeness_flags_pass_the_flag_allowlist():
    ok = ["min_lookups_nudge", "completeness_pass", "completeness_pass_failed", "completeness_pass_skipped"]
    assert [f for f in ok + ["completeness_pass_x", "min_lookups"] if telemetry.FLAG.match(f)] == ok


def test_secrets_paths_and_free_text_never_pass_the_allowlists(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    path, key = "/Users/someone/code/secret.json", "sk-" + "q" * 24
    trace = {"question": "q", "status": f"answered {path}", "agent_status": key, "flags": ["unverified_citation", key, path],
             "timing_s": {"total": 1.0}, "tokens": {}, "cost_usd": 0.0, "citations": [], "words": {"displayed": 3},
             "config": {"primary": path, "search": {"mode": path}}, "needs_review": False, "provider": path, "model": path,
             "context": {"user_id": path, "conversation_id": "has spaces", "generation": "3"},
             "model_calls": [{"duration_s": 0.1, "requested_model": path, "served_model": "m", "stop_reason": key,
                              "provider": path, "fallback": False, "cost_usd": 0.0,
                              "usage": {"input": 1, "output": 1, "cache_read": 0, "cache_write": 0},
                              "input_messages": [{"role": "user", "text": path}], "output": {"text": key}}],
             "tool_calls": [{"name": "search_documents", "input": {"query": key, "program": path}, "duration_s": 0.1,
                             "is_error": True, "error_kind": f"tool_error at {path}", "pages": [], "result": path}]}
    body = json.dumps(telemetry.build(trace, "metadata"), default=str)
    assert path not in body and key not in body and "someone" not in body
    md = telemetry.build(trace, "metadata")["metadata"]
    assert md["status"] == "other" and md["agent_status"] == "other" and md["flags"] == ["unverified_citation"]
    assert md["primary_model"] is None and md["provider"] is None and md["model"] is None
    assert md["user_id"] is None and md["conversation_id"] is None and md["generation"] is None


# ---- full mode: inputs and outputs ----

def test_full_mode_sends_question_answer_citations_messages_tool_io_and_queries(monkeypatch):
    ls = traced(monkeypatch)
    r = run("full")
    root = ls.created[0]
    assert root["inputs"] == {"question": QUESTION}
    out = outputs(ls, "agent_answer")[0]
    assert out["answer"] == ANSWER and out["status"] == "answered" and out["needs_review"] is True
    assert [(c["doc_id"], c["page"], c["flag"]) for c in out["citations"]] == [
        ("ny_medicaid_pdl", 34, None), ("ny_medicaid_pdl", 99, "not returned by any tool during this question")]
    assert root["extra"]["metadata"]["content_mode"] == "full" and root["extra"]["metadata"]["user_id"] == "user-42"
    # llm runs: the messages each call saw (deltas), and the assistant reply
    llm_in, llm_out = inputs(ls, "agent_model_call"), outputs(ls, "agent_model_call")
    assert llm_in[0]["messages"][0]["role"] == "user" and QUESTION in llm_in[0]["messages"][0]["text"]
    assert llm_out[0]["message"]["tool_calls"][0] == {"id": llm_out[0]["message"]["tool_calls"][0]["id"],
                                                      "name": "search_documents",
                                                      "arguments": {"query": AGENT_QUERY, "program": "NY Medicaid"}}
    assert llm_in[1]["messages"][0]["role"] == "tool" and EVIDENCE in llm_in[1]["messages"][0]["tool_results"][0]["content"]
    assert llm_out[2]["message"]["tool_calls"][0]["arguments"]["answer"] == ANSWER
    assert "usage_metadata" in llm_out[0]
    # tool runs: arguments in, returned text out
    assert inputs(ls, "search_documents")[0] == {"query": AGENT_QUERY, "program": "NY Medicaid"}
    assert EVIDENCE in outputs(ls, "search_documents")[0]["output"]
    assert inputs(ls, "structured_lookup")[0] == {"drug": "Ozempic"}
    assert json.loads(outputs(ls, "structured_lookup")[0]["output"])["result"] == "exact_match"
    assert inputs(ls, "read_page")[0] == {"doc_id": "ny_medicaid_pdl", "page": 34}
    assert outputs(ls, "read_page")[0]["output"].startswith("ny_medicaid_pdl page 34")
    # retriever runs: the query and the hit list
    assert inputs(ls, "original_question_search")[0] == {"query": QUESTION}
    assert inputs(ls, "agent_query_search")[0] == {"query": AGENT_QUERY}
    assert outputs(ls, "agent_query_search")[0]["hits"][0]["doc_id"] == "ny_medicaid_pdl"
    assert r["trace_id"] == REQUEST_ID


def test_full_mode_still_redacts_secrets_and_caps_long_strings(monkeypatch):
    key = "sk-" + "z" * 30
    trace = {"question": f"q {key}", "status": "answered", "agent_status": "answered", "flags": [], "timing_s": {"total": 1.0},
             "tokens": {}, "cost_usd": 0.0, "citations": [], "words": {"displayed": 1}, "config": {}, "needs_review": False,
             "answer": "a" * 10_000, "context": {},
             "model_calls": [], "tool_calls": [{"name": "read_page", "input": {"doc_id": "d", "page": 1, "api_key": "x"},
                                                "duration_s": 0.1, "is_error": False, "pages": [], "result": "r" * 9000}]}
    root = telemetry.scrub(telemetry.build(trace, "full"))   # what the client's hide_* hooks apply
    assert key not in json.dumps(root) and root["inputs"]["question"] == "q [redacted]"
    assert root["outputs"]["answer"].startswith("a" * telemetry.MAX_STR) and "[5904 chars]" in root["outputs"]["answer"]
    tool_run = root["children"][0]
    assert tool_run["inputs"]["api_key"] == "[redacted]" and len(tool_run["outputs"]["output"]) < 4100
    assert telemetry.make_client is not None


@pytest.mark.parametrize("env, conf, expected", [
    (None, "full", "full"), (None, "metadata", "metadata"), (None, "development", "metadata"), (None, None, "metadata"),
    ("metadata", "full", "metadata"), ("full", "metadata", "full"), ("raw", "full", "metadata"), ("", "full", "metadata"),
    (" FULL ", "metadata", "full"),
])
def test_content_mode_env_overrides_config_and_unknown_values_mean_metadata(monkeypatch, env, conf, expected):
    if env is not None:
        monkeypatch.setenv("LANGSMITH_CONTENT_MODE", env)
    assert telemetry.content_mode({"tracing_v2": {"content": conf}} if conf else {}) == expected


@pytest.mark.parametrize("mode", ["development", "Development ", "dev", "raw", "true", ""])
def test_unknown_content_modes_send_no_content(monkeypatch, mode):
    ls = traced(monkeypatch, mode=mode)
    run("full")   # config asks for full; the environment's unknown value wins and means metadata
    body = ls.payload()
    for text in (QUESTION, AGENT_QUERY, ANSWER, EVIDENCE, "Ozempic", "Rybelsus", "Jane", "semaglutide"):
        assert text not in body, (mode, text)
    assert all(c["inputs"] == {} for c in ls.created)
    assert ls.created[0]["extra"]["metadata"]["content_mode"] == "metadata"


def test_env_metadata_switches_a_full_deployment_back(monkeypatch):
    ls = traced(monkeypatch, mode="metadata")
    run("full")
    assert QUESTION not in ls.payload() and ls.created[0]["extra"]["metadata"]["content_mode"] == "metadata"


# ---- isolation ----

def test_disabled_tracing_is_a_no_op(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("a LangSmith client was made with tracing off")
    monkeypatch.setattr(telemetry, "_client", None)
    monkeypatch.setattr(telemetry, "make_client", boom)
    monkeypatch.setattr(telemetry, "build", lambda t, m: boom())
    for value in ("false", "", "yes"):
        monkeypatch.setenv("LANGSMITH_TRACING", value)
        assert run("full")["trace_id"] is None
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.delenv("LANGSMITH_API_KEY")
    assert run("full")["trace_id"] is None


def _comparable(r):
    return json.dumps({k: v for k, v in r.items() if k != "trace_id"}, sort_keys=True, ensure_ascii=False)


def test_a_langsmith_failure_never_changes_the_answer(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    plain = run("full")
    traced(monkeypatch, fail=True)
    failed = run("full")
    assert _comparable(failed) == _comparable(plain) and failed["trace_id"] == REQUEST_ID
    monkeypatch.setattr(telemetry, "build", lambda t, m: 1 / 0)   # a bug while building is swallowed too
    broken = run("full")
    assert _comparable(broken) == _comparable(plain) and broken["trace_id"] is None


@pytest.mark.parametrize("mode", ["metadata", "full"])
def test_traced_and_untraced_responses_are_identical_apart_from_the_trace_id(monkeypatch, mode):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    plain = run(mode)
    ls = traced(monkeypatch)
    with_trace = run(mode)
    assert ls.created and _comparable(with_trace) == _comparable(plain)
    assert plain["trace_id"] is None and with_trace["trace_id"] == REQUEST_ID


def test_the_local_trace_keeps_the_full_detail(monkeypatch, tmp_path):
    from pharmassist.agent import loop
    monkeypatch.setattr(loop, "project_path", lambda name: tmp_path)
    monkeypatch.setattr(loop, "PROJECT_ROOT", tmp_path)
    traced(monkeypatch)
    r = run("metadata", save_trace=True)
    local = (tmp_path / r["trace_path"]).read_text()
    assert QUESTION in local and ANSWER in local and AGENT_QUERY in local


def test_a_full_backlog_drops_traces_instead_of_queueing_without_bound(monkeypatch):
    import threading
    gate = threading.Event()
    ls = traced(monkeypatch)
    monkeypatch.setattr(telemetry, "MAX_PENDING", 2)
    monkeypatch.setattr(telemetry, "_safe_post", lambda *a: gate.wait(5))
    trace = {"question": "q", "timing_s": {"total": 0.0}, "citations": [], "request_id": REQUEST_ID}
    ids = [telemetry.emit(trace) for _ in range(5)]
    assert len([f for f in telemetry._pending if not f.done()]) <= 2
    assert ids[:2] == [REQUEST_ID, REQUEST_ID] and ids[2:] == [None, None, None]   # dropped traces return no id
    gate.set()
    telemetry.flush()
    assert ls.created == []


def test_an_invalid_request_id_gets_a_fresh_run_id(monkeypatch):
    traced(monkeypatch)
    monkeypatch.setattr(telemetry, "_safe_post", lambda *a: None)
    rid = telemetry.emit({"question": "q", "timing_s": {"total": 0.0}, "citations": [], "request_id": "not-a-uuid"})
    import uuid
    assert uuid.UUID(rid) and rid != "not-a-uuid"


TOOL = {"tool_name", "duration_s", "outcome", "error_category", "evidence_ids", "result_count", "doc_ids"}
SPAN_FIELDS = {
    "agent_answer": {"request_id", "user_id", "conversation_id", "generation", "question_id", "question_chars_bucket",
                     "question_words_bucket", "programs", "status", "agent_status", "flags", "needs_review", "latency_s",
                     "model_call_count", "tool_call_count", "tokens", "cost_usd", "citation_count", "provider", "model",
                     "fallback_used", "cached", "primary_model", "fallback_model", "effort", "search_mode", "rrf_k",
                     "fusion_depth", "return_parents", "rerank", "content_mode"},
    "agent_model_call": {"model", "served_model", "provider", "call_number", "latency_s", "stop_reason", "fallback",
                         "tokens", "cost_usd", "ls_provider", "ls_model_name"},
    "search_documents": TOOL | {"program"},
    "original_question_search": {"program", "k", "result_count", "cache_hit", "seconds"},
    "agent_query_search": {"program", "k", "result_count", "cache_hit", "seconds"},
    "merge_and_rerank": {"returned", "duplicates_merged", "from_both", "from_original_only", "from_agent_only"},
    "structured_lookup": TOOL | {"program", "lookup_result", "rows"},
    "read_page": TOOL | {"page"},
    "citation_validation": {"citation_count", "citation_ids", "flagged", "flag_categories"},
    "answer_complete": {"answer_words", "citation_ids", "citation_flags", "needs_review"},
}


@pytest.mark.parametrize("mode", ["metadata", "full"])
def test_each_span_carries_exactly_its_own_fields(monkeypatch, mode):
    ls = traced(monkeypatch)
    run(mode)
    assert {c["name"] for c in ls.created} == set(SPAN_FIELDS)
    for c in ls.created:
        assert set(c["extra"]["metadata"]) == SPAN_FIELDS[c["name"]], c["name"]


def test_no_parent_or_root_metadata_is_copied_into_children(monkeypatch):
    ls = traced(monkeypatch)
    run("metadata")
    root = ls.created[0]["extra"]["metadata"]
    search = meta(ls, "search_documents")[0]
    for c in ls.created[1:]:
        md = c["extra"]["metadata"]
        assert "request_id" not in md and "question_id" not in md and "status" not in md and "user_id" not in md
        if c["name"] != "agent_model_call":
            assert "cost_usd" not in md and "tokens" not in md, c["name"]
    for name in ("original_question_search", "agent_query_search", "merge_and_rerank"):
        md = meta(ls, name)[0]
        assert not {"duration_s", "evidence_ids", "doc_ids", "tool_name"} & set(md), name
    # each sub-search reports its own count and timing, not its parent's
    orig = meta(ls, "original_question_search")[0]
    assert orig["result_count"] == 2 and search["result_count"] == 2 and orig["seconds"] != search["duration_s"]
    assert root["cost_usd"] == pytest.approx(sum(m["cost_usd"] for m in meta(ls, "agent_model_call")))


def test_a_fallback_call_is_visible_on_the_model_call_and_the_root(monkeypatch):
    from tests.test_agent_fakes import error, submit
    ls = traced(monkeypatch)
    router = make_router(error(500, retryable=True), error(500, retryable=True),
                         fallback_script=[reply(submit([("ny_medicaid_pdl", 34)]))])
    from pharmassist.agent import tools
    box = tools.ToolBox(FakeStore(), FakeSearch({QUESTION: HITS}), cfg=cfg_with("metadata"), question=QUESTION)
    ask(QUESTION, router=router, tools=box, cfg=cfg_with("metadata"), request_id=REQUEST_ID)
    telemetry.flush()
    md = ls.created[0]["extra"]["metadata"]
    assert (md["provider"], md["model"], md["fallback_used"]) == ("anthropic", "claude-sonnet-5-5", True)
    call = meta(ls, "agent_model_call")[0]
    assert call["fallback"] is True and call["ls_provider"] == "anthropic" and call["model"] == "claude-sonnet-5-5"
