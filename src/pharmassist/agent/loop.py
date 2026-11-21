"""ask(): one question in, one structured answer out.

A manual tool loop over the provider-independent `Router` (llm/router.py): the loop builds canonical
`Message`s (llm/base.py), the router runs each call on OpenAI and falls back to Sonnet when OpenAI
can't answer, and once a thread has fallen back the loop keeps passing `prefer=` so the rest of the
turn stays on the serving provider. The request prefix (system, tools, earlier turns) is never
edited: when the budget is spent, a user-role note tells the model to submit, and any further
lookups get an error result instead of running. A reply without submit_answer gets one nudge (a
user turn) to resubmit through it, so the answer keeps its citations.

Two completeness measures (both config, agent.*): an "answered" submit after fewer than `min_lookups`
lookups gets one error result asking for one more lookup (time and cap permitting; the next submit
is accepted whatever the count), and an accepted "answered" submit is followed, when at least
`completeness_min_remaining_s` of the 30 s remain, by one more model turn: a user-role note asks the
model to compare its answer with the evidence already returned and resubmit with any omitted point
added, lookups closed. Its submit replaces the first; a failed turn, a text reply or a lookup
attempt keeps the first answer. Neither changes what is retrieved, and the citation check and the
no-answer rule run on whichever submit is final.

The model's answer is returned as written; nothing rewrites it. Citations to pages or rows no tool
returned are flagged (`unverified_citation`). The no-answer rule (DESIGN.md, Quality): `agent_status` keeps
the model's own status; the public `status` is "answered" only when the model answered AND at least
one citation survived the check unflagged. Everything else returns exactly NO_ANSWER_TEXT with no
citations, so the API and the cache never see a half-supported answer. The trace keeps the model's
text (`model_answer`) and the cited evidence, so the offline checks (agent/offline.py) can still run
later, in evaluation or diagnostics only.

After the answer is built, agent/telemetry.py queues the LangSmith trace (inputs and outputs when
tracing_v2.content is "full", metadata only otherwise). It is a no-op when tracing is off and can't
raise, block or change the answer; its root run id comes back as `trace_id`.
"""

import json
import re
import time
import uuid
from datetime import date, datetime, timezone

from pharmassist.agent import telemetry
from pharmassist.agent.prompt import system_prompt
from pharmassist.agent.tools import ToolBox, locator, page_link, tool_defs
from pharmassist.config import PROJECT_ROOT, project_path
from pharmassist.eval.scoring import word_count
from pharmassist.llm.base import Message, TextPart, ToolResult
from pharmassist.store.protocols import NO_ANSWER_TEXT

HARD_LIMIT_S = 30  # end-to-end requirement; each request's timeout is what's left of it
BUDGET_SPENT = ("Lookup budget spent. Call submit_answer now with what you have; say what you "
                "couldn't verify.")
SUBMIT_NUDGE = ("You replied without calling submit_answer. Call submit_answer now with the same "
                "answer, its status and the pages that support it.")
MIN_LOOKUPS_NUDGE = ("Before submitting, run at least one more lookup that could change or complete this "
                     "answer: search the part of the question you have not yet covered, or the same question "
                     "with the other relevant program, or read the cited page. Then call submit_answer again.")
MIN_LOOKUPS_RESERVE_S = 6  # the nudge needs this much before the deadline for the lookup and the resubmit
COMPLETENESS_CHECK = (
    "Completeness check. Compare your answer with the evidence the tools returned in this conversation. "
    "List, for yourself, any condition, quantity or day limit, exception, effective date, step of a process "
    "or alternative channel, older-version difference, or program distinction that the evidence states for "
    "this question and your answer omits. Then call submit_answer again: the same answer with those points "
    "added in one or two sentences each, each cited to the page or row that states it; if nothing is "
    "missing, resubmit the same answer unchanged. Do not add anything the evidence does not state; do not "
    "remove correct content; do not run more lookups.")
SUBMIT_RECEIVED = "Answer received."  # the result the accepted submit_answer call gets before the completeness check
LOOKUPS_CLOSED = "lookups are closed; call submit_answer"
REVIEW = "Please have a pharmacist review it before acting."
REFUSED = f"The model declined this question, and no fallback model answered it. {REVIEW}"
NO_ANSWER = f"No answer was submitted within the turn limit. {REVIEW}"
EVIDENCE_CHARS = 6000  # per cited page kept in the trace for the offline checks
AGENT_STATUSES = ("answered", "not_in_documents", "out_of_scope", "no_answer", "refused")


def check_citations(citations: list[dict], seen: set[str], cat: dict | None = None) -> list[dict]:
    """Attach a link to each citation and flag any page or sheet row no tool returned during
    this question. `cat` is the store's catalog (the file catalog when omitted)."""
    if cat is None:
        from pharmassist.agent.tools import catalog
        cat = catalog()
    out = []
    for c in citations:
        doc_id, page, row = c.get("doc_id"), c.get("page"), c.get("row")
        loc = locator(doc_id, page, row)
        flag = None
        if doc_id not in cat:
            flag = "unknown doc_id"
        elif loc not in seen:
            flag = "not returned by any tool during this question"
        item = {"doc_id": doc_id, "page": page, "link": page_link(doc_id, page, cat), "flag": flag,
                "locator": loc}
        if row is not None:
            item["row"] = row
        out.append(item)
    return out


def _message_record(m: Message) -> dict:
    """A message as the trace and LangSmith's llm runs see it: role, text, tool calls or results."""
    rec = {"role": m.role}
    if m.text:
        rec["text"] = m.text
    calls = [{"id": c.id, "name": c.name, "arguments": c.arguments} for c in m.tool_calls]
    if calls:
        rec["tool_calls"] = calls
    results = [{"call_id": r.call_id, "is_error": r.is_error, "content": r.content[:telemetry.OUTPUT_CHARS]}
               for r in m.parts if isinstance(r, ToolResult)]
    if results:
        rec["tool_results"] = results
    return rec


def ask(question: str, *, router, tools: ToolBox, cfg: dict, context: dict | None = None,
        clock=time.perf_counter, today: date | None = None, request_id: str | None = None,
        save_trace: bool = False) -> dict:
    """`router`: a Router (llm/router.py). `tools`: a fresh ToolBox for this question (its `question`
    is set here when None). `cfg`: the whole config (agent.*, llm.*, search.*, tracing_v2.*).
    `context`: {"user_id", "conversation_id", "generation"} for telemetry only; it never changes the
    answer. `request_id`: the caller's id for this request, used for the trace and LangSmith."""
    acfg, lcfg = cfg["agent"], cfg.get("llm", {})
    today = today or date.today()
    start = clock()
    started_utc = datetime.now(timezone.utc)
    request_id = request_id or str(uuid.uuid4())
    if tools.question is None:
        tools.question = question
    tools.clock = clock   # one clock for the loop and its tools, so the trace's timings line up
    structured = tools.structured
    system, specs = system_prompt(structured, tuple(acfg.get("prompt_extras") or ())), tool_defs(structured)
    call_timeout = float(lcfg.get("call_timeout_s", HARD_LIMIT_S))

    min_lookups = int(acfg.get("min_lookups", 2))
    completeness_on = bool(acfg.get("completeness_pass", True))
    completeness_min_s = float(acfg.get("completeness_min_remaining_s", 8))

    messages = [Message("user", [TextPart(f"Today's date: {today.isoformat()}\n\nQuestion: {question}")])]
    model_calls, lookups, final, final_call, flags = [], 0, None, None, []
    budget_note_sent = nudged = min_nudged = False
    submitted = False  # whether `final` came from a submit_answer call (the completeness pass needs one)
    text_reply = ""  # a plain-text answer kept in case the nudge doesn't produce a submit
    state = {"prefer": None,  # the provider that served this thread's last call
             "sent": 0}       # messages already shown to the model (for the per-call input record)

    def complete(tool_choice="auto"):
        """One model call on the thread so far, recorded in model_calls (usage, cost, timing)."""
        elapsed = clock() - start
        t0 = clock()
        c = router.complete(system=system, messages=messages, tools=specs,
                            timeout_s=max(5.0, min(call_timeout, HARD_LIMIT_S - elapsed)), prefer=state["prefer"],
                            tool_choice=tool_choice)
        state["prefer"] = c.provider
        call = {"t_start": round(t0 - start, 3), "duration_s": round(clock() - t0, 3),
                "requested_model": c.requested_model, "served_model": c.model, "provider": c.provider,
                "fallback": bool(c.fallback_used), "stop_reason": c.stop_reason,
                "usage": {"input": c.usage.input, "output": c.usage.output, "cache_read": c.usage.cache_read,
                          "cache_write": c.usage.cache_write},
                "cost_usd": c.cost_usd, "response_id": c.raw_id,
                "input_messages": [_message_record(m) for m in messages[state["sent"]:]],
                "output": _message_record(c.message)}
        model_calls.append(call)
        state["sent"] = len(messages)
        return c, call

    # each turn either runs lookups or submits; the cap bounds the loop even if the model stalls
    # (+4 covers the min-lookups nudge, the submit nudge and the budget-note turn, each at most once)
    for _ in range(acfg["max_tool_calls"] + 4):
        elapsed = clock() - start
        budget_spent = lookups >= acfg["max_tool_calls"] or elapsed >= acfg["deadline_s"]
        if budget_spent and not budget_note_sent:
            # a user-role note: OpenAI has no mid-thread system turn and Anthropic has none at all
            messages.append(Message("user", [TextPart(BUDGET_SPENT)]))
            budget_note_sent = True
            flags.append("budget_spent:" + ("tool_cap" if lookups >= acfg["max_tool_calls"] else "deadline"))

        c, call = complete()
        if c.stop_reason == "refusal":
            final = {"status": "refused", "assumption": None, "citations": [], "conflicts_noted": [],
                     "answer": REFUSED}
            final_call = call
            break
        messages.append(c.message)
        state["sent"] = len(messages)

        tool_uses = c.message.tool_calls
        submit = next((t for t in tool_uses if t.name == "submit_answer"), None)
        if submit is not None:
            # an "answered" submit after too few lookups is refused once, when a lookup can still run
            early = (submit.arguments.get("status") == "answered" and lookups < min_lookups and not min_nudged
                     and not budget_note_sent and lookups < acfg["max_tool_calls"]
                     and clock() - start < acfg["deadline_s"] - MIN_LOOKUPS_RESERVE_S)
            if not early:
                final, final_call, submitted = dict(submit.arguments), call, True
                break
            min_nudged = True
            flags.append("min_lookups_nudge")
        if not tool_uses:
            text = c.message.text.strip() or text_reply
            # no submit_answer: ask once (time permitting) for the same answer through submit_answer
            if not nudged and clock() - start < acfg["deadline_s"]:
                nudged, text_reply = True, text
                flags.append("nudged_to_submit")
                messages.append(Message("user", [TextPart(SUBMIT_NUDGE)]))
                continue
            # still none: keep the text rather than lose the answer, and flag it
            final = {"status": "answered", "assumption": None, "answer": text, "citations": [],
                     "conflicts_noted": []}
            final_call = call
            flags.append("no_submit")
            break

        results = []
        for tu in tool_uses:
            if tu.name == "submit_answer":   # the refused early submit; any lookups beside it still run
                content, is_error = MIN_LOOKUPS_NUDGE, True
            elif lookups >= acfg["max_tool_calls"] or budget_note_sent:
                content, is_error = BUDGET_SPENT, True
            else:
                lookups += 1
                t_tool, n_calls = clock(), len(tools.calls)
                content, is_error = tools.run(tu.name, tu.arguments)
                if len(tools.calls) > n_calls:
                    tools.calls[-1]["t_start"] = round(t_tool - start, 3)
            results.append(ToolResult(call_id=tu.id, content=content, is_error=is_error))
        messages.append(Message("tool", results))

    if final is None:
        flags.append("no_answer")
        final = {"status": "no_answer", "assumption": None, "citations": [], "conflicts_noted": [],
                 "answer": NO_ANSWER}

    completeness = None
    if submitted and final.get("status") == "answered" and completeness_on:
        completeness, first = {"ran": False, "changed": False, "added_words": 0, "outcome": "skipped"}, final
        if HARD_LIMIT_S - (clock() - start) < completeness_min_s:
            flags.append("completeness_pass_skipped")
        else:
            # close the submit turn (every tool call needs a result before a user turn), then ask once
            messages.append(Message("tool", [ToolResult(call_id=tu.id, is_error=tu.name != "submit_answer",
                                                        content=SUBMIT_RECEIVED if tu.name == "submit_answer"
                                                        else LOOKUPS_CLOSED) for tu in tool_uses]))
            messages.append(Message("user", [TextPart(COMPLETENESS_CHECK)]))
            t_pass = clock()
            try:
                c2, call2 = complete(tool_choice="submit_answer")
            except Exception as e:  # noqa: BLE001 - a failed pass never costs the answer we have
                completeness.update(ran=True, outcome="failed", error=type(e).__name__)
            else:
                completeness["ran"] = True
                uses2 = c2.message.tool_calls
                submit2 = next((t for t in uses2 if t.name == "submit_answer"), None)
                others = [t for t in uses2 if t.name != "submit_answer"]
                if c2.stop_reason == "refusal":
                    completeness["outcome"] = "refused"
                elif others:
                    # lookups are closed in this turn: refuse them, keep the first answer
                    messages.append(c2.message)
                    messages.append(Message("tool", [ToolResult(call_id=t.id, content=LOOKUPS_CLOSED, is_error=True)
                                                     for t in uses2]))
                    completeness.update(outcome="lookup_attempted", refused=[t.name for t in others])
                elif submit2 is None:
                    completeness["outcome"] = "no_submit"
                elif submit2.arguments.get("status") != "answered":
                    completeness["outcome"] = "status_changed"  # the pass may add, never withdraw the answer
                else:
                    messages.append(c2.message)
                    final, final_call = dict(submit2.arguments), call2
                    changed = (final.get("answer") != first.get("answer")
                               or (final.get("citations") or []) != (first.get("citations") or []))
                    completeness.update(outcome="replaced" if changed else "unchanged", changed=changed,
                                        added_words=word_count(final.get("answer") or "") - word_count(first.get("answer") or ""))
            completeness["duration_s"] = round(clock() - t_pass, 3)
            flags.append("completeness_pass" if completeness["outcome"] in ("replaced", "unchanged")
                         else "completeness_pass_failed")

    t_cite = clock()
    citations = check_citations(final.get("citations") or [], tools.seen, tools.catalog)
    citation_check = {"t_start": round(t_cite - start, 3), "duration_s": round(clock() - t_cite, 3)}
    if any(c["flag"] for c in citations):
        flags.append("unverified_citation")
    agent_status = final.get("status") if final.get("status") in AGENT_STATUSES else "no_answer"
    supported = [c for c in citations if not c["flag"]]
    # the no-answer rule: an answer needs the model's "answered" and one citation the tools actually returned
    answered = agent_status == "answered" and bool(supported)
    if not answered:
        flags.append("no_answer_rule")
    status = "answered" if answered else "no_answer"
    answer = (final.get("answer") or "") if answered else NO_ANSWER_TEXT
    # metadata for staff tooling; it never changes the answer
    needs_review = not answered or "unverified_citation" in flags or "no_submit" in flags

    total_s = round(clock() - start, 3)
    tokens = {k: sum(c["usage"][k] for c in model_calls) for k in ("input", "output", "cache_read", "cache_write")}
    stage = lambda name: round(sum(c["duration_s"] for c in tools.calls if c["name"] == name), 3)
    result = {
        "question": question, "request_id": request_id,
        "status": status, "agent_status": agent_status,
        "assumption": final.get("assumption") if answered else None, "answer": answer,
        "citations": citations if answered else [],
        "conflicts_noted": (final.get("conflicts_noted") or []) if answered else [],
        "flags": flags, "needs_review": needs_review,
        "words": {"displayed": word_count(answer), "rendered": word_count(answer)},
        "answered_by": final_call["served_model"] if final_call else None,
        "provider": final_call["provider"] if final_call else None,
        "model": final_call["served_model"] if final_call else None,
        "fallback_used": any(c["fallback"] for c in model_calls),
        "timing_s": {"total": total_s, "search": stage("search_documents"), "read_page": stage("read_page"),
                     "list_documents": stage("list_documents"),
                     "lookups": round(sum(c["duration_s"] for c in tools.calls if c["name"].startswith("lookup_")), 3),
                     "model_calls": [c["duration_s"] for c in model_calls]},
        "lookups": lookups, "tokens": tokens, "cost_usd": round(sum(c["cost_usd"] for c in model_calls), 6),
        # the completeness pass: None when it didn't apply (no "answered" submit, or turned off)
        "completeness": completeness,
        # every page any tool returned; the eval's retrieval recall uses it
        "pages_seen": sorted(tools.seen),
        "trace_id": None,
    }
    chars = acfg.get("trace_evidence_chars", EVIDENCE_CHARS)
    scfg = cfg.get("search", {})
    trace = {**result, "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "config": {"primary": (lcfg.get("primary") or {}).get("model"),
                        "fallback": (lcfg.get("fallback") or {}).get("model"),
                        "effort": (lcfg.get("primary") or {}).get("effort"),
                        "search": {k: scfg.get(k) for k in ("mode", "rrf_k", "fusion_depth", "return_parents", "rerank")},
                        **{k: acfg.get(k) for k in ("max_tool_calls", "deadline_s", "search_k", "min_lookups",
                                                    "completeness_pass", "completeness_min_remaining_s")}},
             "structured_lookups": structured, "context": dict(context or {}),
             # the model's submitted answer and citations, before the no-answer rule
             "model_answer": final.get("answer"), "model_citations": citations,
             # the submit the completeness pass replaced (None when it kept the first or didn't run)
             "first_submit": first if completeness and completeness.get("changed") else None,
             "model_calls": model_calls, "tool_calls": tools.calls,
             # the text tools returned for each cited page or row, for the offline checks only
             "cited_evidence": {c["locator"]: tools.evidence.get(c["locator"], "")[:chars] for c in citations},
             "cited_evidence_parts": {c["locator"]: [x[:chars] for x in tools.evidence_parts.get(c["locator"], [])]
                                      for c in citations},
             "cost_note": "each call priced at its serving role's rates (llm.<role>.prices_per_mtok)",
             "request_started_utc": started_utc.isoformat(), "citation_check": citation_check}
    if save_trace:
        result["trace_path"] = str(_save(trace))
    # LangSmith; a no-op when tracing is off, and it never raises or blocks
    result["trace_id"] = telemetry.emit(trace, cfg=cfg)
    return result


# ---- v1 helpers other modules still import (eval/judge.py, parsers/figures.py, rag/pipeline.py) ----

def agent_config() -> dict:
    from pharmassist.config import load_config
    return load_config()["agent"]


def make_client():
    """An Anthropic client with the workspace header, as v1 built it (the figure extraction, the
    rag_v1 pipeline and the eval judge still call the Messages API directly)."""
    from dotenv import load_dotenv
    from pharmassist.llm.anthropic_provider import AnthropicProvider
    load_dotenv(PROJECT_ROOT / ".env")
    return AnthropicProvider().client()


def _usage(resp) -> dict:
    from pharmassist.llm.anthropic_provider import usage_of
    u = usage_of(resp)
    return {"input": u.input, "output": u.output, "cache_read": u.cache_read, "cache_write": u.cache_write}


def cost_usd(tokens: dict, prices: dict) -> float:
    from pharmassist.llm.pricing import cost_usd as _cost
    return _cost(tokens, prices)


def _save(trace: dict):
    out = project_path("traces")
    out.mkdir(exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", trace["question"].lower())[:40].strip("-")
    path = out / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{slug}.json"
    path.write_text(json.dumps(trace, indent=2, ensure_ascii=False, default=str) + "\n")
    return path.relative_to(PROJECT_ROOT)
