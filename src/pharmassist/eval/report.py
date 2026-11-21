"""One eval row per question, the run summary, and summary.md."""

from statistics import mean, median

from pharmassist.agent.tools import catalog, locator, parse_locator
from pharmassist.eval import scoring

GRADE_POINTS = {"correct": 1.0, "partial": 0.5, "incorrect": 0.0}
CSV_FIELDS = [
    "id", "type", "program", "answerable", "status", "flags", "error",
    "accuracy", "judge_grades", "judge_reason", "must_include_judge", "must_include_substring", "missing_terms",
    "groundedness", "claims_supported", "claims_partial", "claims_unsupported", "unsupported_claims",
    "failure_class", "failure_reason",
    "retrieval_recall", "retrieval_recall_pages", "recall_at_5", "recall_at_10",
    "gold", "gold_missed", "gold_rows",
    "citation_precision", "citation_recall", "citation_recall_pages", "citations", "citations_flagged",
    "evidence_tools", "abstention_ok", "assumption_ok",
    "verification_outcome", "direct_label", "claim_labels", "needs_review", "omission_causes",
    "omitted_claim_types", "over_abstention", "safe", "useful", "claim_audit", "audit_cost_usd",
    "audit_shown", "audit_shown_unsupported", "audit_shown_partial", "offline_check_flagged", "offline_checks",
    "total_s", "model_s", "search_s", "read_page_s", "index_warm", "lookups", "tools_used",
    "words", "words_in_range", "displayed_words", "displayed_words_in_range", "rejected_atomicity",
    "presentation_warnings", "atomicity_warned_claims", "audit_warned", "agent_cost_usd", "judge_cost_usd", "answer", "trace_path",
]


def _join(locators) -> str:
    return "; ".join(sorted(locators))


def cited_locators(citations: list[dict]) -> set[str]:
    return {c.get("locator") or locator(c["doc_id"], c.get("page"), c.get("row")) for c in citations}


def citable(citations: list[dict]) -> list[str]:
    """Cited sources that exist, for the groundedness judge (unknown docs, pages and rows are left out)."""
    out = []
    for loc in cited_locators(citations):
        doc_id, kind, n = parse_locator(loc)
        entry = catalog().get(doc_id)
        if entry is None:
            continue
        if kind == "p" and entry["file"].lower().endswith(".pdf") and 1 <= n <= entry["pages"]:
            out.append(loc)
        elif kind == "r" and not entry["file"].lower().endswith(".pdf"):
            from pharmassist.tables import va_formulary
            f = va_formulary.load()
            if n in f.rows.index or n in f.notes or n == f.header_row:
                out.append(loc)
    return sorted(out)


def evidence_tools(cited: set[str], tool_calls: list[dict]) -> str:
    """For each cited source, the tools that returned it during the question."""
    parts = []
    for loc in sorted(cited):
        tools = sorted({c["name"] for c in tool_calls if loc in c.get("pages", [])})
        parts.append(f"{loc} <- {', '.join(tools) or 'no tool'}")
    return "; ".join(parts)


def _rejected(result: dict, kinds: tuple[str, ...]) -> str:
    """The submitted claims (by number) rejected for any of these problem kinds."""
    claims = (result.get("verification") or {}).get("claims", [])
    return ", ".join(f"claim {c['index']}" for c in claims if any(p["kind"] in kinds for p in c["problems"]))


def build_row(q: dict, result: dict | None, accuracy: dict | None, grounded: dict | None,
              judge_cost: float, words_range: tuple[int, int], error: str | None = None,
              tool_calls: list[dict] | None = None, ranked: list[str] | None = None,
              rows_ingested: bool = False) -> dict:
    """`ranked`: the pages a direct hybrid search ranks for the question (for Recall@k).
    `rows_ingested`: whether the setup can read spreadsheet rows (the structured lookups)."""
    gold = scoring.gold_locators(q["gold"])
    gold_pages = scoring.pages_only(gold)
    row = {"id": q["id"], "type": q["type"], "program": q["program"], "answerable": q["answerable"],
           "gold": _join(gold), "gold_rows": len(gold - gold_pages), "error": error,
           "judge_cost_usd": round(judge_cost, 6)}
    if ranked is not None:
        row["recall_at_5"] = scoring.recall_at_k(gold_pages, ranked, 5)
        row["recall_at_10"] = scoring.recall_at_k(gold_pages, ranked, 10)
    if result is None:
        return {**row, "accuracy": "error"}

    # traces from before locators stored pages as 'doc:p34', which is already a locator
    seen = set(result["pages_seen"])
    cited = cited_locators(result["citations"])
    ret = scoring.retrieval(gold, seen)
    cites = scoring.citation_scores(gold, cited)
    t = result["timing_s"]
    words = scoring.word_count(result["answer"])
    substring = scoring.must_include_substring(q["must_include"], result["answer"])
    tool_calls = tool_calls or []
    row.update({
        "status": result["status"], "flags": "; ".join(result["flags"]),
        "retrieval_recall": ret["recall"], "gold_missed": _join(ret["missed"]),
        "retrieval_recall_pages": scoring.retrieval(gold_pages, seen)["recall"],
        "citation_precision": cites["precision"], "citation_recall": cites["recall"],
        "citation_recall_pages": scoring.citation_scores(gold_pages, cited)["recall"],
        "citations": _join(cited), "evidence_tools": evidence_tools(cited, tool_calls),
        "citations_flagged": sum(1 for c in result["citations"] if c["flag"]),
        "abstention_ok": scoring.abstention_ok(q["answerable"], result["status"]),
        "assumption_ok": scoring.assumption_ok(q["program"], result["answer"], result["assumption"]),
        "must_include_substring": f"{sum(substring)}/{len(substring)}",
        "total_s": t["total"], "model_s": round(sum(t["model_calls"]), 3), "search_s": t["search"],
        "read_page_s": t["read_page"], "index_warm": result.get("index_warm_at_start"),   # v1 only; v2 has no file index to warm
        "lookups": result["lookups"],
        "tools_used": "; ".join(c["name"] for c in tool_calls),
        "words": words, "words_in_range": words_range[0] <= words <= words_range[1],
        "displayed_words": (result.get("words") or {}).get("displayed"),
        "displayed_words_in_range": (words_range[0] <= result["words"]["displayed"] <= words_range[1])
                                    if result.get("words") else None,
        "rejected_atomicity": _rejected(result, ("multiple_sentences", "compound_assertion", "semicolon")),
        "presentation_warnings": "; ".join((f"claim {w['claim']}: " if w.get("claim") else "") + w["kind"]
                                           for w in (result.get("verification") or {}).get("warnings", [])),
        "atomicity_warned_claims": " | ".join(
            f"claim {c['index']}: {c['text']}" for c in (result.get("verification") or {}).get("claims", [])
            if any(w["kind"] == "atomicity_warning" for w in c.get("warnings", [])) and c["passed"]
            and result["verification"].get("outcome") == "answered"),
        "agent_cost_usd": result["cost_usd"], "answer": result["answer"],
        # older traces predate answer verification
        "verification_outcome": (result.get("verification") or {}).get("outcome"),
        "direct_label": (result.get("verification") or {}).get("direct_label"),
        "claim_labels": "; ".join(f"{k} {v}" for k, v in ((result.get("verification") or {}).get("labels") or {}).items() if v),
        "needs_review": result.get("needs_review"),
        "omission_causes": " | ".join(f"claim {o['claim']} ({o['type']}): {', '.join(o['causes'])}"
                                      for o in (result.get("verification") or {}).get("omissions", [])),
        "omitted_claim_types": "; ".join(result.get("omitted_claim_types") or []),
        "trace_path": result.get("trace_path"),
    })
    if accuracy is None:
        row["accuracy"] = "judge_error"
    else:
        present = [m for m in accuracy["must_include"] if m["present"]]
        row.update({"accuracy": accuracy["grade"], "judge_reason": accuracy["reason"],
                    "judge_grades": ", ".join(accuracy.get("grades", [accuracy["grade"]])),
                    "must_include_judge": f"{len(present)}/{len(accuracy['must_include'])}",
                    "missing_terms": "; ".join(m["term"] for m in accuracy["must_include"]
                                               if not m["present"])})
    # abstaining is correct only where the gold says the documents can't answer
    row["over_abstention"] = scoring.over_abstained(q["answerable"], result["status"])
    if row["over_abstention"]:
        row["accuracy"] = "incorrect"
    elif not q["answerable"] and result["status"] in scoring.ABSTAINED:
        row["accuracy"] = "correct"
    # useful: an answerable question whose direct claim was shown (whatever its check label)
    row["useful"] = scoring.useful(q["answerable"], result["status"])
    row["failure_class"], row["failure_reason"] = scoring.classify(
        row["accuracy"], gold, seen, cited, rows_ingested)
    if result["status"] in scoring.ABSTAINED:
        row["groundedness"] = "n/a"  # nothing to ground
    elif not cited:
        row["groundedness"] = "uncited"
    elif grounded is None:
        # no judge pass (run_eval --no-judge / --deepeval: DeepEval scores the run) vs a judge that failed
        row["groundedness"] = "unjudged" if (accuracy or {}).get("grade") == "unjudged" else "judge_error"
    else:
        claims = grounded["claims"]
        n = {v: sum(c["verdict"] == v for c in claims) for v in ("supported", "partial", "unsupported")}
        row.update({"groundedness": scoring._share(n["supported"], len(claims)) if claims else "no claims",
                    "claims_supported": n["supported"], "claims_partial": n["partial"],
                    "claims_unsupported": n["unsupported"],
                    "unsupported_claims": " | ".join(f"{c['claim']} ({c['verdict']}: {c['note']})"
                                                     for c in claims if c["verdict"] != "supported")})
    # safe: nothing the groundedness judge found unsupported was shown (an abstention shows nothing)
    if result["status"] in scoring.ABSTAINED:
        row["safe"] = True
    elif grounded is not None and cited:
        row["safe"] = row.get("claims_unsupported", 0) == 0
    return row


def _num(v, default):
    """Numeric value for ranking; n/a counts as perfect so it never drags a question down."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v
    return 0.0 if v in ("uncited", "judge_error", "no claims") else default


def rank_key(row: dict) -> tuple:
    """Lowest first: accuracy, then groundedness, citation recall, retrieval recall."""
    return (GRADE_POINTS.get(row.get("accuracy"), -1.0), _num(row.get("groundedness"), 1.0),
            _num(row.get("citation_recall"), 1.0), _num(row.get("retrieval_recall"), 1.0))


def lowest(rows: list[dict], n: int = 5) -> list[dict]:
    return sorted(rows, key=rank_key)[:n]


def _avg(values) -> float | None:
    values = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    return round(mean(values), 3) if values else None


def _count(rows, key, value=True) -> str:
    applicable = [r for r in rows if r.get(key) is not None]
    return f"{sum(r[key] == value for r in applicable)}/{len(applicable)}"


def _ratio_sum(rows, key) -> str:
    parts = [r[key].split("/") for r in rows if r.get(key)]
    return f"{sum(int(a) for a, _ in parts)}/{sum(int(b) for _, b in parts)}"


def summarize(rows: list[dict]) -> dict:
    done = [r for r in rows if r.get("status")]
    grades = [r["accuracy"] for r in rows]
    gold_total = sum(len(r["gold"].split("; ")) for r in done if r["gold"])
    gold_missed = sum(len(r["gold_missed"].split("; ")) for r in done if r.get("gold_missed"))
    failures = [r.get("failure_class") for r in rows if r.get("failure_class")]
    agent_cost = sum(r.get("agent_cost_usd") or 0 for r in rows)
    judge_cost = sum(r["judge_cost_usd"] for r in rows)
    return {
        "questions": len(rows), "errors": sum(1 for r in rows if r.get("error")),
        "accuracy": {g: grades.count(g) for g in ("correct", "partial", "incorrect", "unjudged", "judge_error", "error")},
        "accuracy_score": _avg(GRADE_POINTS.get(g) for g in grades),
        "judge_unanimous": f"{sum(len(set(r['judge_grades'].split(', '))) == 1 for r in done if r.get('judge_grades'))}"
                           f"/{sum(1 for r in done if r.get('judge_grades'))}",
        "must_include_judge": _ratio_sum(done, "must_include_judge"),
        "must_include_substring": _ratio_sum(done, "must_include_substring"),
        "retrieval_recall_mean": _avg(r["retrieval_recall"] for r in done),
        "retrieval_recall_pages_mean": _avg(r["retrieval_recall_pages"] for r in done),
        "recall_at_5_mean": _avg(r.get("recall_at_5") for r in rows),
        "recall_at_10_mean": _avg(r.get("recall_at_10") for r in rows),
        "gold_found": f"{gold_total - gold_missed}/{gold_total}",
        "gold_rows": sum(r["gold_rows"] for r in rows),
        "citation_precision_mean": _avg(r["citation_precision"] for r in done),
        "citation_recall_mean": _avg(r["citation_recall"] for r in done),
        "citation_recall_pages_mean": _avg(r["citation_recall_pages"] for r in done),
        "failures": {c: failures.count(c) for c in (scoring.NOT_INGESTED, scoring.NOT_RETRIEVED,
                                                    scoring.ANSWERED_WRONG, scoring.CITED_WRONG,
                                                    scoring.AMBIGUOUS)},
        "citations_flagged": sum(r["citations_flagged"] for r in done),
        "groundedness_mean": _avg(r.get("groundedness") for r in done),
        "uncited_answers": sum(r.get("groundedness") == "uncited" for r in done),
        "abstention_ok": _count(done, "abstention_ok"),
        "over_abstention": sum(bool(r.get("over_abstention")) for r in done),
        "safe": _count(done, "safe"),
        "useful": f"{sum(bool(r.get('useful')) for r in done if r['answerable'])}"
                  f"/{sum(1 for r in done if r['answerable'])}",
        "assumption_ok": _count(done, "assumption_ok"),
        "latency_all": scoring.percentiles([r["total_s"] for r in done]),
        "latency_cold": scoring.percentiles([r["total_s"] for r in done if not r["index_warm"]]),
        "latency_warm": scoring.percentiles([r["total_s"] for r in done if r["index_warm"]]),
        "over_30s": sum(r["total_s"] > 30 for r in done),
        "words_mean": _avg(r["words"] for r in done),
        "words_median": median([r["words"] for r in done]) if done else None,
        "words_max": max((r["words"] for r in done), default=None),
        "words_in_range": _count(done, "words_in_range"),
        "displayed_words_mean": _avg(r.get("displayed_words") for r in done),
        "displayed_words_in_range": _count([r for r in done if r.get("displayed_words") is not None],
                                           "displayed_words_in_range"),
        "needs_review": sum(bool(r.get("needs_review")) for r in done if r.get("needs_review") is not None),
        "presentation_warned": sum(bool(r.get("presentation_warnings")) for r in done),
        "answered": sum(r.get("verification_outcome") == "answered" and not r.get("needs_review") for r in done),
        "answered_omitting": sum(r.get("verification_outcome") == "answered" and bool(r.get("needs_review")) for r in done),
        "abstained": sum(r.get("verification_outcome") == "abstained" for r in done),
        "direct_labels": {lab: sum(r.get("direct_label") == lab for r in done)
                          for lab in ("verified", "values_checked", "unchecked")},
        "audit_cost": round(sum(r.get("audit_cost_usd") or 0 for r in rows), 4),
        "audit_shown": sum(r.get("audit_shown") or 0 for r in rows),
        "audit_shown_unsupported": sum(r.get("audit_shown_unsupported") or 0 for r in rows),
        "audit_shown_partial": sum(r.get("audit_shown_partial") or 0 for r in rows),
        "gated": any(r.get("verification_outcome") for r in done),
        "offline_flagged_answers": sum(bool(r.get("offline_check_flagged")) for r in rows),
        "offline_flagged_sentences": sum(r.get("offline_check_flagged") or 0 for r in rows),
        "flags": {f: sum(f in (r.get("flags") or "").split("; ") for r in done)
                  for f in ("nudged_to_submit", "no_submit", "budget_spent:tool_cap",
                            "budget_spent:deadline", "unverified_citation", "no_answer")},
        "cost": {"agent": round(agent_cost, 4), "judge": round(judge_cost, 4),
                 "total": round(agent_cost + judge_cost, 4),
                 "agent_per_question": round(agent_cost / max(len(done), 1), 4)},
    }


def _cell(v) -> str:
    return "–" if v is None or v == "" else str(v).replace("|", "\\|").replace("\n", " ")


def _fmt(v, digits: int) -> str:
    return f"{v:.{digits}f}" if isinstance(v, (int, float)) else _cell(v)


def _lat(p: dict) -> str:
    return f"p50 {p['p50']} s, p95 {p['p95']} s (n={p['n']})" if p["n"] else "none"


def markdown(meta: dict, s: dict, rows: list[dict], low: list[dict], spot: list[dict]) -> str:
    acc = s["accuracy"]
    lines = [
        f"# Eval: {meta['setup']}, {meta['run']}", "",
        f"- Agent: `{meta['agent_model']}` (effort {meta['agent_effort']}), index setup `{meta['setup']}`, "
        f"max {meta['max_tool_calls']} lookups, {meta['deadline_s']} s deadline",
        f"- Judge: `{meta['judge_model']}` (effort {meta['judge_effort']}"
        + (f", {meta['judge_passes']} pass{'es' if meta['judge_passes'] != 1 else ''}" if meta.get('judge_passes') else "") + ")",
        f"- Golden set: `{meta['golden']}`, {s['questions']} questions, each run once",
        f"- Code: commit `{meta['commit']}`{' (with uncommitted changes)' if meta['dirty'] else ''}",
        *([f"- System under test (agent) commit: `{meta['system_commit']}`; evaluation harness: commit "
           f"`{meta['commit']}`"] if meta.get("system_commit") else []),
        f"- Run date: {meta['run']}; per-question results in `results.csv`",
        *([f"- Re-judged from `{meta['rejudged_from']}` with the current judges; the agent wasn't rerun"]
          if meta.get("rejudged_from") else []),
        "",
        "## Results", "",
        "| Metric | Result |", "|---|---|",
        f"| Accuracy (judge) | {acc['correct']} correct, {acc['partial']} partial, {acc['incorrect']} incorrect"
        + (f", {acc['judge_error'] + acc['error']} errors" if acc['judge_error'] + acc['error'] else "")
        + f" (score {s['accuracy_score']}, partial = 0.5) |",
        f"| Judge passes unanimous on the grade | {s['judge_unanimous']} |",
        f"| must_include terms present (judge, paraphrase counts) | {s['must_include_judge']} |",
        f"| must_include terms present (literal substring) | {s['must_include_substring']} |",
        f"| Recall@5 / @10 (direct hybrid search on the question, PDF gold) | "
        f"{s['recall_at_5_mean']} / {s['recall_at_10_mean']} |",
        f"| Retrieval recall: all gold / PDF pages only (mean, any tool) | "
        f"{s['retrieval_recall_mean']} / {s['retrieval_recall_pages_mean']} |",
        f"| Gold sources returned by any tool (all questions) | {s['gold_found']} |",
        f"| Citation precision / recall: all gold (mean) | {s['citation_precision_mean']} / {s['citation_recall_mean']} |",
        f"| Citation recall: PDF pages only (mean) | {s['citation_recall_pages_mean']} |",
        f"| Citations failing the in-code check | {s['citations_flagged']} |",
        f"| Groundedness (supported claims / claims, mean) | {s['groundedness_mean']} |",
        f"| Answered without citations | {s['uncited_answers']} |",
        f"| **Safe**: no unsupported content shown (judge found 0 unsupported claims, or abstained) | {s['safe']} |",
        f"| **Useful**: answerable questions that received a non-abstaining answer | {s['useful']} |",
        f"| Over-abstention (abstained or unverified on an answerable question; graded incorrect) | {s['over_abstention']} |",
        f"| Abstention correct | {s['abstention_ok']} |",
        f"| Opens with the assumption (unspecified program) | {s['assumption_ok']} |",
        *([f"| Startup warmup before timing (not in any latency) | {meta['startup']['total_s']} s "
           f"({', '.join(f'{k} {v} s' for k, v in meta['startup']['steps_s'].items())})"
           + (f", error: {_cell(meta['startup']['error'])}" if meta['startup'].get('error') else "") + " |"]
          if meta.get("startup") else []),
        f"| Latency, all | {_lat(s['latency_all'])} |",
        f"| Latency, cold (index not yet loaded) | {_lat(s['latency_cold'])} |",
        f"| Latency, warm | {_lat(s['latency_warm'])} |",
        f"| Over 30 s | {s['over_30s']} |",
        f"| Rendered length incl. citations, words (mean / median / max) | {s['words_mean']} / {s['words_median']} / {s['words_max']} |",
        f"| Displayed content, words excl. labels and citations (mean; in 60-120) | {s['displayed_words_mean']}; "
        f"{s['displayed_words_in_range']} |",
        # the claim gate's outcome rows, only for runs of the gated agent (5ea6601)
        *([f"| Outcome: answered / answered with claims omitted / abstained (needs review = the last two) | "
           f"{s['answered']} / {s['answered_omitting']} / {s['abstained']} |",
           f"| Direct claim check label: verified / values_checked / unchecked | "
           f"{s['direct_labels']['verified']} / {s['direct_labels']['values_checked']} / {s['direct_labels']['unchecked']} |"]
          if s["gated"] else [f"| Needs review (not answered, uncited or a flagged citation) | {s['needs_review']} |"]),
        *([f"| Offline deterministic checks: answers / sentences with an evidence problem | "
           f"{s['offline_flagged_answers']} / {s['offline_flagged_sentences']} |"] if meta.get("offline_checks") else []),
        *([f"| Offline Sonnet audit of shown sentences/claims: unsupported / partially supported / audited | "
           f"{s['audit_shown_unsupported']} / {s['audit_shown_partial']} / {s['audit_shown']} "
           f"(audit cost ${s['audit_cost']:.2f}) |"] if meta.get("claim_audit") else []),
        f"| Flags | " + (", ".join(f"{k} {v}" for k, v in s["flags"].items() if v) or "none") + " |",
        f"| Failures by class | " + (", ".join(f"{k} {v}" for k, v in s["failures"].items() if v) or "none") + " |",
        f"| Cost | agent ${s['cost']['agent']:.2f} (${s['cost']['agent_per_question']:.3f}/question), "
        f"judge ${s['cost']['judge']:.2f}, total ${s['cost']['total']:.2f} |",
        "", "## Per question", "",
        "| ID | Accuracy | Grounded | R@10 | Retrieval | Cite P / R | Abst. | Assum. | Time s | Words | Cost $ | Failure class |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r['id']} | {_cell(r.get('accuracy'))} | {_cell(r.get('groundedness'))} | "
                     f"{_cell(r.get('recall_at_10'))} | {_cell(r.get('retrieval_recall'))} | {_cell(r.get('citation_precision'))} / "
                     f"{_cell(r.get('citation_recall'))} | {_cell(r.get('abstention_ok'))} | "
                     f"{_cell(r.get('assumption_ok'))} | {_fmt(r.get('total_s'), 1)} | {_cell(r.get('words'))} | "
                     f"{_fmt((r.get('agent_cost_usd') or 0) + r['judge_cost_usd'], 3)} | {_cell(r.get('failure_class'))} |")
    lines += ["", "## Lowest-scoring questions", "",
              "Ranked by accuracy, then groundedness, citation recall and retrieval recall.", ""]
    lines += spot_lines(low)
    lines += ["", "## Random sample the judge marked correct",
              "", f"To check the judge isn't too lenient (sample seed {meta['seed']}).", ""]
    lines += spot_lines(spot) if spot else ["No questions were marked correct."]
    lines += [
        "", "## Caveats", "",
        f"- **The judge is also a Claude model**, so it may share the agent's blind spots. "
        "Human spot checks of its grades (the two lists above) are the safeguard.",
        "- **Each question ran once.** The agent isn't deterministic, so a one-question difference "
        "between setups may be noise.",
        f"- **VA formulary gold** ({s['gold_rows']} spreadsheet rows, from cells such as A1697:G1697) "
        "counts in the all-gold scores; a setup without the formulary lookup can't reach it, so "
        "compare setups on the PDF-pages-only scores too. Recall@k covers PDF pages only.",
        "- **Failure classes are assigned by rule** (earliest stage that explains the miss), "
        "with ambiguous cases set by hand in `evals/failure_overrides.yaml`.",
        "- **Citation precision is a lower bound**: a correct citation to a page outside the gold set "
        "counts against it. Read it together with groundedness.",
        f"- **Cold latency has n={s['latency_cold']['n']}**: in one process only the first question "
        "loads the index, so the cold p95 is not a real percentile.",
    ]
    return "\n".join(lines) + "\n"


def spot_lines(rows: list[dict]) -> list[str]:
    out = []
    for r in rows:
        out.append(f"- **{r['id']}** ({r['type']}): {r.get('accuracy')}"
                   + (f" [{r['failure_class']}]" if r.get("failure_class") else "") + ", groundedness "
                   f"{_cell(r.get('groundedness'))}, citation recall {_cell(r.get('citation_recall'))}, "
                   f"retrieval {_cell(r.get('retrieval_recall'))}")
        out.append(f"  - Judge: {_cell(r.get('judge_reason') or r.get('error'))}")
        if r.get("missing_terms"):
            out.append(f"  - Missing terms: {r['missing_terms']}")
        if r.get("unsupported_claims"):
            out.append(f"  - Not fully supported: {_cell(r['unsupported_claims'])}")
    return out
