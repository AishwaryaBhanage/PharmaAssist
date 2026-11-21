# PharmAssist: evaluation

> Code paths in this document are relative to the [repository root](../); the write-ups live in `writeup/`.

**In 20 seconds.** PharmAssist was measured on a frozen set of 20 pharmacist questions and 8 figure questions
after every change, from the first baseline (2026-10-14) to production (2026-10-18), with the same judge and
harness. Production scores accuracy 0.85 with 0 incorrect answers, groundedness 0.937 (share of answer claims
the cited pages support), p95 latency 21.4 s against the 30 s rule, $0.110 per question
(`reports/evals/v2_2026-10-18_0903/summary.md`). A second, independent scorer (DeepEval) ranks the versions the
same way (§3.2). Every number here is copied from a run folder under `reports/`; nothing is estimated.
[DESIGN.md](DESIGN.md) §4 and §5 carry the production numbers and the acceptance rule; this is the detailed companion.

## 1. Question sets

| Set | File | Questions | sha256 (first 12) | Frozen since |
|---|---|---|---|---|
| Golden | `evals/golden.jsonl` | 20 | `2664dd7d24fb` | 2026-10-14 (unchanged since added) |
| Visual | `evals/visual.jsonl` | 8 | `0823626fe0c3` | 2026-10-18 |

The golden set covers the question shapes the assistant is designed for (conflicts across versions, multi-document, synthesis,
structured rows, reject codes, the prior-auth process, effective dates, no program stated, silence versus
absence) plus one unanswerable question (Q20). Each record has the question, a pharmacist-style
`expected_answer`, `must_include` terms and `gold` pages or rows. The visual set (V01–V08) can only be answered
from flowcharts, charts and tables printed as images in the VA/DoD guidelines. Every run writes the set's hash
into `meta.json`. Eight answers with the weak ones explained: [EXAMPLES.md](EXAMPLES.md).

## 2. Method

### 2.1 A run (`scripts/run_eval.py`)

1. Warm the store, drug tables and search (timed separately, never part of a question's latency).
2. Ask each question once, one at a time, through the same `ask()` the API serves. The full trace (model turns,
   tool calls and results, citations, timings, tokens) goes to `traces/<timestamp>-<slug>.json`.
3. Judge with Claude Opus 5.5 (effort medium) in three passes: majority grade, median groundedness. Two runs
   used one pass and are marked in §3.1.
4. Write `reports/evals/<run>/results.csv` (one row per question), `summary.md` (metrics, per-question table,
   lowest-scoring answers, caveats) and `meta.json` (models, judge passes, dataset and prompt hashes, commit).
5. `--rejudge reports/evals/<run>` re-scores saved answers with the current judges; `--golden evals/visual.jsonl
   --tag visual` runs the visual set; offline checks (`--checks`, `--audit`) never run while answering.

### 2.2 The Opus judge

The accuracy judge sees the question, the reference, the `must_include` terms, the notes and the answer, and
grades correct / partial / incorrect with no outside knowledge; declining an answerable question is incorrect,
declining Q20 is correct. The groundedness judge splits the answer into claims and checks each against the text
of the cited pages and rows only; partial support counts as not supported. Both prompts are verbatim in
[`docs/PROMPTS.md`](../docs/PROMPTS.md) §2.

### 2.3 Metrics

| Metric | Definition | Method |
|---|---|---|
| **Accuracy grade** | correct / partial / incorrect; score = correct 1, partial 0.5 | Opus judge against the reference and notes only |
| must_include | share of key terms conveyed | Judge (paraphrase counts) and a literal substring check, side by side |
| **Groundedness** | supported claims / claims, per answer | Groundedness judge, cited pages and rows only |
| **Unsupported-claim rate** | unsupported claims / evaluated claims | Same judge; claims the cited evidence does not back |
| Citation support rate | fully supported claims / evaluated claims | Same judge; partial support counts as not supported |
| Citation validity | cited references that exist / references | Deterministic, against the catalog and the formulary sheet |
| Citation coverage | answered cases with ≥ 1 citation / answered cases | Answer-level proxy |
| Citation precision / recall | cited gold / cited; cited gold / gold | Against the golden `gold`; precision is a lower bound |
| Retrieval recall | gold pages any tool returned / gold pages | From the trace |
| Recall@5 / @10 | gold pages in a direct search's top k | No agent; isolates retrieval |
| **Safe** | no unsupported claim shown (or abstained) | From the groundedness judge |
| **Useful** | answerable question that got a non-abstaining answer | From status and grade |
| Over-abstention | abstained on an answerable question | Deterministic |
| Failure class | source not ingested / ingested but not retrieved / retrieved but answered wrong / answered right but cited wrong | Earliest stage that explains the miss; ambiguous cases set by hand in `evals/failure_overrides.yaml` |
| Latency | end-to-end `ask()` seconds, p50 and p95 | Per question |
| Cost | agent tokens × configured prices | From API usage; excludes judge and embeddings |

Accuracy alone hides *why* an answer failed: groundedness separates "wrong" from "unsupported"; retrieval recall
and the failure classes say whether to fix ingestion, retrieval or generation; safe / useful / over-abstention
exposed the trade-off of the live safety gate (§4.3). Limits: groundedness judges against the *text* of a cited
page, so a claim drawn from a figure printed on it reads as unsupported (§4.5); accuracy grades against one
reference. Judge results are labelled as estimates everywhere.

### 2.4 DeepEval as the scorer (from 2026-10-18)

`scripts/run_eval.py --label <name> --deepeval` runs the agent on a set and scores it with
`scripts/deepeval_score.py`, which also re-scores any finished run (`--run reports/evals/<run>`). DeepEval 4.3.1,
judge `claude-sonnet-5-5`, one pass; one test case per question from the answer, the golden `expected_answer`
and the cited evidence in the trace. Metrics: **accuracy** (a `GEval` correctness rubric with the harness's
1 / 0.5 / 0 definitions, probability-weighted), **groundedness** (`FaithfulnessMetric`: claims the context does
not *contradict*, so it sits at or above ours), **truthfulness** (`HallucinationMetric`) and **relevancy**
(`AnswerRelevancyMetric`). Abstentions carry no context and are skipped. About $0.09 per question.

## 3. Results

### 3.1 Every evaluation, baseline to production (golden set, 20 questions)

Judge Claude Opus 5.5, three passes unless marked; same harness throughout; folders under `reports/evals/`. The
baseline row is the re-judged run (the same answers re-scored under the current judge prompts). Unsupported-claim
% is reported for the runs DeepEval also scored; Safe was not printed before 2026-10-17 (n/r).

| Date | Setup (run folder) | Accuracy (correct / partial / incorrect) | Groundedness | Unsupported claims | Safe | p50 / p95 | Agent $/question |
|---|---|---|---|---|---|---|---|
| Oct 14, re-judged Oct 16 | Baseline: Sonnet, fixed 350-token chunks, bge-small embeddings (`baseline_2026-10-14_1800_rejudged_2026-10-16_0133`) | 0.70 (8 / 12 / 0) | 0.910 | 2.0% | n/r | 7.2 s / 11.0 s | $0.033 |
| Oct 16 | + structured drug lookups (`structured_2026-10-16_0040_rejudged_2026-10-16_1224`) | 0.75 (11 / 8 / 1) | 0.876 | — | n/r | 7.5 s / 13.8 s | $0.031 |
| Oct 16 | + OpenAI `text-embedding-3-large`, fixed chunks (`fixed_openai_structured_2026-10-16_0132`) | 0.775 (12 / 7 / 1) | 0.882 | — | n/r | 7.6 s / 10.2 s | $0.033 |
| Oct 16 | + parent/child sections, hybrid search, `bge-reranker-base` (`sections_rerank_structured_2026-10-16_1241`) | 0.80 (13 / 6 / 1) | 0.889 | — | n/r | 10.0 s / 20.0 s | $0.052 |
| Oct 16 | + search-query schema fix (`sections_rerank_structured_local_post-query-schema-fix_2026-10-16_2054`) | 0.85 (14 / 6 / 0) | 0.859 | — | n/r | 9.2 s / 13.9 s | $0.050 |
| Oct 17 | + original question searched beside the agent's query, fused (`evalB_ungated_d804f38_answers_2026-10-17_1525_rejudged_2026-10-17_1530`; 1 judge pass) | 0.875 (15 / 5 / 0) | 0.889 | — | 18/20 | 11.7 s / 20.1 s | $0.069 |
| Oct 17 | Live safety gate experiment, rejected (`sections_rerank_structured_2026-10-17_1516`; 1 judge pass) | 0.30 (4 / 4 / 12) | 0.876 | — | 20/20 | 12.6 s / 20.1 s | $0.081 |
| Oct 17 | **v1 best**: Docling sections + figure records + reranker, local (`docling_rerank_structured_orig_2026-10-17_2342`) | **0.925** (17 / 3 / 0) | 0.887 | 2.5% | 16/20 | 10.6 s / 22.2 s | $0.064 |
| Oct 18 | v1 hosted on Lambda, no reranker (`docling_norerank_structured_orig-hosted_2026-10-18_0152`) | 0.85 (15 / 4 / 1) | 0.878 | 4.3% | 15/20 | 7.2 s / 12.0 s | $0.067 |
| Oct 18 | **v2 production**: `gpt-5.5`, Postgres hybrid search, semantic cache, no reranker (`v2_2026-10-18_0903`) | 0.85 (14 / 6 / 0) | **0.937** | 2.5% | 17/20 | 10.8 s / 21.4 s | $0.110 |
| Oct 18 | v2 + `bge-reranker-large`, depth 50 (`v2_rerank_large_2026-10-18_1132`) | 6 of 20 errored (5 over 30 s); 0.821 (9 / 5 / 0) on the 14 answered | 0.857 | — | 13/14 | 26.5 s / 55.1 s | $0.056 (14 answered) |
| Oct 18 | v2 + `bge-reranker-base`, depth 20 (`v2_rerank_base_2026-10-18_1225`) | 0.70 (8 / 12 / 0) | 0.867 | — | 14/20 | 13.9 s / 23.5 s | $0.100 |
| Oct 18 | v2 + minimum-lookups nudge + completeness pass (`v2_complete_2026-10-18_1819`; flags, off in production) | 0.85 (14 / 6 / 0) | 0.942 | 1.2% | 18/20 | 19.2 s / 30.6 s (1 over 30 s) | $0.173 |
| Oct 18 | v2 + pre-submit checklist + one search per sub-question (`v2_checklist_2026-10-18_1926`; prompt extras, off in production) | 0.825 (13 / 7 / 0) | 0.957 | 0.0% | 20/20 | 12.7 s / 18.2 s | $0.136 |

Production-run details (`v2_2026-10-18_0903/summary.md`, prompt hash `8c05de6fe23a`): judge
passes unanimous on 18/20 grades; must_include 52/54 by the judge, 21/54 by literal substring; retrieval recall
0.931 (53 of 59 gold sources returned by some tool); citation precision / recall 0.743 / 0.793; 0 citations
failing the in-code check; 0 answers without citations; useful 19/19; over-abstention 0; Q20 abstained
correctly; 0 questions over 30 s; 19/20 within 60–120 words; failure classes: ingested but not retrieved 3,
retrieved but answered wrong 3, answered right but cited wrong 5; cost agent $2.20, judge $2.61.

**Unsupported claims by version** (the judge's unsupported claims over all claims; "answers with ≥ 1
unsupported" is the staff-facing view):

| Version | Claims | Unsupported | Rate | Answers with ≥1 unsupported | Incorrect answers |
|---|---|---|---|---|---|
| Baseline (Sonnet, fixed chunks) | 152 | 3 | 2.0% | 3 / 20 | 0 |
| v1 best (Docling + reranker, local) | 160 | 4 | 2.5% | 4 / 20 | 0 |
| v1 hosted (no reranker) | 161 | 7 | 4.3% | 5 / 20 | 1 |
| v2 production | 118 | 3 | 2.5% | 3 / 20 | 0 |
| v2 + completeness pass (not shipped) | 163 | 2 | 1.2% | 2 / 20 | 0 |

v2 writes shorter answers with far fewer partially supported claims (4 against 13–16 in v1), which is where its
0.937 comes from.

### 3.2 Two judges on the same answers: DeepEval against the Opus harness

DeepEval 4.3.1, judge `claude-sonnet-5-5`, one pass; means over the questions each metric scored (count in
parentheses where it differs from n). Raw scores: `reports/deepeval/<run>/deepeval.json`.

| Run | Set | n | DE accuracy | DE truthfulness | DE groundedness | DE relevancy | Harness accuracy | Harness groundedness | Harness unsupported % | Judge cost $ |
|---|---|---|---|---|---|---|---|---|---|---|
| `baseline_2026-10-14_1800_rejudged_2026-10-16_0133` | golden | 20 | 0.570 | 0.930 | 0.976 (19) | 0.951 | 0.700 | 0.910 | 2.0 | 1.76 |
| `docling_rerank_structured_orig_2026-10-17_2342` | golden | 20 | 0.625 | 0.963 | 1.000 (19) | 0.958 | 0.925 | 0.887 | 2.5 | 1.85 |
| `docling_norerank_structured_orig-hosted_2026-10-18_0152` | golden | 20 | 0.528 | 1.000 | 1.000 (18) | 0.949 | 0.850 | 0.878 | 4.3 | 1.95 |
| `v2_2026-10-18_0903` | golden | 20 | 0.515 | 0.989 | 1.000 (19) | 0.903 | 0.850 | 0.937 | 2.5 | 1.78 |
| `v2_complete_2026-10-18_1819` | golden | 20 | 0.500 | 1.000 | 0.995 (19) | 0.931 | 0.850 | 0.942 | 1.2 | 2.09 |
| `v2_checklist_2026-10-18_1926` | golden | 20 | 0.410 | 0.974 | 1.000 (19) | 0.916 | 0.825 | 0.957 | 0.0 | 1.73 |
| `docling_rerank_structured_visual_2026-10-17_2342` | visual | 8 | 0.988 | 0.875 | 0.984 (8) | 0.961 | 1.000 | 0.703 | 8.5 | 0.71 |
| `docling_norerank_structured_visual-hosted_2026-10-18_0152` | visual | 8 | 0.988 | 0.938 | 1.000 (8) | 0.948 | 1.000 | 0.667 | 11.7 | 0.72 |
| `v2_visual_2026-10-18_0916` | visual | 8 | 0.975 | 1.000 | 1.000 (8) | 0.982 | 1.000 | 0.614 | 17.0 | 0.56 |
| `v2_checklist_visual_2026-10-18_1939` | visual | 8 | 0.875 | 1.000 | 0.975 (8) | 0.972 | 1.000 | 0.619 | 13.0 | 0.60 |

Total DeepEval judge spend $13.73. Not scored (the `--budget-usd` guard stopped first):
`evalB_ungated_d804f38_answers_2026-10-17_1525_rejudged_2026-10-17_1530`, `v2_rerank_base_2026-10-18_1225`.

Both scorers put the v1 best run first and rank the golden versions alike, but GEval sits 0.2–0.3 below Opus:
its rubric asks for every fact in the expected answer, so one missing secondary point costs half the score.
DeepEval groundedness is 0.98–1.00 everywhere (ours 0.61–0.94) because faithfulness penalises contradiction,
not missing support. Its truthfulness flags are real detail errors (baseline Q19 attributes a PDL marking to the
wrong drug; V01 says "nephropathy" where the flowchart says "neuropathy"). Two judges that agree on the ranking
and disagree on the scale is the useful outcome: the harness numbers are the strict ones.

### 3.3 The visual set (8 figure questions)

| Run folder | Accuracy | Groundedness | Safe | p50 / p95 | Agent $/question |
|---|---|---|---|---|---|
| `docling_rerank_structured_visual_2026-10-17_2342` (v1 best) | 1.00 (8 / 0 / 0) | 0.703 | 5/8 | 12.7 s / 26.5 s | $0.065 |
| `docling_norerank_structured_visual-hosted_2026-10-18_0152` (v1 hosted) | 1.00 (8 / 0 / 0) | 0.667 | 4/8 | 6.0 s / 6.9 s | $0.059 |
| `v2_visual_2026-10-18_0916` (**v2 production**) | 1.00 (8 / 0 / 0) | 0.614 | 5/8 | 6.5 s / 6.9 s | $0.052 |
| `v2_complete_visual_2026-10-18_1838` (completeness pass, off) | 1.00 (8 / 0 / 0) | 0.783 | 7/8 | 17.0 s / 20.9 s | $0.155 |
| `v2_checklist_visual_2026-10-18_1939` (checklist, off) | 1.00 (8 / 0 / 0) | 0.619 | 6/8 | 7.1 s / 10.7 s | $0.081 |

Every visual answer is graded correct; the low groundedness is the measurement effect of §4.5 (5 of 8
production answers are classed "answered right but cited wrong").

### 3.4 Retrieval alone (no agent, no judge)

Direct hybrid search (dense + BM25, RRF k = 60) on the questions with PDF gold pages. Recall@k counts gold pages
covered by the top-k returned units; *recall at matched tokens* gives every setup the same text budget, so bigger
units cannot win by returning more text. The experiment that chose the retrieval unit
(`reports/retrieval/2026-10-16_0121/results.md`, 19 golden questions, one variable changed per setup):

| Setup | Chunks (parents) | Embedder | Reranker | Recall@5 | Recall@10 | Recall at matched tokens |
|---|---|---|---|---|---|---|
| A `baseline` | fixed 350 / 50 overlap (1,521) | bge-small-en-v1.5 | – | 0.552 | 0.646 | 0.838 |
| B `fixed_openai` | same as A | text-embedding-3-large | – | 0.567 | 0.713 | 0.877 |
| C `sections_bge` | sections (1,962 children, 581 parents) | bge-small-en-v1.5 | – | 0.652 | 0.750 | 0.732 |
| D `sections_openai` | same as C | text-embedding-3-large | – | 0.687 | 0.833 | 0.833 |
| E `sections_openai_rerank` | same as C | text-embedding-3-large | bge-reranker-base | 0.675 | 0.882 | 0.864 |

The Docling index on the same 19 golden questions (`reports/retrieval/2026-10-18_0042/results.md`) and on the
visual set (`reports/retrieval/2026-10-18_0043/results.md`):

| Setup | Chunks (parents) | Reranker | Golden Recall@5 | Golden Recall@10 | Visual Recall@5 | Visual Recall@10 |
|---|---|---|---|---|---|---|
| D `sections_openai` | 1,962 (581) | – | 0.687 | 0.833 | 0.646 | 0.875 |
| E `sections_openai_rerank` | 1,962 (581) | bge-reranker-base | 0.675 | 0.882 | 0.750 | 0.875 |
| F0 `docling_norerank` | 1,983 (589) | – | 0.744 | 0.820 | 0.875 | 0.958 |
| F `docling_sections` | 1,983 (589) | bge-reranker-base | 0.729 | 0.842 | 0.708 | 1.000 |

The reranker lifts the tail (Recall@10), not the head, at 5–19 s per search on CPU. In production the single
hybrid search on the question text gives Recall@5 / @10 of 0.636 / 0.768, while the agent's searches and
lookups together reach 0.931 of the gold sources (`v2_2026-10-18_0903/summary.md`). A v1 parity test of
Pinecone against the local dense matrix gave identical Recall@5 / @10 / @20 and MRR; that path was removed with v2.

## 4. Reading the results

### 4.1 Why v2 is in production although the v1 best scored higher

The 0.925 (`docling_rerank_structured_orig_2026-10-17_2342`) was measured on a laptop. Its one ingredient that
does not survive hosting is the cross-encoder reranker: 15–23 s per search on a 2-vCPU server, two to four
searches per question, so it cannot meet the 30-second rule. Hosted v1 without it scored 0.85
(`docling_norerank_structured_orig-hosted_2026-10-18_0152`). Under the same constraint v2 matches the 0.85 and
improves what staff see: groundedness 0.937 against 0.878, 17/20 answers with no unsupported claim against
15/20, no incorrect answer, cached repeats in under a second. Two ways to recover the 0.925 remain open: the
reranker at depth 50 on a Graviton3 or GPU box (about +$115/month), or Sonnet as v2's primary model (one line
in `config.yaml`).

### 4.2 The reranker inside v2

Retried on 2026-10-18 on the production hardware. `bge-reranker-large` at depth 50 took 19 s per search on CPU:
5 answers went over 30 s and 6 of 20 questions ended in provider timeouts, with 0.821 on the 14 that answered
(`v2_rerank_large_2026-10-18_1132`). `bge-reranker-base` at the depth the CPU can afford (20) scored 0.70
against 0.85 without it (`v2_rerank_base_2026-10-18_1225`). So v2 ships with `search.rerank: null`; the code
path stays behind the flag.

### 4.3 The live safety gate (rejected)

On 2026-10-17 the agent was rebuilt to submit atomic claims, each checked
deterministically against only the pages it cited; one failing direct claim made the whole answer abstain. On
the same 20 questions the gated agent scored 0.300 (4 / 4 / 12), answering 7 of 19 answerable questions,
against 0.875 (15 / 5 / 0) and 19 of 19 for the ungated agent; the gate removed the 2 unsupported claims the
ungated run showed (`sections_rerank_structured_2026-10-17_1516`, `evalB_ungated_..._1530`). Decision (commit
`cc5331f`): the in-code citation check stays live; every other check runs offline on saved traces, and a test
proves no checker is called while answering. Safe / useful / over-abstention entered the harness because of
this experiment.

### 4.4 The six partial answers in production

No answer in `v2_2026-10-18_0903` was graded incorrect. The six partials are three retrieval misses (Q06, Q07,
Q10: the gold page was never returned by any tool) and three omissions with the evidence in hand (Q01, Q13,
Q18: recall@10 1.0). The per-question table is in [EXAMPLES.md](EXAMPLES.md). The references are shorter than
the answers (median 67 against 92 words): the model spends words on clinical detail and drops the reference's
secondary points.

### 4.5 Two answer-side experiments (kept as switches, off)

Both targeted the omissions. The **completeness pass** (`agent.min_lookups`, `agent.completeness_pass`) raised
groundedness to 0.942, halved the unsupported-claim rate (2.5% → 1.2%) and fixed Q18, but left accuracy at 0.85
and added 8 s of median latency with one answer over 30 s (`v2_complete_2026-10-18_1819`). The **pre-submit
checklist** with one search per sub-question (`agent.prompt_extras`) cut unsupported claims to 0 (groundedness
0.957, Safe 20/20) but ended at 0.825 (`v2_checklist_2026-10-18_1926`). Three of the remaining partials are
retrieval misses no prompt can fix, so neither shipped: [DESIGN.md](DESIGN.md) §5's rule is that accuracy must
rise and groundedness and recall must not fall.

**Figure-derived answers.** Every visual answer is correct, yet visual groundedness is 0.61–0.70: the judge gets
the cited page's extracted text, which for a flowchart image is a heading and an abbreviation list, so
picture-derived claims read as unsupported. The fix is in measurement (give the judge the figure
interpretation) and in the product (cite the figure plus the appendix page); neither changes an answer.

### 4.6 Judge noise on 20 questions

Each question runs once and the agent is not deterministic; one grade step on one question moves the score by
0.025, so a one-question difference between runs is within noise. The passes were unanimous on 18 of 20 grades
in the production run. The judge is a Claude model and may share the agent's blind spots; each `summary.md`
prints the lowest-scoring answers and a random correct sample for human spot checks, and DeepEval is the
independent cross-check. The re-judged baseline differs from its original judging (0.70 against 0.725), which
is why one judging configuration is used for every row of §3.1.

## 5. Where the data is

- `reports/evals/<run>/`: `summary.md`, `results.csv` (one row per question: grade and judge reason,
  groundedness, failure class, retrieval and citation metrics, timing, cost, the full answer, `trace_path`) and
  `meta.json`; the folders kept are exactly those named in §3.
- `traces/<timestamp>-<question-slug>.json`: the trace each `trace_path` points at (milestone runs committed).
- `reports/deepeval/<run>/deepeval.json` and `deepeval.csv`: DeepEval scores and reasons for the ten runs of §3.2.
- `reports/retrieval/<timestamp>/results.md` and `per_question.csv`: the three retrieval-only experiments of §3.4.
- `reports/parsing/VISUAL_EXTRACTION.md`, `FIGURES.json`, `PARSE_REPORT.json`: parsing and figure extraction.
- LangSmith project `pharmassist`: one run per answer with child runs per model call, tool call and
  retrieval. Access by invitation; not checked in.
- `evidence/`: the production live check and screenshots ([evidence/README.md](evidence/README.md)).

## 6. How to run an evaluation, and what must not change

From the repository root with the local stack up (`docker compose up -d postgres valkey elasticmq
s3 createbuckets`, then `scripts/seed_local.py`; see [SOLUTION.md](SOLUTION.md)):

```bash
.venv/bin/python scripts/run_eval.py --label my_change --deepeval            # golden set, DeepEval scorer
.venv/bin/python scripts/run_eval.py --label my_change_visual --deepeval \
    --golden evals/visual.jsonl --tag visual                                     # figure questions
.venv/bin/python scripts/run_eval.py --label my_change                       # Opus three-pass judge instead
.venv/bin/python scripts/run_eval.py --rejudge reports/evals/<run>           # re-score saved answers
.venv/bin/python scripts/deepeval_score.py --run reports/evals/<run>         # DeepEval on a finished run
```

A golden run costs about $5 and a visual run about $1.25 including the Opus judge; DeepEval adds about $0.09
per question. The acceptance rule ([DESIGN.md](DESIGN.md) §5): golden accuracy ≥ 0.85 with 0 incorrect; Q20
returns the exact no-answer sentence; 0 questions over 30 s; 0 answers without citations; 0 citations failing
the in-code check; ≥ 18/20 answers within 60–120 words.

What must not change:

- `evals/golden.jsonl` and `evals/visual.jsonl` are frozen; their hashes (`2664dd7d24fb`, `0823626fe0c3`) are
  written into every run's `meta.json`, and a run whose hash differs is not comparable with §3.
- `meta.json` also records the prompt hash, models, effort, passes, tool cap, deadline, commit and seed; compare
  these before comparing numbers, and use `--rejudge` when the judge changed.
- The judge model, passes and prompts (`docs/PROMPTS.md` §2) stay fixed for any row added to §3.1; a different
  judge gets its own column, as DeepEval does.
- Run folders under `reports/evals/` are never edited after the run.
