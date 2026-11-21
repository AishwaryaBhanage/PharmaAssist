"""Run the golden set through the v2 agent (PostgreSQL store, OpenAI-first router), score it, write the report.

Run: python scripts/run_eval.py [--ids Q11,Q20] [--audit] [--judge-passes 1] [--golden evals/visual.jsonl] [--tag visual]
     python scripts/run_eval.py --rejudge reports/evals/<run folder>
Needs DATABASE_URL (the store the app serves from) and the provider keys in .env. Writes
reports/evals/<label>_<date>_<HHMM>/results.csv and summary.md. Questions run one at a time in one
process, so latency isn't distorted by contention. Before the first question is timed, the store
connection, the drug tables and the search path are warmed (no paid call); that startup time is
reported on its own and isn't in any question's latency. --checks runs the offline deterministic
checks after each answer and --audit also the Sonnet claim audit; neither can change an answer.
--rejudge doesn't rerun the agent: it rebuilds each row from the run's traces with the current
judges and scoring, and writes <run folder>_rejudged_<date>_<HHMM>/.
"""

import argparse
import csv
import hashlib
import json
import sys
import os
import random
import subprocess
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

from pharmassist.agent import offline, telemetry
from pharmassist.agent.loop import ask, cost_usd, make_client
from pharmassist.agent.prompt import system_prompt
from pharmassist.agent.tools import ToolBox, _table, locator
from pharmassist.config import PROJECT_ROOT, load_config, project_path
from pharmassist.eval import report, scoring
from pharmassist.eval.judge import judge_accuracy, judge_groundedness

OVERRIDES = PROJECT_ROOT / "evals" / "failure_overrides.yaml"


@dataclass
class Stack:
    """What one evaluated system is made of: the config, the store it answers from and its router."""
    cfg: dict
    store: object
    router: object
    label: str = "v2"

    def embed(self, text: str) -> list[float]:
        """One question's vector, the shape hybrid search and the tools take (Router.embed takes a list)."""
        return list(self.router.embed([text])[0])

    @property
    def structured(self) -> bool:
        return bool(self.cfg.get("agent", {}).get("structured_lookups", True))


def build_stack(cfg: dict, label: str, dsn: str | None = None) -> Stack:
    from pharmassist.llm.router import router_from_config
    from pharmassist.store import open_store
    dsn = dsn or os.environ.get(cfg.get("database", {}).get("url_env", "DATABASE_URL"))
    if not dsn:
        raise SystemExit("set DATABASE_URL (or --dsn) to the PostgreSQL store to evaluate")
    return Stack(cfg, open_store(dsn), router_from_config(cfg), label)


def warm_up(stack: Stack) -> dict:
    """The same startup the app does before it answers: store connection, drug tables, one keyword
    search (no embedding, so no paid call). Reported separately from the questions' latency."""
    from pharmassist.search.hybrid import search as hybrid_search
    steps, t_all, error = {}, time.perf_counter(), None
    try:
        t = time.perf_counter()
        stack.store.documents.generation()
        steps["store"] = round(time.perf_counter() - t, 3)
        if stack.structured:
            t = time.perf_counter()
            _table(stack.store, "va_formulary")
            _table(stack.store, "ny_pdl")
            steps["tables"] = round(time.perf_counter() - t, 3)
        t = time.perf_counter()
        hybrid_search("warm up", k=1, store=stack.store, embed=None, mode="keyword", cfg=stack.cfg.get("search"))
        steps["search"] = round(time.perf_counter() - t, 3)
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
    return {"steps_s": steps, "total_s": round(time.perf_counter() - t_all, 3), "error": error, "index_warm": error is None}


def _git(*args) -> str:
    return subprocess.run(["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True).stdout.strip()


def ranked_pages(question: str, stack: Stack) -> list[list[str]]:
    """The top 10 units a direct hybrid search returns for the question, each as the pages it
    covers, for Recall@5/@10 (no agent involved)."""
    from pharmassist.search.hybrid import search as hybrid_search
    hits = hybrid_search(question, k=10, store=stack.store, embed=stack.embed, cfg=stack.cfg.get("search"))
    return [[locator(h["doc_id"], p) for p in (h.get("pages") or [h["page"]])] for h in hits]


def overrides() -> dict:
    return yaml.safe_load(OVERRIDES.read_text()) or {} if OVERRIDES.exists() else {}


def score(q: dict, result: dict, tool_calls: list[dict], client, ecfg: dict, stack: Stack,
          today: date, notes: dict) -> dict:
    """Judge and score one answered question. Judge failures go in the row, not up the stack."""
    accuracy = grounded = None
    judge_cost, errors, passes = 0.0, [], ecfg.get("judge_passes", 1)
    grades, groundings = [], []
    for _ in range(passes):
        try:
            a, cost = judge_accuracy(client, ecfg, q, result, today.isoformat())
            grades.append(a)
            judge_cost += cost
        except Exception as e:
            errors.append(f"accuracy judge: {e!r}")
    if passes == 0:   # --no-judge / --deepeval: answers and traces only; DeepEval scores the run afterwards
        accuracy = {"grade": "unjudged", "reason": "scored by DeepEval (reports/deepeval)", "must_include": [], "grades": []}
    if grades:
        # majority grade; its first reason; each must_include term by majority
        grade = scoring.majority_grade([g["grade"] for g in grades])
        terms = [m["term"] for m in grades[0]["must_include"]]
        present = {t: sum(any(m["term"] == t and m["present"] for m in g["must_include"]) for g in grades)
                   for t in terms}
        accuracy = {"grade": grade,
                    "reason": next((g["reason"] for g in grades if g["grade"] == grade), grades[0]["reason"]),
                    "must_include": [{"term": t, "present": present[t] > len(grades) / 2} for t in terms],
                    "grades": [g["grade"] for g in grades]}
    sources = report.citable(result["citations"])
    if sources and result["status"] == "answered":
        for _ in range(passes):
            try:
                g, cost = judge_groundedness(client, ecfg, result, sources, today.isoformat())
                groundings.append(g)
                judge_cost += cost
            except Exception as e:
                errors.append(f"groundedness judge: {e!r}")
        if groundings:
            # the median pass by supported share
            share = lambda g: (sum(c["verdict"] == "supported" for c in g["claims"]) / len(g["claims"])
                               if g["claims"] else 1.0)
            grounded = sorted(groundings, key=share)[len(groundings) // 2]
    row = report.build_row(q, result, accuracy, grounded, judge_cost, tuple(ecfg["answer_words"]),
                           error="; ".join(errors) or None, tool_calls=tool_calls,
                           ranked=ranked_pages(q["question"], stack), rows_ingested=stack.structured)
    note = notes.get(q["id"])
    if note and row.get("failure_class"):
        row["failure_class"], row["failure_reason"] = scoring.AMBIGUOUS, note["reason"]
    return row


def run_agent(questions, client, stack: Stack, ecfg, today, notes):
    for q in questions:
        try:
            tools = ToolBox(stack.store, None, stack.embed, stack.cfg, question=q["question"])
            result = ask(q["question"], router=stack.router, tools=tools, cfg=stack.cfg, today=today, save_trace=True)
        except Exception as e:  # one bad question shouldn't end the run
            yield report.build_row(q, None, None, None, 0.0, tuple(ecfg["answer_words"]),
                                   error=f"ask: {e!r}", ranked=ranked_pages(q["question"], stack))
            continue
        trace = json.loads((PROJECT_ROOT / result["trace_path"]).read_text())
        audit = run_audit(client, ecfg, q, result, trace)
        row = score(q, result, trace["tool_calls"], client, ecfg, stack, today, notes)
        if audit is not None:
            row.update(audit)
        yield row


def run_audit(client, ecfg: dict, q: dict, result: dict, trace: dict):
    """The optional offline checks on an answer already given (agent/offline.py): the deterministic
    checks (eval.offline_checks.enabled, --checks) and the Sonnet claim audit (eval.claim_audit.enabled,
    --audit; it runs the deterministic checks too). Stored in the trace and the row; they never change
    the answer. None when both are off."""
    acfg = ecfg.get("claim_audit") or {}
    if not acfg.get("enabled") and not (ecfg.get("offline_checks") or {}).get("enabled"):
        return None
    out = offline.audit_trace(trace, client if acfg.get("enabled") else None, acfg if acfg.get("enabled") else None)
    trace["offline_checks"] = out["checks"]
    checks = out["checks"]
    row = {"offline_check_flagged": checks["evidence_flagged"],
           "offline_checks": " | ".join(f"sentence {c['index']}: " + ", ".join(f"{p['cause']} ({p['detail']})"
                                                                              for p in c["problems"])
                                        for c in checks["claims"] if c["evidence_problem"])}
    if "claim_audit" in out:
        audit = trace["claim_audit"] = out["claim_audit"]
        if "error" in audit:
            row.update({"claim_audit": f"audit error: {audit['error']}", "audit_cost_usd": 0.0})
        else:
            # every sentence of an answer is shown; an abstention shows none
            shown = result["status"] not in scoring.NON_ANSWERS
            verdicts = [x["verdict"] for x in audit["verdicts"]] if shown else []
            row.update({"claim_audit": "; ".join(f"sentence {x['claim']}: {x['verdict']}" for x in audit["verdicts"]),
                        "audit_cost_usd": cost_usd(audit["usage"], acfg["prices_per_mtok"]),
                        "audit_shown": len(verdicts), "audit_shown_unsupported": verdicts.count("unsupported"),
                        "audit_shown_partial": verdicts.count("partially_supported")})
    (PROJECT_ROOT / result["trace_path"]).write_text(json.dumps(trace, indent=2, ensure_ascii=False) + "\n")
    return row


def rejudge(folder: Path, questions, client, ecfg, stack: Stack, notes):
    """Rows rebuilt from an earlier run's traces. Today's date is the run's own date, since answers
    about effective dates were written relative to it."""
    by_id = {q["id"]: q for q in questions}
    for old in csv.DictReader((folder / "results.csv").open()):
        q = by_id[old["id"]]
        if not old.get("trace_path"):
            yield report.build_row(q, None, None, None, 0.0, tuple(ecfg["answer_words"]),
                                   error=old.get("error") or "no trace")
            continue
        trace = json.loads((PROJECT_ROOT / old["trace_path"]).read_text())
        result = {**trace, "trace_path": old["trace_path"]}
        run_day = datetime.fromisoformat(trace["started_at"]).astimezone().date()  # local date, as the run saw it
        yield score(q, result, trace["tool_calls"], client, ecfg, stack, run_day, notes)


def main():
    load_dotenv(PROJECT_ROOT / ".env")
    cfg = load_config()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--label", default="v2", help="name for the run folder and the report (default: v2)")
    parser.add_argument("--dsn", help="PostgreSQL DSN of the store to evaluate (default: DATABASE_URL)")
    parser.add_argument("--ids", help="comma-separated question ids, e.g. Q11,Q20 (default: all)")
    parser.add_argument("--rejudge", type=Path, help="an earlier run folder to re-judge from its traces")
    parser.add_argument("--checks", action="store_true",
                        help="run the offline deterministic checks after each answer (free)")
    parser.add_argument("--audit", action="store_true",
                        help="run the offline Sonnet claim audit (and the deterministic checks) after each answer")
    parser.add_argument("--judge-passes", type=int, help="judge passes per question (default: eval.judge_passes)")
    parser.add_argument("--no-judge", action="store_true",
                        help="run the agent and write answers, traces and retrieval metrics only (no Opus judge)")
    parser.add_argument("--deepeval", action="store_true",
                        help="score the finished run with scripts/deepeval_score.py (implies --no-judge unless --judge-passes is given)")
    parser.add_argument("--golden", help="a different question set, e.g. evals/visual.jsonl (default: eval.golden)")
    parser.add_argument("--tag", help="added to the run folder name, e.g. visual")
    args = parser.parse_args()

    ecfg = cfg["eval"]
    if args.audit:
        ecfg["claim_audit"] = {**ecfg["claim_audit"], "enabled": True}
    if args.checks or args.audit:
        ecfg["offline_checks"] = {**(ecfg.get("offline_checks") or {}), "enabled": True}
    if args.judge_passes:
        ecfg["judge_passes"] = args.judge_passes
    elif args.no_judge or args.deepeval:
        ecfg["judge_passes"] = 0
    if args.golden:
        ecfg["golden"] = args.golden
    questions = [json.loads(line) for line in (PROJECT_ROOT / ecfg["golden"]).open()]
    if args.ids:
        wanted = args.ids.split(",")
        questions = [q for q in questions if q["id"] in wanted]
    notes, started, client = overrides(), datetime.now(), make_client()
    stack = build_stack(cfg, args.label, args.dsn)
    startup = None

    if args.rejudge:
        source = (args.rejudge if args.rejudge.is_absolute() else Path.cwd() / args.rejudge).resolve()
        first = json.loads((PROJECT_ROOT / next(csv.DictReader((source / "results.csv").open()))["trace_path"]).read_text())
        out = source.parent / f"{source.name}_rejudged_{started:%Y-%m-%d_%H%M}"
        rows_iter = rejudge(source, questions, client, ecfg, stack, notes)
    else:
        tag = f"_{args.tag}" if args.tag else ""
        out = project_path("reports") / "evals" / f"{args.label}{tag}_{started:%Y-%m-%d_%H%M}"
        # the same kind of startup warmup as the FastAPI app, before any question is timed
        startup = warm_up(stack)
        print(f"Startup warmup {startup['total_s']} s {startup['steps_s']}"
              + (f"  ERROR {startup['error']}" if startup["error"] else ""))
        rows_iter = run_agent(questions, client, stack, ecfg, date.today(), notes)
    out.mkdir(parents=True, exist_ok=False)  # a same-minute rerun fails rather than overwriting

    rows = []
    for i, row in enumerate(rows_iter, 1):
        rows.append(row)
        print(f"[{i}/{len(questions)}] {row['id']}  {row.get('accuracy')}  grounded {row.get('groundedness')}  "
              f"R@10 {row.get('recall_at_10')}  {row.get('total_s')} s  "
              f"${(row.get('agent_cost_usd') or 0) + row['judge_cost_usd']:.3f}"
              + (f"  [{row['failure_class']}]" if row.get("failure_class") else "")
              + (f"  ERROR {row['error']}" if row.get("error") else ""))

    seed = random.randrange(10_000)
    correct = [r for r in rows if r.get("accuracy") == "correct"]
    spot = random.Random(seed).sample(correct, min(3, len(correct)))
    low = report.lowest(rows)
    summary = report.summarize(rows)
    llm, acfg = cfg["llm"], cfg.get("agent", {})
    meta = {"setup": args.label, "run": f"{started:%Y-%m-%d %H:%M}",
            "agent_model": f"{llm['primary']['model']} (fallback {llm['fallback']['model']})",
            "agent_effort": llm["primary"].get("effort"), "max_tool_calls": acfg.get("max_tool_calls"),
            "deadline_s": acfg.get("deadline_s"), "judge_model": ecfg["judge_model"],
            "judge_effort": ecfg["judge_effort"], "judge_passes": ecfg.get("judge_passes", 1), "golden": ecfg["golden"],
            # untracked files (report folders) don't count as changes to the code under test
            "commit": _git("rev-parse", "--short", "HEAD"),
            "dirty": bool(_git("status", "--porcelain", "--untracked-files=no")),
            "seed": seed, "rejudged_from": str(source.relative_to(PROJECT_ROOT)) if args.rejudge else None,
            "startup": startup, "claim_audit": bool(ecfg["claim_audit"].get("enabled")),
            "offline_checks": bool((ecfg.get("offline_checks") or {}).get("enabled")),
            "generation": _generation(stack)}
    if args.rejudge and (source / "system.json").exists():
        # answers produced by another commit's agent (see that file), scored by this harness
        meta["system_commit"] = json.loads((source / "system.json").read_text())["commit"]
    if args.rejudge:
        meta["run"] = f"{first['started_at'][:16].replace('T', ' ')} UTC, re-judged {started:%Y-%m-%d %H:%M}"

    with (out / "results.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=report.CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    (out / "summary.md").write_text(report.markdown(meta, summary, rows, low, spot))
    # machine-readable run metadata (label, commits, golden-set hash) next to summary.md
    golden_bytes = (PROJECT_ROOT / ecfg["golden"]).read_bytes()
    (out / "meta.json").write_text(json.dumps({
        **{k: v for k, v in meta.items() if k != "startup"}, "run_date": meta["run"], "cases": len(rows),
        "golden_sha256": hashlib.sha256(golden_bytes).hexdigest()[:12],
        "prompt_sha256": hashlib.sha256(system_prompt(stack.structured).encode()).hexdigest()[:12]}, indent=2) + "\n")

    print(f"\nAccuracy {summary['accuracy']}  |  cost ${summary['cost']['total']:.2f} "
          f"(agent ${summary['cost']['agent']:.2f}, judge ${summary['cost']['judge']:.2f})")
    print(f"Failures: {summary['failures']}")
    print("\nLowest-scoring questions:")
    print("\n".join(report.spot_lines(low)))
    print(f"\nRandom sample marked correct (seed {seed}):")
    print("\n".join(report.spot_lines(spot)) or "none")
    print(f"Report: {out.relative_to(PROJECT_ROOT)}/summary.md")
    telemetry.flush()  # bounded wait for queued LangSmith traces (a no-op when tracing is off)
    if args.deepeval:
        import subprocess
        cmd = [sys.executable, str(PROJECT_ROOT / "scripts" / "deepeval_score.py"), "--run", str(out)]
        print("\nDeepEval:", " ".join(cmd[1:]))
        subprocess.run(cmd, check=False, cwd=PROJECT_ROOT)


def _generation(stack: Stack):
    try:
        return stack.store.documents.generation()
    except Exception:
        return None


if __name__ == "__main__":
    main()
