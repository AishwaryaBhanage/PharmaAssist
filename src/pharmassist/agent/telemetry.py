"""LangSmith tracing for the agent, built from ask()'s finished trace.

ask() calls emit(trace, cfg) once, after the answer exists, and gets the root run id back (the API
stores it as the message's trace_id). emit() never raises and never changes the answer: it builds
plain payloads from the trace (about a millisecond) and hands them to one background worker, which
posts them through LangSmith's batching client. Tracing off (LANGSMITH_TRACING not "true", or no
key) makes emit() a no-op; a backlog over MAX_PENDING drops the trace; LangSmith errors are swallowed.

Two content modes (config tracing_v2.content, overridden by LANGSMITH_CONTENT_MODE):
- full (v2's default): the root run carries the question as inputs and the answer, status and
  citations as outputs; each model call is an `llm` run with the messages it saw (text, tool calls
  and tool results) and the assistant's reply; each tool call is a `tool` run with its arguments and
  the text it returned (cut at OUTPUT_CHARS); each search is a `retriever` run with its query and
  hits. Secrets are still redacted and strings capped.
- metadata (v1's behaviour, still available): ids, categories, counts, ranks, scores, timings,
  tokens and cost only; never a question, answer, query, drug name, page or row text. The question
  is identified by an HMAC of its normalized text with TRACE_HASH_SALT; without the salt no id is sent.

Hierarchy: agent_answer > agent_model_call*, search_documents > (original_question_search,
agent_query_search, merge_and_rerank), structured_lookup, read_page, list_documents,
citation_validation, answer_complete.
"""

import hashlib
import hmac
import os
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from functools import cache

from pharmassist.config import PROJECT_ROOT

SECRET_KEY = re.compile(r"(^|_)(api_?key|secret|password|authorization|access_?key|session_?token)$", re.I)
SECRET_VALUE = re.compile(r"(sk-[A-Za-z0-9_-]{12,}|pcsk_[A-Za-z0-9_-]{12,}|lsv2_[A-Za-z0-9_-]{12,}"
                          r"|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{20,})")
MAX_PENDING = 50                 # traces waiting to be posted; more are dropped
TIMEOUT_MS = (2_000, 5_000)      # LangSmith connect / read timeouts
OUTPUT_CHARS = 4000              # of a tool result or tool-result message kept in a run
MAX_STR = 4096                   # any string sent is cut here (after OUTPUT_CHARS, so headroom for the cut marker)
MODES = ("full", "metadata")
PROGRAMS = ("VA", "Medicare Part D", "NY Medicaid")
LOOKUP_PROGRAM = {"lookup_va_formulary": "VA", "lookup_ny_medicaid_drug": "NY Medicaid"}
STATUSES = ("answered", "no_answer")
AGENT_STATUSES = ("answered", "not_in_documents", "out_of_scope", "refused", "no_answer")
FLAG = re.compile(r"^(nudged_to_submit|no_submit|no_answer|no_answer_rule|unverified_citation|budget_spent:(tool_cap|deadline)"
                  r"|min_lookups_nudge|completeness_pass(_failed|_skipped)?)$")
CATEGORY = re.compile(r"^[a-z][a-z_]{1,40}$")
STABLE_ID = re.compile(r"^[a-z0-9_]+(?::[A-Za-z0-9_.#-]+)*$")
MODEL_NAME = re.compile(r"^[A-Za-z0-9._:-]{1,80}$")
CITATION_FLAG = {"unknown doc_id": "unknown_doc", "not returned by any tool during this question": "not_returned"}

_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="langsmith")
_lock = threading.Lock()
_pending: list = []
_client = None


# ---- configuration ----

@cache
def _load_env() -> None:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")


def _env(name: str) -> str | None:
    """An environment variable's value (never logged), with .env loaded once first."""
    _load_env()
    return os.environ.get(name) or None


def enabled() -> bool:
    return (_env("LANGSMITH_TRACING") or "").lower() == "true" and bool(_env("LANGSMITH_API_KEY"))


def content_mode(cfg: dict | None = None) -> str:
    """'full' or 'metadata'. When LANGSMITH_CONTENT_MODE is set it decides (so a deployment switches back
    to v1 behaviour with `metadata`); otherwise config tracing_v2.content does. Only the exact word
    'full' sends content: any other value, in either place, means metadata."""
    if "LANGSMITH_CONTENT_MODE" in os.environ:
        value = _env("LANGSMITH_CONTENT_MODE") or ""
    else:
        value = str(((cfg or {}).get("tracing_v2") or {}).get("content") or "")
    return "full" if value.strip().lower() == "full" else "metadata"


def scrub(obj):
    """Secret-named keys and secret-shaped values are redacted; strings are capped at MAX_STR."""
    if isinstance(obj, dict):
        return {k: ("[redacted]" if SECRET_KEY.search(str(k)) else scrub(v)) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [scrub(v) for v in obj]
    if isinstance(obj, str):
        s = SECRET_VALUE.sub("[redacted]", obj)
        return s if len(s) <= MAX_STR else s[:MAX_STR] + f"…[{len(s) - MAX_STR} chars]"
    return obj


def make_client():
    import langsmith
    return langsmith.Client(timeout_ms=TIMEOUT_MS, omit_traced_runtime_info=True,
                            hide_inputs=scrub, hide_outputs=scrub, hide_metadata=scrub)


def _get_client():
    global _client
    if _client is None:
        _client = make_client()
    return _client


# ---- identifiers and buckets ----

def question_id(question: str) -> str | None:
    salt = _env("TRACE_HASH_SALT")
    if not salt:
        return None
    norm = " ".join(re.findall(r"\w+", question.lower()))
    return hmac.new(salt.encode(), norm.encode(), hashlib.sha256).hexdigest()[:24]


def bucket(n: int, edges=(50, 100, 200, 400, 800)) -> str:
    lo = 0
    for e in edges:
        if n < e:
            return f"{lo}-{e - 1}"
        lo = e
    return f"{lo}+"


def stable(unit: str) -> str:
    """A unit id as is when it's an id, else a short hash (a fallback id can embed text)."""
    return unit if STABLE_ID.match(unit or "") else "h:" + hashlib.sha256((unit or "").encode()).hexdigest()[:16]


def _category(v) -> str | None:
    return v if isinstance(v, str) and CATEGORY.match(v) else None


def _model(v) -> str | None:
    return v if isinstance(v, str) and MODEL_NAME.match(v) else None


def _ident(v) -> str | None:
    """A user, conversation or request id: a short token, never free text."""
    return v if isinstance(v, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", v) else None


def _cut(text) -> str | None:
    return text[:OUTPUT_CHARS] if isinstance(text, str) else None


# ---- payloads ----

def _span(name, run_type, t_start, duration, metadata, outputs=None, children=(), error=None, inputs=None):
    """One span's payload. In metadata mode `inputs` is always empty."""
    return {"name": name, "run_type": run_type, "t_start": t_start or 0.0, "duration": duration or 0.0,
            "metadata": metadata, "inputs": inputs or {}, "outputs": outputs or {}, "children": list(children),
            "error": error}


def _source_hits(meta: dict, source: str) -> list[dict]:
    hits = [{"unit_id": stable(h["unit"]), "doc_id": h["doc_id"], "pages": h["pages"], "rank": h["ranks"][source],
             "score": (h.get("scores") or {}).get(source)} for h in meta.get("hits", []) if source in (h.get("ranks") or {})]
    return sorted(hits, key=lambda h: h["rank"])


def _search_spans(call: dict, full: bool) -> list[dict]:
    meta, t0, dur = call.get("search") or {}, call.get("t_start", 0.0), call["duration_s"]
    subs, wall = [], 0.0
    for e in meta.get("executed", []):
        name = "original_question_search" if e["source"] == "original" else "agent_query_search"
        wall = max(wall, e.get("seconds") or 0.0)
        md = {"program": e["program"] if e.get("program") in PROGRAMS else None, "k": e.get("k"),
              "result_count": e.get("results"), "cache_hit": bool(e.get("cached")), "seconds": e.get("seconds")}
        subs.append(_span(name, "retriever", t0, e.get("seconds"), md, outputs={"hits": _source_hits(meta, e["source"])},
                          inputs={"query": e.get("query")} if full else None))
    hits = meta.get("hits", [])
    # RRF fusion of the two searches (each search already reranked its own results)
    merge = _span("merge_and_rerank", "chain", t0 + wall, max(dur - wall, 0.0), {
        "returned": meta.get("returned"),
        "duplicates_merged": meta.get("duplicates_merged"), "from_both": meta.get("from_both"),
        "from_original_only": meta.get("from_original_only"), "from_agent_only": meta.get("from_agent_only")},
        outputs={"results": [{"rank": i, "unit_id": stable(h["unit"]), "doc_id": h["doc_id"], "pages": h["pages"],
                              "source_ranks": h.get("ranks"), "source_scores": h.get("scores")}
                             for i, h in enumerate(hits, 1)]})
    return subs + [merge]


def _tool_span(call: dict, full: bool) -> dict:
    name = call["name"]
    md = {"tool_name": name, "duration_s": call["duration_s"], "outcome": "error" if call["is_error"] else "ok",
          "error_category": _category(call.get("error_kind")) if call["is_error"] else None,
          "evidence_ids": call.get("pages", []), "result_count": len(call.get("pages", []))}
    md["doc_ids"] = sorted({p.split(":")[0] for p in md["evidence_ids"]})
    children = []
    if name == "search_documents":
        md["program"] = call["input"].get("program") if call["input"].get("program") in PROGRAMS else None
        md["result_count"] = (call.get("search") or {}).get("returned", md["result_count"])
        children = _search_spans(call, full)
        span_name = "search_documents"
    elif name.startswith("lookup_"):
        lk = call.get("lookup") or {}
        md.update(program=LOOKUP_PROGRAM.get(name), lookup_result=_category(lk.get("result")), rows=lk.get("rows"))
        span_name = "structured_lookup"
    elif name == "read_page":
        md["page"] = call["input"].get("page") if isinstance(call["input"].get("page"), int) else None
        span_name = "read_page"
    else:
        span_name = name if name in ("list_documents",) else "tool"
    inputs = dict(call.get("input") or {}) if full else None
    outputs = {"output": _cut(call.get("result"))} if full else None
    return _span(span_name, "tool", call.get("t_start"), call["duration_s"], md, outputs=outputs, children=children,
                 error=md["error_category"] if call["is_error"] else None, inputs=inputs)


def _usage_metadata(u: dict) -> dict:
    return {"input_tokens": u["input"] + u["cache_read"] + u["cache_write"], "output_tokens": u["output"],
            "total_tokens": u["input"] + u["cache_read"] + u["cache_write"] + u["output"],
            "input_token_details": {"cache_read": u["cache_read"], "cache_creation": u["cache_write"]}}


def _model_call_span(c: dict, i: int, full: bool) -> dict:
    u = c["usage"]
    provider = c.get("provider") if c.get("provider") in ("openai", "anthropic") else None
    md = {"model": _model(c.get("requested_model")), "served_model": _model(c.get("served_model")), "provider": provider,
          "call_number": i, "latency_s": c["duration_s"], "stop_reason": _category(c.get("stop_reason")),
          "fallback": bool(c.get("fallback")), "tokens": u, "cost_usd": c.get("cost_usd"),
          "ls_provider": provider, "ls_model_name": _model(c.get("served_model") or c.get("requested_model"))}
    outputs = {"usage_metadata": _usage_metadata(u)}
    inputs = None
    if full:
        inputs = {"messages": c.get("input_messages") or []}
        outputs["message"] = c.get("output") or {}
    return _span("agent_model_call", "llm", c.get("t_start"), c["duration_s"], md, outputs=outputs, inputs=inputs)


def build(trace: dict, mode: str = "metadata") -> dict:
    """The root span, with its children, from ask()'s trace. `mode` is 'full' or 'metadata'."""
    full = mode == "full"
    calls, tool_calls = trace.get("model_calls", []), trace.get("tool_calls", [])
    children = [_model_call_span(c, i, full) for i, c in enumerate(calls, 1)]
    children += [_tool_span(c, full) for c in tool_calls]
    # the model's citations as checked (the public list is empty on a no-answer)
    cites = trace.get("model_citations") if "model_citations" in trace else trace.get("citations", [])
    cites = cites or []
    cite_ids = [c.get("locator") for c in cites]
    cite_flags = [CITATION_FLAG.get(c.get("flag")) for c in cites if c.get("flag")]
    cc = trace.get("citation_check") or {}
    children.append(_span("citation_validation", "chain", cc.get("t_start"), cc.get("duration_s"), {
        "citation_count": len(cites), "citation_ids": cite_ids, "flagged": len(cite_flags),
        "flag_categories": sorted(set(f for f in cite_flags if f))}))
    total = (trace.get("timing_s") or {}).get("total", 0.0)
    words = (trace.get("words") or {}).get("displayed")
    children.append(_span("answer_complete", "chain", total, 0.0, {
        "answer_words": words, "citation_ids": cite_ids, "citation_flags": sorted(set(f for f in cite_flags if f)),
        "needs_review": trace.get("needs_review")}))
    question = trace.get("question") or ""
    programs = sorted({c["input"].get("program") for c in tool_calls if c["name"] == "search_documents"
                       and c["input"].get("program") in PROGRAMS} |
                      {LOOKUP_PROGRAM[c["name"]] for c in tool_calls if c["name"] in LOOKUP_PROGRAM})
    status, agent_status = trace.get("status"), trace.get("agent_status")
    ctx, conf = trace.get("context") or {}, trace.get("config") or {}
    search = conf.get("search") or {}
    root_md = {
        "request_id": trace.get("request_id"), "user_id": _ident(ctx.get("user_id")),
        "conversation_id": _ident(ctx.get("conversation_id")),
        "generation": ctx.get("generation") if isinstance(ctx.get("generation"), int) else None,
        "question_id": question_id(question),
        "question_chars_bucket": bucket(len(question)), "question_words_bucket": bucket(len(question.split()), (10, 20, 40, 80)),
        "programs": programs, "status": status if status in STATUSES else "other",
        "agent_status": agent_status if agent_status in AGENT_STATUSES else "other",
        "flags": [f for f in trace.get("flags", []) if FLAG.match(f)], "needs_review": trace.get("needs_review"),
        "latency_s": total, "model_call_count": len(calls), "tool_call_count": len(tool_calls),
        "tokens": trace.get("tokens"), "cost_usd": trace.get("cost_usd"), "citation_count": len(cites),
        "provider": trace.get("provider") if trace.get("provider") in ("openai", "anthropic") else None,
        "model": _model(trace.get("model")), "fallback_used": bool(trace.get("fallback_used")), "cached": False,
        "primary_model": _model(conf.get("primary")), "fallback_model": _model(conf.get("fallback")),
        "effort": _category(conf.get("effort")),
        "search_mode": _category(search.get("mode")), "rrf_k": search.get("rrf_k"),
        "fusion_depth": search.get("fusion_depth"), "return_parents": search.get("return_parents"),
        "rerank": bool(search.get("rerank")), "content_mode": mode}
    outputs = {"status": root_md["status"], "needs_review": trace.get("needs_review")}
    inputs = None
    if full:
        inputs = {"question": question}
        outputs.update(answer=trace.get("answer"), citations=[{k: c.get(k) for k in ("doc_id", "page", "row", "locator",
                                                                                     "link", "flag") if k in c}
                                                             for c in trace.get("citations") or []])
    return _span("agent_answer", "chain", 0.0, total, root_md, children=children, outputs=outputs, inputs=inputs) | {
        "request_id": trace.get("request_id"), "started_utc": trace.get("request_started_utc")}


# ---- submission ----

def _run_id(request_id) -> uuid.UUID:
    try:
        return uuid.UUID(str(request_id))
    except (ValueError, TypeError, AttributeError):
        return uuid.uuid4()


def _post(root: dict, client, project: str | None) -> None:
    from langsmith import RunTree
    t0 = datetime.fromisoformat(root["started_utc"]) if root.get("started_utc") else datetime.now(timezone.utc)
    at = lambda s: t0 + timedelta(seconds=s)

    def send(span, parent=None, run_id=None):
        kw = dict(name=span["name"], run_type=span["run_type"], inputs=span.get("inputs") or {},
                  start_time=at(span["t_start"]), extra={"metadata": span["metadata"]})
        if parent is None:
            run = RunTree(**kw, id=run_id, project_name=project, ls_client=client, tags=["agent"])
        else:
            # built directly rather than with create_child(), which copies the parent's metadata into
            # every child: each span carries only its own fields
            run = RunTree(**kw, parent_run=parent, project_name=parent.session_name, ls_client=parent.ls_client)
        run.post()
        for child in span["children"]:
            send(child, run)
        run.end(outputs=span["outputs"], error=span["error"], end_time=at(span["t_start"] + span["duration"]))
        run.patch()

    send(root, run_id=root["run_id"])


def emit(trace: dict, client=None, cfg: dict | None = None) -> str | None:
    """Queue one agent trace for LangSmith and return the root run id (None when tracing is off or
    the trace was dropped). Never raises."""
    try:
        if not enabled():
            return None
        root = build(trace, content_mode(cfg))
        root["run_id"] = _run_id(root.get("request_id"))
        project = _env("LANGSMITH_PROJECT")
        with _lock:
            _pending[:] = [f for f in _pending if not f.done()]
            if len(_pending) >= MAX_PENDING:
                return None
            _pending.append(_worker.submit(_safe_post, root, client, project))
        return str(root["run_id"])
    except Exception:
        return None


def _safe_post(root, client, project) -> None:
    try:
        _post(root, client or _get_client(), project)
    except Exception:
        pass  # tracing trouble never reaches the answer


def flush(timeout: float = 5.0) -> None:
    """Wait (bounded) for queued traces to be posted; for scripts that exit right after answering."""
    try:
        with _lock:
            pending = list(_pending)
        for f in pending:
            f.result(timeout=timeout)
        if _client is not None:
            _client.flush(timeout=timeout)
    except Exception:
        pass
