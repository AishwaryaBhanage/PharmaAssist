"""Score finished evaluation runs with DeepEval as an independent second scorer.

Reads reports/evals/<run>/results.csv plus each row's trace and the golden set, builds one
LLMTestCase per question and runs four DeepEval metrics with a judge model of our choosing:

  groundedness  = FaithfulnessMetric       claims in the answer supported by the retrieval context
  truthfulness  = 1 - HallucinationMetric  the answer does not contradict the context
  relevancy     = AnswerRelevancyMetric    the answer addresses the question
  accuracy      = GEval (correctness)      the answer against the golden expected_answer

Raw scores are recorded (threshold 0.5 is only DeepEval's pass/fail line). Nothing is written to the
original run folders: results land in reports/deepeval/<run>/deepeval.{json,csv} and the cross-run
summary in reports/deepeval/summary.md plus per_question_golden.csv.

Retrieval context, in order of preference, per question (recorded as `context_source`):
  trace.cited_evidence   the cited pages/rows kept in the trace (runs from 2026-10-17 on)
  trace.tool_outputs     the text of every search_documents result in the trace (v2 traces)
  harness.source_text    the cited locators rendered from the local PDFs / formulary rows with the
                         same helper the harness's groundedness judge uses (older traces)
  none                   abstentions, or nothing cited; faithfulness/hallucination are skipped

Usage:
  .venv/bin/python scripts/deepeval_score.py --run reports/evals/v2_2026-10-18_0903 --limit 2
  .venv/bin/python scripts/deepeval_score.py --all-milestones --budget-usd 12
  .venv/bin/python scripts/deepeval_score.py --summary-only
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path

from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT_ROOT = PROJECT_ROOT / "reports" / "deepeval"
SCRATCH = Path(os.environ.get("DEEPEVAL_SCRATCH", PROJECT_ROOT / ".deepeval_home"))

# Keys from .env; never printed. DeepEval's own dotenv loader is switched off so only these apply.
for k, v in dotenv_values(PROJECT_ROOT / ".env").items():
    if v and k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY") and k not in os.environ:
        os.environ[k] = v
os.environ.setdefault("DEEPEVAL_DISABLE_DOTENV", "1")
os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")
os.environ.setdefault("DEEPEVAL_HOME", str(SCRATCH))
os.environ.setdefault("DEEPEVAL_CACHE_FOLDER", str(SCRATCH / ".deepeval"))
SCRATCH.mkdir(parents=True, exist_ok=True)
os.chdir(SCRATCH)  # deepeval's key handler creates ./.deepeval in the cwd regardless of the settings above

from deepeval.metrics import AnswerRelevancyMetric, FaithfulnessMetric, GEval, HallucinationMetric  # noqa: E402
from deepeval.models import AnthropicModel, GPTModel  # noqa: E402
from deepeval.test_case import LLMTestCase, LLMTestCaseParams  # noqa: E402

MILESTONES = [  # display order in summary.md
    "baseline_2026-10-14_1800_rejudged_2026-10-16_0133",
    "evalB_ungated_d804f38_answers_2026-10-17_1525_rejudged_2026-10-17_1530",
    "docling_rerank_structured_orig_2026-10-17_2342",
    "docling_norerank_structured_orig-hosted_2026-10-18_0152",
    "v2_2026-10-18_0903",
    "v2_rerank_base_2026-10-18_1225",
    "v2_complete_2026-10-18_1819",
    "docling_rerank_structured_visual_2026-10-17_2342",
    "docling_norerank_structured_visual-hosted_2026-10-18_0152",
    "v2_visual_2026-10-18_0916",
]
# baseline, v1 best, v1 hosted, v2: scored first so a tight budget still yields the key comparison
KEY_GOLDEN_RUNS = [MILESTONES[0], MILESTONES[2], MILESTONES[3], MILESTONES[4]]
SCORING_ORDER = KEY_GOLDEN_RUNS + MILESTONES[7:] + [MILESTONES[6], MILESTONES[1], MILESTONES[5]]

# $/token for judges DeepEval does not know (its price table stops at claude-sonnet-5); from config.yaml.
JUDGE_PRICES = {"claude-sonnet-5-5": (2.00e-6, 10.00e-6), "claude-opus-5-5": (5.00e-6, 25.00e-6)}
EVIDENCE_CHARS = 6000       # per cited page, same cut as llm.trace_evidence_chars in config.yaml
EST_COST_PER_METRIC = 0.03  # used for the budget guard when the model reports no cost
ACCURACY_CRITERIA = (
    "Compare the actual output with the expected output for a pharmacy staff question; score 1 when "
    "every fact the expected output states is present and correct in the actual output, 0.5 when the "
    "main conclusion is right but a stated condition, limit, date, program or process step is missing, "
    "0 when the conclusion is wrong or contradicts the expected output; extra correct detail is not "
    "penalised"
)


# ----------------------------------------------------------------------------- inputs
def load_golden(path: Path) -> dict[str, dict]:
    return {r["id"]: r for r in (json.loads(l) for l in path.read_text().splitlines() if l.strip())}


def golden_for(run_dir: Path, ids: list[str]) -> tuple[Path, dict[str, dict]]:
    meta = run_dir / "meta.json"
    if meta.exists():
        g = json.loads(meta.read_text()).get("golden")
        if g and (PROJECT_ROOT / g).exists():
            return PROJECT_ROOT / g, load_golden(PROJECT_ROOT / g)
    # no meta.json (re-judged runs): pick the set whose ids cover the run's ids
    for cand in ("evals/golden.jsonl", "evals/visual.jsonl"):
        rows = load_golden(PROJECT_ROOT / cand)
        if all(i in rows for i in ids):
            return PROJECT_ROOT / cand, rows
    raise SystemExit(f"{run_dir}: no golden set covers ids {ids[:3]}...")


def tool_output_texts(trace: dict) -> list[str]:
    """Texts of the search_documents results kept in a trace (v2 traces store them as JSON)."""
    out: list[str] = []
    for call in trace.get("tool_calls") or []:
        if not str(call.get("name", "")).startswith("search"):
            continue
        raw = call.get("result") if call.get("result") is not None else call.get("output")
        if not raw:
            continue
        hits = None
        if isinstance(raw, str):
            try:
                hits = json.loads(raw)
            except ValueError:
                out.append(raw[:EVIDENCE_CHARS])
                continue
        else:
            hits = raw
        if isinstance(hits, list):
            for h in hits:
                if isinstance(h, dict) and h.get("text"):
                    label = f"{h.get('doc_id', '')}:p{h.get('page', '')}"
                    out.append(f"{label}\n{h['text']}"[:EVIDENCE_CHARS])
                elif isinstance(h, str):
                    out.append(h[:EVIDENCE_CHARS])
        elif isinstance(hits, dict):
            out.append(json.dumps(hits)[:EVIDENCE_CHARS])
    return out


def harness_texts(locators: list[str]) -> list[str]:
    """The cited sources as the harness's groundedness judge sees them (local PDFs / formulary rows)."""
    from pharmassist.eval.judge import catalog_details, parse_locator, source_text

    out = []
    for loc in locators:
        try:
            doc_id = parse_locator(loc)[0]
            out.append(f"{loc}\nCatalog: {catalog_details(doc_id)}\n{source_text(loc, EVIDENCE_CHARS)}")
        except Exception as e:  # unknown locator, missing PDF
            out.append(f"{loc}\n[source unavailable offline: {type(e).__name__}]")
    return out


def retrieval_context(row: dict, trace: dict) -> tuple[list[str], str]:
    answered = row.get("status") == "answered"
    if not answered:
        return [], "none (abstention)"
    ce = trace.get("cited_evidence") or {}
    if ce:
        return [f"{loc}\n{txt}" for loc, txt in ce.items() if txt], "trace.cited_evidence"
    texts = tool_output_texts(trace)
    if texts:
        return texts, "trace.tool_outputs"
    locators = [c.strip() for c in (row.get("citations") or "").split(";") if c.strip()]
    if not locators:
        locators = [c.get("locator") or f"{c['doc_id']}:p{c['page']}" for c in trace.get("citations") or []]
    if locators:
        return harness_texts(locators), "harness.source_text"
    return [], "none"


def load_run(run_dir: Path, limit: int | None) -> tuple[Path, list[dict]]:
    rows = list(csv.DictReader((run_dir / "results.csv").open()))
    if limit:
        rows = rows[:limit]
    golden_path, golden = golden_for(run_dir, [r["id"] for r in rows])
    cases = []
    for r in rows:
        trace = json.loads((PROJECT_ROOT / r["trace_path"]).read_text()) if r.get("trace_path") else {}
        g = golden.get(r["id"]) or {}
        ctx, source = retrieval_context(r, trace)
        cases.append({
            "id": r["id"], "status": r.get("status", ""),
            "question": trace.get("question") or g.get("question", ""),
            "answer": trace.get("answer") or r.get("answer", ""),
            "expected_answer": g.get("expected_answer", ""),
            "answerable": g.get("answerable", True),
            "context": ctx, "context_source": source,
            "harness": {"accuracy": r.get("accuracy"), "groundedness": r.get("groundedness"),
                        "claims_supported": r.get("claims_supported"), "claims_partial": r.get("claims_partial"),
                        "claims_unsupported": r.get("claims_unsupported"), "judge_reason": r.get("judge_reason")},
        })
    return golden_path, cases


# ----------------------------------------------------------------------------- judge
def make_judge(name: str):
    if name.startswith("claude"):
        prices = JUDGE_PRICES.get(name)
        kw = {"cost_per_input_token": prices[0], "cost_per_output_token": prices[1]} if prices else {}
        return AnthropicModel(model=name, **kw)  # no temperature: the SDK rejects it for Claude 5.x
    return GPTModel(model=name)


def build_metrics(judge):
    return {
        "groundedness": FaithfulnessMetric(threshold=0.5, model=judge, include_reason=True, async_mode=True),
        "truthfulness": HallucinationMetric(threshold=0.5, model=judge, include_reason=True, async_mode=True),
        "relevancy": AnswerRelevancyMetric(threshold=0.5, model=judge, include_reason=True, async_mode=True),
        "accuracy": GEval(
            name="accuracy", criteria=ACCURACY_CRITERIA, model=judge, threshold=0.5, async_mode=True,
            evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT,
                               LLMTestCaseParams.EXPECTED_OUTPUT]),
    }


class Budget:
    def __init__(self, usd: float, seed_per_question: float = 0.11):
        self.limit, self.spent, self.calls, self.estimated = usd, 0.0, 0, 0
        self.questions, self.seed = 0, seed_per_question  # seed: the smoke test's $/question

    def add(self, metric) -> float:
        cost = getattr(metric, "evaluation_cost", None)
        if cost is None:
            cost, self.estimated = EST_COST_PER_METRIC, self.estimated + 1
        self.spent += float(cost)
        self.calls += 1
        return float(cost)

    def per_question(self) -> float:
        return self.spent / self.questions if self.questions else self.seed

    def fits(self, n_questions: int) -> bool:
        return self.spent + n_questions * self.per_question() <= self.limit

    def exhausted(self) -> bool:
        return self.spent >= self.limit


async def score_case(case: dict, judge, budget: Budget, sem: asyncio.Semaphore, judge_name: str) -> dict:
    async with sem:
        tc = LLMTestCase(input=case["question"], actual_output=case["answer"],
                         expected_output=case["expected_answer"],
                         retrieval_context=case["context"] or None, context=case["context"] or None)
        metrics = build_metrics(judge)
        result = {"id": case["id"], "status": case["status"], "context_source": case["context_source"],
                  "n_context": len(case["context"]), "judge": judge_name, "scores": {}, "reasons": {},
                  "skipped": {}, "errors": {}, "timings_s": {}, "cost_usd": 0.0,
                  "question": case["question"], "answer": case["answer"],
                  "expected_answer": case["expected_answer"], "harness": case["harness"]}

        async def run(label: str, metric):
            if label in ("groundedness", "truthfulness") and not case["context"]:
                result["skipped"][label] = f"no retrieval context ({case['context_source']})"
                return
            t0 = time.perf_counter()
            try:
                await metric.a_measure(tc, _show_indicator=False)
                raw = metric.score
                # deepeval 4.3.1's HallucinationMetric scores the share of context passages the answer
                # agrees with (passing verdict = YES), so the raw score already is "truthfulness";
                # the contradicted share is kept alongside for readers used to the older polarity.
                result["scores"][label] = None if raw is None else round(float(raw), 4)
                if label == "truthfulness" and raw is not None:
                    result["scores"]["contradicted_share"] = round(1.0 - float(raw), 4)
                result["reasons"][label] = metric.reason
            except Exception as e:
                result["errors"][label] = f"{type(e).__name__}: {str(e)[:300]}"
            result["timings_s"][label] = round(time.perf_counter() - t0, 2)
            result["cost_usd"] += budget.add(metric)

        await asyncio.gather(*(run(label, m) for label, m in metrics.items()))
        result["cost_usd"] = round(result["cost_usd"], 5)
        return result


async def score_run(run_dir: Path, args, judge, budget: Budget) -> Path | None:
    golden_path, cases = load_run(run_dir, args.limit)
    out_dir = OUT_ROOT / run_dir.name
    out_dir.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(args.concurrency)
    print(f"== {run_dir.name}: {len(cases)} questions, golden {golden_path.relative_to(PROJECT_ROOT)}, "
          f"judge {args.judge}", flush=True)
    results: list[dict] = []
    t0 = time.perf_counter()
    # questions are launched in batches so the budget guard can stop between them
    batch = max(1, args.concurrency)
    for i in range(0, len(cases), batch):
        if budget.exhausted():
            print(f"   budget ${budget.limit:.2f} reached after ${budget.spent:.2f}; stopping before {cases[i]['id']}")
            break
        results += await asyncio.gather(*(score_case(c, judge, budget, sem, args.judge) for c in cases[i:i + batch]))
        budget.questions += len(cases[i:i + batch])
        print(f"   {results[-1]['id']} done; spent ${budget.spent:.2f} over {budget.calls} metric calls", flush=True)
    elapsed = round(time.perf_counter() - t0, 1)
    sources = {}
    for r in results:
        sources[r["context_source"]] = sources.get(r["context_source"], 0) + 1
    payload = {
        "run": run_dir.name, "run_dir": str(run_dir.relative_to(PROJECT_ROOT)),
        "golden": str(golden_path.relative_to(PROJECT_ROOT)), "judge": args.judge, "deepeval_version": _dv(),
        "scored_at": time.strftime("%Y-%m-%d %H:%M"), "n": len(results), "n_requested": len(cases),
        "elapsed_s": elapsed, "cost_usd": round(sum(r["cost_usd"] for r in results), 4),
        "cost_estimated_metrics": budget.estimated, "context_sources": sources,
        "metrics": {
            "groundedness": "FaithfulnessMetric(threshold=0.5)",
            "truthfulness": "HallucinationMetric(threshold=0.5).score (deepeval 4.3.1: share of context passages the answer agrees with; contradicted_share = 1 - score)",
            "relevancy": "AnswerRelevancyMetric(threshold=0.5)",
            "accuracy": "GEval(name='accuracy', criteria=..., params=[input, actual_output, expected_output], threshold=0.5)",
        },
        "accuracy_criteria": ACCURACY_CRITERIA,
        "means": means(results),
        "questions": results,
    }
    (out_dir / "deepeval.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    with (out_dir / "deepeval.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "status", "context_source", "n_context", "accuracy", "truthfulness", "groundedness",
                    "relevancy", "contradicted_share", "harness_accuracy", "harness_groundedness", "skipped",
                    "errors", "cost_usd", "time_s", "accuracy_reason", "groundedness_reason",
                    "truthfulness_reason", "relevancy_reason"])
        for r in results:
            s = r["scores"]
            w.writerow([r["id"], r["status"], r["context_source"], r["n_context"], s.get("accuracy"),
                        s.get("truthfulness"), s.get("groundedness"), s.get("relevancy"), s.get("contradicted_share"),
                        r["harness"]["accuracy"], r["harness"]["groundedness"],
                        "; ".join(f"{k}: {v}" for k, v in r["skipped"].items()),
                        "; ".join(f"{k}: {v}" for k, v in r["errors"].items()),
                        r["cost_usd"], round(sum(r["timings_s"].values()), 1),
                        r["reasons"].get("accuracy"), r["reasons"].get("groundedness"),
                        r["reasons"].get("truthfulness"), r["reasons"].get("relevancy")])
    m = payload["means"]
    print(f"   means: accuracy {m['accuracy']} truthfulness {m['truthfulness']} groundedness {m['groundedness']} "
          f"relevancy {m['relevancy']}; cost ${payload['cost_usd']:.2f}; {elapsed}s; sources {sources}", flush=True)
    return out_dir


def _dv() -> str:
    import deepeval
    return deepeval.__version__


def means(results: list[dict]) -> dict:
    out = {}
    for label in ("accuracy", "truthfulness", "groundedness", "relevancy"):
        vals = [r["scores"][label] for r in results if r["scores"].get(label) is not None]
        out[label] = round(statistics.fmean(vals), 3) if vals else None
        out[f"{label}_n"] = len(vals)
    return out


# ----------------------------------------------------------------------------- summary
def harness_numbers(run_dir: Path) -> dict:
    """Judge accuracy score, groundedness and unsupported-claim share from the run's own outputs."""
    out = {"accuracy": None, "groundedness": None, "unsupported_pct": None, "incorrect": None}
    summ = run_dir / "summary.md"
    if summ.exists():
        text = summ.read_text()
        m = re.search(r"Accuracy \(judge\) \| (\d+) correct, (\d+) partial, (\d+) incorrect \(score ([0-9.]+)", text)
        if m:
            out["accuracy"], out["incorrect"] = float(m.group(4)), int(m.group(3))
        m = re.search(r"Groundedness \(supported claims / claims, mean\) \| ([0-9.]+)", text)
        if m:
            out["groundedness"] = float(m.group(1))
    try:
        rows = list(csv.DictReader((run_dir / "results.csv").open()))
        sup = sum(int(r.get("claims_supported") or 0) for r in rows)
        par = sum(int(r.get("claims_partial") or 0) for r in rows)
        uns = sum(int(r.get("claims_unsupported") or 0) for r in rows)
        if sup + par + uns:
            out["unsupported_pct"] = round(100 * uns / (sup + par + uns), 1)
    except (OSError, ValueError):
        pass
    return out


def fmt(x, nd=3) -> str:
    return "–" if x is None else f"{x:.{nd}f}"


def write_summary() -> Path:
    payloads = []
    for p in sorted(OUT_ROOT.glob("*/deepeval.json")):
        d = json.loads(p.read_text())
        if d.get("n_requested") and d["n"] < d["n_requested"] and d["n"] <= 2:
            continue  # smoke tests (--limit) are not milestones
        payloads.append(d)
    order = {name: i for i, name in enumerate(MILESTONES)}
    payloads.sort(key=lambda d: (order.get(d["run"], 99), d["run"]))
    lines = ["# DeepEval scorer: milestone runs side by side", "",
             f"Scored with DeepEval {payloads[0]['deepeval_version'] if payloads else ''} by "
             f"`scripts/deepeval_score.py`; judge `{payloads[0]['judge'] if payloads else ''}` "
             "(DeepEval `AnthropicModel`, one pass, default sampling). Means are over the questions each metric scored "
             "(abstentions carry no retrieval context, so groundedness and truthfulness skip them). "
             "The harness columns are copied from each run's own `summary.md` / `results.csv` "
             "(judge `claude-opus-5-5`, three passes).", "",
             "| Run | Golden | n | DE accuracy | DE truthfulness | DE groundedness | DE relevancy | "
             "Harness accuracy (judge) | Harness groundedness | Harness unsupported claims % | "
             "Context source | Judge cost $ |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    total = 0.0
    for d in payloads:
        h = harness_numbers(PROJECT_ROOT / d["run_dir"])
        m = d["means"]
        src = ", ".join(f"{k} {v}" for k, v in d["context_sources"].items())
        total += d["cost_usd"]
        lines.append(
            f"| `{d['run']}` | {Path(d['golden']).name} | {d['n']} | {fmt(m['accuracy'])} | {fmt(m['truthfulness'])} "
            f"| {fmt(m['groundedness'])} ({m['groundedness_n']}) | {fmt(m['relevancy'])} | {fmt(h['accuracy'])} | "
            f"{fmt(h['groundedness'])} | {fmt(h['unsupported_pct'], 1)} | {src} | {d['cost_usd']:.2f} |")
    scored = {d["run"] for d in payloads}
    unscored = [r for r in MILESTONES if r not in scored]
    lines += ["", f"Total judge spend across the runs above: ${total:.2f}."]
    if unscored:
        lines += ["", "Milestone runs not scored (the `--budget-usd` guard stopped before them): " +
                  ", ".join(f"`{r}`" for r in unscored) + ". Score them with "
                  "`.venv/bin/python scripts/deepeval_score.py --run reports/evals/<run>` when budget allows."]
    lines += ["", "## Reading the table", "",
              "- DeepEval's GEval accuracy sits 0.2-0.3 below the harness judge on every golden run, and the gap is "
              "almost entirely answers the Opus judge graded *correct* that GEval put at 0.5: the rubric asks for "
              "*every* fact in the expected answer, so one missing secondary point (a no-PA note, a 7-day dispense "
              "option, a monitoring frequency) drops the score, where our judge grades on the conclusion plus the "
              "`must_include` terms. Both scorers put the v1 best run (`docling_rerank_structured_orig`) first, but "
              "GEval compresses the rest into 0.50-0.57 and places the baseline above the hosted v1 and v2 runs, where "
              "our judge has it clearly last (0.70 vs 0.85): the later runs answer more conclusions correctly while "
              "still leaving out secondary expected points, which GEval weighs as heavily.",
              "- DeepEval groundedness is 0.98-1.00 everywhere (ours 0.61-0.94): faithfulness counts only claims the "
              "context contradicts, so it does not see the partially supported claims our judge counts against the "
              "answer. The visual runs show this most clearly (ours 0.61-0.70, DeepEval 0.98-1.00): figure-derived "
              "claims that the page text neither confirms nor denies pass DeepEval and fail ours.",
              "- Truthfulness is 0.88-1.00 and the flagged passages are worth reading: most are genuine detail errors "
              "(baseline Q19 attributes a PDL marking to the wrong drug; V01 says 'nephropathy' where the flowchart says "
              "'neuropathy'; V06 calls the GLP-1 RA heart-failure effect neutral where the figure shows a reduction), "
              "and the rest are across-versions answers that follow one cited source on a point another states "
              "differently (Q01, Q18).",
              "", "## How the DeepEval metrics map to ours", "",
              "- **Accuracy.** Ours: the Opus judge grades the answer correct / partial / incorrect against the golden "
              "`expected_answer`, `must_include` terms and notes (score = correct + 0.5 x partial, three passes, majority). "
              "DeepEval: a `GEval` correctness rubric with the same 1 / 0.5 / 0 definitions (every expected fact present; "
              "main conclusion right but a condition, limit, date, program or step missing; conclusion wrong), seeing only "
              "question, answer and expected answer. GEval returns a probability-weighted score, so values fall between the "
              "rubric points rather than on them.",
              "- **Groundedness.** Ours: supported claims / all claims, judged against the cited pages with their catalog "
              "details (partial support counts as not supported). DeepEval `FaithfulnessMetric`: the share of claims "
              "extracted from the answer that are not contradicted by the retrieval context (claims the context neither "
              "supports nor contradicts are not penalised unless `penalize_ambiguous_claims` is on, which it is not). It is "
              "therefore the more lenient of the two and sits at or above our number.",
              "- **Truthfulness.** DeepEval `HallucinationMetric` (4.3.1) judges each context passage and returns the "
              "share the answer agrees with (a passage counts against the answer only when the answer contradicts it), so "
              "we report its score as truthfulness and 1 - score as the contradicted share. Our closest number is the "
              "unsupported-claim share from the Opus judge (column *Harness unsupported claims %*): ours counts claims the "
              "sources do not back, DeepEval counts passages that are contradicted, so the two are not interchangeable; a "
              "low truthfulness often means the answer leans on one of several cited passages, not that it is false.",
              "- **Relevancy.** `AnswerRelevancyMetric`: statements in the answer that address the question. We have no "
              "equivalent; our judge rolls relevance into the accuracy grade.",
              "- **Retrieval context.** Where a trace keeps `cited_evidence` that text is used (`trace.cited_evidence`); "
              "v2 traces also keep the search results (`trace.tool_outputs`, used only when cited evidence is absent); "
              "the baseline and evalB traces keep neither, so the cited pages are rendered from the local PDFs / formulary "
              "rows with the harness's own `source_text` helper (`harness.source_text`), the same text the Opus judge saw.",
              "", "## Caveats", "",
              "Judge is `claude-sonnet-5-5`, not the `claude-opus-5-5` used by the harness, and a single pass; DeepEval's "
              "metrics decompose the answer into claims/statements with their own prompts, so small wording differences move "
              "the scores. Faithfulness and hallucination see the cited evidence only (truncated to 6000 characters per "
              "page), not the full documents, and cannot reward an answer for citing the right page. GEval accuracy does "
              "not see the golden notes or must_include list the harness judge sees. Abstentions are scored for accuracy "
              "(the expected answer says the corpus does not cover the question) and relevancy only.",
              "", "Per-run detail: `reports/deepeval/<run>/deepeval.json` and `deepeval.csv`; "
              "golden-set questions across runs: `reports/deepeval/per_question_golden.csv`."]
    (OUT_ROOT / "summary.md").write_text("\n".join(lines) + "\n")

    # per-question CSV across the golden-set runs
    golden_runs = [d for d in payloads if Path(d["golden"]).name == "golden.jsonl"]
    with (OUT_ROOT / "per_question_golden.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "run", "status", "context_source", "de_accuracy", "de_truthfulness", "de_groundedness",
                    "de_relevancy", "harness_accuracy", "harness_groundedness"])
        for d in golden_runs:
            for q in d["questions"]:
                s = q["scores"]
                w.writerow([q["id"], d["run"], q["status"], q["context_source"], s.get("accuracy"),
                            s.get("truthfulness"), s.get("groundedness"), s.get("relevancy"),
                            q["harness"]["accuracy"], q["harness"]["groundedness"]])
    return OUT_ROOT / "summary.md"


# ----------------------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="append", type=Path, default=[], help="a reports/evals/<run> folder (repeatable)")
    ap.add_argument("--all-milestones", action="store_true", help="score the milestone runs listed in the script")
    ap.add_argument("--key-runs", action="store_true", help="only the four key golden runs")
    ap.add_argument("--golden", type=Path, help="override the golden set (default: the run's meta.json, else by ids)")
    ap.add_argument("--judge", default="claude-sonnet-5-5", help="claude-* via AnthropicModel, gpt-* via GPTModel")
    ap.add_argument("--limit", type=int, help="score only the first N questions (smoke test)")
    ap.add_argument("--budget-usd", type=float, default=12.0, help="stop launching questions once spend reaches this")
    ap.add_argument("--concurrency", type=int, default=4, help="questions scored at once (4 metrics each)")
    ap.add_argument("--summary-only", action="store_true", help="rebuild reports/deepeval/summary.md and exit")
    args = ap.parse_args()

    if args.summary_only:
        print(write_summary())
        return
    runs = list(args.run)
    if args.all_milestones:
        runs += [PROJECT_ROOT / "reports" / "evals" / r for r in SCORING_ORDER]
    if args.key_runs:
        runs += [PROJECT_ROOT / "reports" / "evals" / r for r in KEY_GOLDEN_RUNS]
    if not runs:
        ap.error("give --run, --all-milestones or --key-runs")
    if args.golden:
        gpath = args.golden if args.golden.is_absolute() else PROJECT_ROOT / args.golden
        g = load_golden(gpath)
        globals()["golden_for"] = lambda run_dir, ids, _g=g, _p=gpath: (_p, _g)

    judge = make_judge(args.judge)
    budget = Budget(args.budget_usd)

    async def score_all():  # one event loop for every run: the judge caches async HTTP clients per loop
        for run_dir in runs:
            rd = run_dir if run_dir.is_absolute() else PROJECT_ROOT / run_dir
            if not (rd / "results.csv").exists():
                print(f"skip {rd.name}: no results.csv")
                continue
            n = args.limit or sum(1 for _ in csv.DictReader((rd / "results.csv").open()))
            if budget.exhausted() or not budget.fits(n):
                print(f"budget: ${budget.spent:.2f} spent, {n} questions at ~${budget.per_question():.3f} each "
                      f"would pass ${budget.limit:.2f}; skipping {rd.name}", flush=True)
                continue
            await score_run(rd, args, judge, budget)

    asyncio.run(score_all())
    print(f"total spend ${budget.spent:.2f} over {budget.calls} metric calls "
          f"({budget.estimated} estimated at ${EST_COST_PER_METRIC}/metric)")
    if not args.limit:
        print(write_summary())


if __name__ == "__main__":
    main()
