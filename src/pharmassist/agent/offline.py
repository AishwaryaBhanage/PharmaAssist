"""Offline safety checks on answers already given: for evaluation and diagnostics only.

ask() never calls this module, and nothing here can change an answer: it reads a saved trace (the
answer, its citations and the evidence text the tools returned for each cited page or row) and
returns findings to store beside it.

- Deterministic checks (free): the answer is split into sentences, and each is checked by
  agent/verify.py's claim checks (values, phone purposes, drug status, legal words, structure)
  against the evidence the answer cites. A free-form answer doesn't say which citation backs which
  sentence, so every sentence is checked against all of the answer's citations: a lenient check.
- Claim audit (one paid model call): the same sentences judged by the Sonnet claim audit.

Both run only when asked: run_eval.py --checks / --audit, or audit_trace() from a diagnostics session.
"""

import re
from datetime import date, datetime

from pharmassist.agent import verify as V

BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)]|#+)\s+")
TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{3,}")


def answer_claims(answer: str, citations: list[dict]) -> list[dict]:
    """The answer's sentences as claims (table rows as one claim each), every one citing all of the
    answer's citations. The first is marked as the direct answer."""
    cites = [{k: c.get(k) for k in ("doc_id", "page", "row") if k in c} for c in citations]
    lines = (answer or "").split("\n")
    texts = []
    for i, line in enumerate(lines):
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if not line.strip() or TABLE_RULE.match(line) or TABLE_RULE.match(nxt):  # rule or table header
            continue
        if line.strip().startswith("|"):
            texts.append(" | ".join(c.strip() for c in line.strip().strip("|").split("|")))
            continue
        line = BULLET.sub("", line).replace("**", "").strip()
        texts += [s.strip() for s in re.split(r"(?<=[.!?])\s+", line) if s.strip()]
    return [{"text": t, "type": "other", "direct_answer": i == 0, "step": None, "citations": cites}
            for i, t in enumerate(texts)]


def deterministic_checks(trace: dict, today: date | None = None) -> dict:
    """verify.py's claim checks on each sentence of the trace's answer. No model call."""
    claims = answer_claims(trace.get("answer", ""), trace.get("citations") or [])
    today = today or _run_day(trace)
    ctx = V.Context(trace.get("cited_evidence") or {}, trace.get("cited_evidence_parts") or {},
                    trace.get("question", ""), today)
    out = []
    for i, c in enumerate(claims, 1):
        checked = V.check_claim(c, ctx)
        problems = [p.record() for p in checked["problems"]]
        out.append({"index": i, "text": c["text"], "label": checked["label"], "problems": problems,
                    # a value, status or wording the cited evidence doesn't support (not structure)
                    "evidence_problem": any(p["cause"] in ("evidence_failure", "citation_only") for p in problems)})
    return {"claims": out, "sentences": len(out), "evidence_flagged": sum(c["evidence_problem"] for c in out)}


def audit(client, acfg: dict, trace: dict) -> dict:
    """The Sonnet claim audit on the answer's sentences: one batched model call."""
    claims = answer_claims(trace.get("answer", ""), trace.get("citations") or [])
    if not claims:
        return {"verdicts": [], "model": None, "usage": {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}}
    out = V.audit_claims(client, acfg, claims, trace.get("cited_evidence") or {}, trace.get("question", ""))
    for v in out["verdicts"]:
        if 1 <= v["claim"] <= len(claims):
            v["text"] = claims[v["claim"] - 1]["text"]
    return out


def audit_trace(trace: dict, client=None, acfg: dict | None = None) -> dict:
    """Both checks on one saved trace: the deterministic checks always, the claim audit when a client
    and audit config are given. Errors are returned, never raised; the trace's answer is not touched."""
    out = {"checks": deterministic_checks(trace)}
    if client is not None and acfg:
        try:
            out["claim_audit"] = audit(client, acfg, trace)
        except Exception as e:
            out["claim_audit"] = {"error": f"{type(e).__name__}: {e}"}
    return out


def _run_day(trace: dict) -> date:
    started = trace.get("started_at")
    return datetime.fromisoformat(started).astimezone().date() if started else date.today()
