# PharmAssist: design

> Code paths in this document are relative to the [repository root](../); the write-ups live in `writeup/`.

**In 20 seconds.** PharmAssist answers one pharmacy operations question at a time, with page-level citations,
from the 11 public VA, Medicare Part D and NY Medicaid documents listed in [docs/SOURCES.md](../docs/SOURCES.md). Golden set of 20 questions:
accuracy 0.85 with 0 incorrect answers, groundedness 0.937 (share of answer claims the cited pages support),
latency 10.8 s median and 21.4 s p95 (the time 95% of questions beat) against a 30 s limit, $0.110 per fresh
question (`reports/evals/v2_2026-10-18_0903/summary.md`; [EVALUATION.md](EVALUATION.md) §3.1). Deployed on AWS
at pharmassist.aishwaryabhanage.com (`evidence/live_check_2026-10-18.log`, `evidence/screenshots/`);
runs locally with one Docker command ([SOLUTION.md](SOLUTION.md)). Eight answers verbatim with the judge's
verdicts: [EXAMPLES.md](EXAMPLES.md). Nothing below is estimated unless it says so.

**Where each topic is.** Brief and scope §1 · Architecture and corpus
representation "Architecture" · Decisions and tradeoffs §2 · Question handling "Question handling" · Risks and
failure modes §3 · Quality measurement "Quality" · Production metrics and alerts §4 · Tests and acceptance
criteria §5 · Continuous improvement "Continuous improvement" · Output shapes "Output shape" · AI usage §6 ·
Runtime model and cost §7 · Optimization idea §7 ("Cut cost 10×", "Cut latency 2×") · Cuts and next steps
"What we cut", "What we'd build next".

## 1. Brief

**Intent.** A pharmacist or technician types one question ("is Ozempic preferred on NY Medicaid, and does it
need PA?") and gets a 60–120-word cited answer. The alternative today is reading the manual.

**Target user.** Pharmacy staff who know the acronyms. Roles: `staff` ask and rate; `admin` see every
conversation, manage documents, watch spend (`app/auth.py`, `app/admin.py`).

**Scoped outcomes** (`REQUIREMENTS.md`): one question in, one answer out, no clarifying questions; the program
inferred and the assumption stated first; conflicts decided by a fixed precedence rule the answer names;
numbered steps for processes, a small table for coverage; every answer cited, or exactly
`No answer found in knowledge base`; under 30 s.

**Not solved.** Multi-turn chat; patient-specific advice (the composer says "No patient information");
documents outside the corpus; live payer systems. Non-pharmacy questions, including ones about an uploaded
document, are declined by design via the prompt's `out_of_scope` status (`docs/PROMPTS.md`).

## 2. Key decisions and tradeoffs

| Decision | Chosen | Alternative, and why rejected |
|---|---|---|
| Model | `gpt-5.5` first, `claude-sonnet-5-5` on failure (`src/pharmassist/llm/router.py`) | Sonnet-only (v1): 0.925 with the reranker, 0.85 without, same as gpt-5.5 (EVALUATION.md §3.1). OpenAI as the primary provider was a project constraint |
| Agent vs pipeline | Tool loop, at most 6 lookups, 25 s deadline (`src/pharmassist/agent/loop.py`) | A fixed retrieve-then-generate pipeline (v1) cannot decide that a question needs a formulary row, policy text and a second search |
| Retrieval unit | Child chunks (350 tokens) matched, parent sections (≤ 1,500 tokens) returned; exact table rows; interpreted figures | Fixed 350-token chunks: Recall@10 0.713 vs 0.833, same embedder (EVALUATION.md §3.4) |
| Search | pgvector (Postgres extension for embeddings) + Postgres full-text, fused with RRF (reciprocal rank fusion) (`src/pharmassist/search/hybrid.py`) | Pinecone + BM25 files (v1): identical recall in a parity test, one more vendor |
| Reranker | Off | `bge-reranker-large`: 19 s per search on CPU, 5 answers over 30 s; `bge-reranker-base`: 0.70 vs 0.85 without (EVALUATION.md §4.2) |
| Answer checking | Live: a citation must point at a page or row a tool returned this request, else no answer. Everything else offline | A live claim-by-claim gate: accuracy 0.875 → 0.300, abstaining on 13 of 19 answerable questions (EVALUATION.md §4.3) |
| Cache | Valkey; cosine ≥ 0.90 returns the stored answer and citations; dropped on index change (`src/pharmassist/cache/valkey.py`) | Exact-string cache never hits on pharmacist phrasing; a lower threshold conflates "max dose" with "starting dose" (paraphrases 0.86–0.89, `docs/CACHE.md`) |
| Store | One PostgreSQL 16 database for everything persistent (`src/pharmassist/store/pg.py`) | DynamoDB + Pinecone + S3 index files (v1): three consistency stories for one corpus |
| Ingestion | Upload → S3 → SQS → Fargate worker, one task kept warm (`WorkerMinCount`, `deploy/aws/v2/template.yaml`) | Scale-to-zero saved ≈ $144/month but an upload waited for a cold start: 15 s to active (`evidence/live_check_2026-10-18.log`) vs 5 s warm (production run 2026-10-18, admin API) |

Prompt stance (`docs/PROMPTS.md`): answer only from returned text; state the program assumption; apply the
precedence rule and name it; distinguish "covered but silent on X" from "not in the documents".

## 3. Risks and failure modes

- **Unsupported claims.** 3 of 20 golden answers held a claim the judge could not support (`v2_2026-10-18_0903/summary.md`).
  Flowchart answers are right but score low (visual groundedness 0.614): the judge sees the cited page's text,
  which for an image page is a heading (EVALUATION.md §4.5).
- **Effective dates.** The NY PDL prints future changes; Q15 stated a 10/22/2026 status as current (`v2_2026-10-18_0903/results.csv`).
- **Cache false positives.** A 0.90 match returns another question's answer. The hit shows the matched
  question; entries die with the index generation; admins can clear the cache (`docs/CACHE.md`).
- **Latency.** p95 21.4 s against 30 s. Each model call gets only the time remaining; a timeout falls back to Sonnet (`src/pharmassist/agent/loop.py`).
- **Cost.** $0.015–0.38 per question (Q11 vs Q07, `traces/`). Caps: 10/min and 100/day per user, 500/day
  global, $10/day spend (`config.yaml` `limits_v2`); WAF 300 requests per 5 min per IP (`deploy/aws/v2/template.yaml`).
- **Prompt injection through documents.** Uploaded text is evidence the model reads. Containment: read-only
  tools, admin-only type-sniffed uploads, a markdown sanitizer, citations checked in code (`src/pharmassist/agent/tools.py`).
- **Unsafe output.** Guidance is quoted, not generated; the remaining risk is omission (Q06, EXAMPLES.md).
- **Silent failures.** Fallback is flagged; failed ingestion lands in a dead-letter queue with the error in the
  admin UI; `/health/ready` checks Postgres, Valkey, S3. Two slipped through and were fixed: a health banner
  that never cleared; a scanned PDF failing at chunking (`src/pharmassist/chunkers/sections.py`).
- **Deployment.** Five stack-creation attempts, one IAM gap each; `deploy/aws/v2/bootstrap.sh` now pre-creates the roles.
- **Privacy.** LangSmith receives question and answer text (`tracing_v2.content: full`, `config.yaml`); `metadata` mode is one setting.

## 4. Key metrics and alert triggers

| Metric | Today (source) | Alert when |
|---|---|---|
| Latency p50 / p95, uncached | 10.8 / 21.4 s golden; 6.5 / 6.9 s visual (`v2_2026-10-18_0903`, `v2_visual_2026-10-18_0916`) | p95 > 25 s over 15 min, or > 2% over 30 s in 5 min |
| Cache-hit latency | 0.4 s (`evidence/live_check_2026-10-18.log`) | p95 > 2 s |
| Cost per uncached question | $0.110 mean (`v2_2026-10-18_0903/summary.md`) | daily spend > 70% of the $10 cap before 18:00 |
| Accuracy (judge, golden) | 0.85 (14 correct / 6 partial / 0 incorrect) | < 0.80, or any `incorrect` |
| Groundedness | 0.937 golden, 0.614 visual | < 0.90 golden |
| Safe (no unsupported claim shown) | 17/20 | < 16/20 |
| No-answer rate | 3 of 13 in the live session, which included off-corpus tests (live-check log) | > 25% in a day |
| Fallback rate | 0 in the live session | > 10% in an hour |
| Errors (5xx, timeouts) | 0 over 30 s in both eval runs | > 1% in 5 min |
| Unhelpful ratings | 0 of 3 (live-check log) | > 30% of rated answers in a week |
| Ingestion | upload → active in 15 s cold (live-check log), 5 s warm (production run 2026-10-18) | any dead-letter message; a job older than 30 min |

Sources: LangSmith project `pharmassist` (one run per answer), `GET /api/v1/admin/stats`,
CloudWatch. Metric definitions: [EVALUATION.md](EVALUATION.md) §2.

## 5. Test plan / acceptance criteria

**Today.** 657 tests collected by `pytest`: 600 run with no network (providers, Valkey, S3, SQS faked), 57
integration tests against the docker-compose Postgres and Valkey; 28 frontend tests (Vitest + MSW)
(`pytest --collect-only -q`; `frontend/src/test/`). Covered: tool cap and deadline, citation
check, no-answer rule, fallback with a fault-injected client, cache, auth, roles, limits, remove-from-index
(`tests/test_admin.py`), scanned-PDF chunking (`tests/test_ingest_pipeline.py`), ingestion end to end.

**Acceptance (`scripts/run_eval.py`).** Golden accuracy ≥ 0.85 with 0 incorrect; Q20 returns the exact no-answer
sentence; 0 questions over 30 s; 0 answers without citations; 0 citations failing the in-code check; ≥ 18/20
answers within 60–120 words. The production run meets all of them, 19/20 on length
(`v2_2026-10-18_0903/summary.md`). Live: `evidence/live_check_2026-10-18.log` ends ALL PASS.

**Regression as models or the corpus change.** Model ids pinned in `config.yaml`; every run writes `meta.json`
with dataset and prompt hashes and the commit; `--rejudge` re-scores saved answers under one judge; failure
classes say which layer moved. A model change re-runs both sets (≈ $5 + $1.25 with the judge) and ships only
if the acceptance table holds; a corpus change bumps the index generation and re-runs the judge-free Recall@k
check. Not built: the CI job doing this on every merge. Commands and frozen hashes: [EVALUATION.md](EVALUATION.md) §6.

## 6. AI usage

Built with Claude Code (Claude Fable 5.1) as an orchestrator over parallel subagents in git worktrees: seven
streams for v2 (data, llm, api, cache, ingest, frontend, infra) against shared contracts, then an integration
pass. The AI wrote the code, tests, documentation, prompts and the evaluation harness; I set the scope, made
the product and cost decisions (instance sizing, reranker off after seeing the numbers, the 0.90 threshold, the
warm worker), reviewed every merge, and ran the admin-only AWS and DNS steps. What failed: the frontend and its
test mocks shared a wrong health path, so tests passed while the live banner was wrong; the ingestion image
lacked a dependency that only showed in the real container; five IAM gaps, one per deploy attempt. Each was
found by running the real thing, not by review.

## 7. Tool selection

Runtime models (`config.yaml`, `llm:`):

| Call | Model | Price per Mtok | Where |
|---|---|---|---|
| Agent, primary | `gpt-5.5`, effort medium | $5 in / $0.50 cached / $30 out | every uncached question |
| Agent, fallback | `claude-sonnet-5-5` | $2 / $0.20 / $10 | transport error, 5xx, exhausted retries, timeout |
| Embeddings | `text-embedding-3-large`, 3,072-d | $0.13 | one per question; ingestion |
| Judge, offline | `claude-opus-5-5`, 3 passes | $4 / $20 | evaluations only |
| Figures, offline | `claude-opus-5-5` vision | $4 / $20 | once per non-decorative image at ingestion |

Cost per run, from the 20 golden traces (`traces/`, run `v2_2026-10-18_0903`):

| Per question | Tokens | Price | USD |
|---|---|---|---|
| Uncached input | 16,748 | $5 / Mtok | 0.084 |
| Cached input | 11,827 | $0.50 / Mtok | 0.006 |
| Output incl. reasoning | 682 | $30 / Mtok | 0.020 |
| Question embedding | ≈ 30 | $0.13 / Mtok | < 0.001 |
| **Mean** | | | **0.110** |

Range $0.015 (Q11: one lookup, 1,085 input tokens) to $0.382 (Q07: four searches, 63,935 input tokens). A cache
hit costs the embedding only. Infrastructure: ≈ $197/month always on plus ≈ $144/month for the warm ingestion
task (`deploy/aws/v2/README.md` "Cost"; `deploy/aws/v2/template.yaml` `WorkerMinCount`).

**Cut cost 10×.** Uncached input is 76% of the bill, mostly parent sections (≤ 1,500 tokens, up to 20 per
search). Return the matched child and let the model `read_page` for the rest: about 4× fewer input tokens. Then
answer short coverage questions (Q11, Q12: under 2,000 input tokens) with the fallback model at effort low,
2.5× cheaper per token. Config plus a tool-result formatter; not measured.

**Cut latency 2×.** The median question makes 2–3 sequential model turns. Run the search and both drug lookups
on the original question before the first model call and put the results in the first prompt, so two-turn
questions need one. Q11 (one turn) took 5.2 s against the 10.8 s median (`v2_2026-10-18_0903/summary.md`).

## What we cut

Titan embeddings and the CI feedback loop ("later" in `REQUIREMENTS.md`); a Playwright smoke test; the reranker
(measured, off); per-claim citations; a selective gate on high-risk fields; multi-turn follow-ups; a recorded
forced-fallback eval (covered by tests with a fault-injected client); effective dates as a field on PDL rows.

## What we'd build next

1. Figure-derived answers: give the groundedness judge the figure interpretation for cited figure pages; cite
   the figure plus the appendix page where the algorithm is printed as text.
2. Effective dates on PDL rows, so "preferred as of 10/22/2026" is never stated as current.
3. The selective gate, measured against the 0.300 lesson: block only unsupported numbers and codes.
4. A nightly eval job posting the acceptance table; unhelpful ratings feeding the golden set.
5. The two §7 ideas, measured.
6. **Amazon Titan embeddings on Bedrock** (the "later" item in `REQUIREMENTS.md`): re-run the retrieval
   experiment of EVALUATION.md §3.4 with `amazon.titan-embed-text-v2` beside `text-embedding-3-large`, same
   frozen set and Recall@10, and keep whichever wins; it also keeps embeddings inside the AWS account.
7. **Evaluating the agent's tool decisions**: today the judge grades the answer only. Add a per-question
   check of which tools were called, in what order, against the tools the gold pages imply (table row versus
   section, one search versus two), so a wrong route is counted even when the answer happens to be right, and
   use it to tune the tool descriptions and the lookup budget.
8. **HIPAA readiness and PII handling.** The product takes no patient data by design (the composer says "No
   patient information"), but staff will paste it. Next: a PII/PHI detector on the question before it reaches
   a model or LangSmith (redact names, dates of birth, member ids; keep drug and program terms), tracing in
   `metadata` mode by default, a Business Associate Agreement with the model providers or Bedrock-hosted
   models so PHI never leaves the account, encryption at rest and in transit (already KMS and TLS), access
   logging per user and a retention period on conversations. None of this is measured; the detector is a
   small model call or a rules pass and should be evaluated for recall on a synthetic PHI set first.
9. **Retrieval beyond the fused search.** Query rewriting is not on the served path; the only rewriting today
   is the agent's own search query fused with the original question (+0.075 accuracy, EVALUATION.md §3.1).
   Candidates to measure with the retrieval harness: multi-query expansion (program and drug synonyms),
   step-back queries for process questions, HyDE (embedding a hypothetical answer), and a small cross-encoder
   on a GPU so the reranker that scored 0.925 fits the 30 s rule. Each is a config flag plus one run, and ships
   only if Recall@10 and golden accuracy both move.

## Architecture

**Retrieval unit and why.** The corpus is 11 documents stored as 1,983 child chunks, 589 parent sections, 50
interpreted figures and 3,520 table rows in PostgreSQL (`scripts/seed_local.py`). **The retrieval unit is the
child chunk; the delivery unit is the parent section.** Children (350 tokens, 100 overlap, prefixed with the
heading path such as "4.2 Prior Authorization > Refills") match precisely in dense and full-text search; the
parent (≤ 1,500 tokens) is what the model reads, so a rule arrives with its conditions and every page it spans
is citable. The retrieval experiment decided it: Recall@10 0.713 on fixed chunks, 0.833 on sections, same
embedder, equal token budgets (`reports/retrieval/2026-10-16_0121/results.md`; EVALUATION.md §3.4).

**Two kinds of content do not fit chunks.** Formulary and PDL rows live in `table_rows`, served by
`lookup_va_formulary` and `lookup_ny_medicaid_drug` with fuzzy names and explicit outcomes (`no_matching_row`
never means "not covered"); they exist because drug-specific PA questions ranked generic PA prose above the row
that answered them. Figures are inventoried from the PDF, interpreted once by a vision model into boxes and
labelled arrows, checked against an independent OCR, and chunked as complete decision paths
(`reports/parsing/VISUAL_EXTRACTION.md`); the visual set scores 1.0 because of it
(`reports/evals/v2_visual_2026-10-18_0916/summary.md`).

**Preprocessing facts that shaped the design.** The VA/DoD algorithm flowcharts are raster images (diabetes
pp. 21–22, opioids pp. 25–27) no text extractor sees; the appendices print the same algorithms as text. The NYRx
manual's table of contents is broken, so headings are found by bold font plus "N.0" numbering. NY PDL rows come
from a fixed-column extractor that reads the 6.96 pt effective-date markers by font size
(`src/pharmassist/tables/ny_pdl.py`); all 1,522 rows were checked against the PDF (`tests/test_ny_pdl.py`).

**Data model and search.** One PostgreSQL 16 database (`src/pharmassist/store/pg.py`): `documents` and
`document_versions` (status from `queued` through `parsing`, `chunking` and `embedding` to `active`), `chunks`
(`halfvec(3072)` embedding under an HNSW index, `tsvector` under a GIN index), `parents`, `figures`,
`table_rows`, `ingestion_jobs`, plus users, conversations, feedback and usage. Search reads only `active`
versions; activating a new version supersedes the old one in the same transaction and bumps the generation
that invalidates the cache. Each search runs the agent's query and the original question concurrently and
fuses them (+0.075 accuracy, EVALUATION.md §3.1, Oct 17 row). Summaries, concept articles and a graph were not
built: these questions are answered by specific sections and rows, and a generated layer is one more thing to
keep grounded.

## Question handling

**Synthesis across sources.** The agent may make up to six lookups; each search runs the agent's query and the
original question and fuses them; what it reads is the parent section, so a rule arrives with its conditions.
Q03 combines four documents and a formulary row and is graded correct; Q07 (continue, split, monitor) is graded
partial for one over-reach and one omission, and synthesis is the shape where the six partial answers
concentrate (EXAMPLES.md "The six partial answers").

**Structured lookups.** Drug-specific questions go to `lookup_va_formulary` and `lookup_ny_medicaid_drug`, which
read exact rows from `table_rows` with fuzzy name matching and explicit outcomes; `no_matching_row` is reported
as such and never turned into "not covered". Q08 (claim code and conditions), Q16 (reject 22, DAW 9) and Q17
(status changes on a date, as a table) are graded correct.

**Missing evidence.** Two cases are kept apart. *Covered but silent*: the documents address the topic but not
the detail; the answer says so and gives what they do say (Q09: no code named for the 90-MME alert; Q19: no copay
tiers, but a $1.00 copay). *Absent*: nothing relevant is retrieved, the agent returns `no_answer`, and the API
returns exactly `No answer found in knowledge base` (Q20). The code path enforces the second case regardless of
what the model writes (see "Quality").

**Conflicts.** The prompt fixes the precedence order (`docs/PROMPTS.md`): match the program; state over federal
when both apply; for coverage, binding policy over advisory guidance, for clinical questions the guidelines;
more recent over older. The answer names the rule it applied and gives the other document one line (Q02: the
2025 guide over the 2020 guide; Q04). Different programs are not a conflict (Q12: VA formulary versus NYRx). Every
answer records what it reconciled in a `conflicts_noted` field, stored with the conversation.

## Quality

**Groundedness** is measured offline: a Claude Opus judge splits each answer into claims and checks each against
the text of the cited pages and rows only, three passes, median taken (`src/pharmassist/eval/judge.py`;
`docs/PROMPTS.md` §2). Reported as supported claims / claims (0.937) and as Safe, answers with zero unsupported
claims (17/20) (`v2_2026-10-18_0903/summary.md`). A second, independent scorer (DeepEval, judge
`claude-sonnet-5-5`, `scripts/deepeval_score.py`) ranks the versions the same way and scores groundedness
0.98–1.0 everywhere because it penalises contradiction, not missing support (EVALUATION.md §3.2); the harness
numbers are the strict ones.

**Hallucination when the corpus is silent** has three detectors. In code: an answer is returned only when the
agent's status is `answered` and at least one citation points at a page or row a tool returned in this request;
anything else becomes the fixed sentence and is never cached (`app/answer_service.py`,
`src/pharmassist/agent/loop.py`). In the prompt: silence versus absence is explicit; Q09 and Q19 test it and are
graded correct (EXAMPLES.md). Offline: deterministic checks on values, dates, phone numbers and row status
(`src/pharmassist/agent/verify.py`) plus the judge's unsupported-claim list. The live gate was measured and
removed (0.300 vs 0.875, EVALUATION.md §4.3): it abstained on answerable questions far more often than it
caught a fabrication.

**Regression testing** is §5. Two answer-side improvements were measured under its rule and left off because
accuracy did not rise (EVALUATION.md §4.5).

## Continuous improvement

Built: staff rate answers with a reason and comment; admins filter conversations by rating, user, date and text
and see answer, citations, model and cost (`app/admin.py`, `frontend/src/pages/admin/ConversationsPage.tsx`);
every eval classifies each miss by layer; a new document version supersedes the old in one transaction and
drops the cache; an admin can remove a document from the index while keeping its file for re-indexing
(`DELETE /api/v1/admin/documents/{id}/index`, `app/admin.py`). Verified in production on
2026-10-18 through the admin API: an upload was indexed 5 s after submission, remove-from-index returned 200
with the removed counts, a question about the document then returned the no-answer sentence, re-indexing took
5 s and the question was answerable again.

Found in the corpus, not yet surfaced in the UI: the NY PDL gives the opioid PA threshold as "≥ 90 MME" in
class rows and "> 90 MME" in the fentanyl row; the 2020 and 2025 VA guides disagree on continuing a DPP-4 when
prandial insulin starts (Q02 applies the rule and names it, EXAMPLES.md).

Next: aggregate the `conflicts_noted` field the agent fills on every answer by document pair into a weekly
inconsistency list; cluster no-answer questions and unhelpful ratings by embedding into a gap list, each
cluster a candidate golden question and a document to upload. The clustering job is not built.

## Output shape

Shipped: an assumption banner when the program was inferred; numbered steps for processes (Q05, Q08, Q13) and
a table for status changes (Q17), rendered from sanitized markdown (EXAMPLES.md); citations as document title
plus page, opening the source PDF at that page, with the figure crop and interpretation when the page has one
(`frontend/src/components/ask/CitationList.tsx`, `FigureNote.tsx`; `evidence/screenshots/citation-source.png`);
badges for cached (with the matched question) and fallback model.

Would help more than prose: a fixed coverage card for drug questions (status, PA, QL, ST, effective date,
copay) filled from the table row so no field is silently missing; the answer's path drawn on the flowchart
crop; a claim-ready block for reject-code answers (field, value, condition); a "what changes on date X" view
for PDL updates.
