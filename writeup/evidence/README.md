# Evidence it works end to end

> Code and report paths are relative to the [repository root](../../).

**In 20 seconds.** PharmAssist was deployed on AWS at pharmassist.aishwaryabhanage.com (the stack is not kept running). On 2026-10-18 an API
transcript against production passed every check (login, cited answer, cache hit in 0.4 s, exact no-answer
sentence, role enforcement, upload indexed in 15 s and answerable; [`live_check_2026-10-18.log`](live_check_2026-10-18.log),
ends `ALL PASS`), seven screenshots of the deployed app were taken ([`screenshots/`](screenshots/)), and the
evaluation runs behind every number in the write-ups are checked in under `../reports/`. One line per item below.

## Index

| Item | Where | What it shows |
|---|---|---|
| Production API transcript, 2026-10-18 | [`live_check_2026-10-18.log`](live_check_2026-10-18.log) | 17 PASS lines, one INFO line (the uncached paraphrase), `ALL PASS`; no passwords or tokens logged (status codes and response fields only) |
| Ask page with a question and its answer | [`screenshots/ask-question-answer.png`](screenshots/ask-question-answer.png) | "Got reject 22 on a Victoza claim, what now?": assumption banner (NY Medicaid), four numbered steps (bill brand Victoza, resubmit with DAW 9), `Cached · gpt-5.5 · 0.3 s` because the question had been asked before, three citations to the NYRx PDL pp. 34, 77, 78, feedback bar, conversation sidebar |
| A cited answer | [`screenshots/ask-answer.png`](screenshots/ask-answer.png) | "Is Trulicity preferred under NY Medicaid?": preferred in the GLP-1 class, PA rule, `openai · gpt-5.5-2026-04-23 · 5.1 s`, one citation to the NYRx PDL p34, feedback bar |
| The citation opened | [`screenshots/citation-source.png`](screenshots/citation-source.png) | the stored NYRx PDL at page 34 of 86, Trulicity in the Preferred Drugs column |
| The no-answer rule | [`screenshots/ask-no-answer.png`](screenshots/ask-no-answer.png) | "What is the capital of France?" → "No answer found in knowledge base", 1.7 s |
| Admin overview | [`screenshots/admin-overview.png`](screenshots/admin-overview.png) | 30-day tiles (8 questions, 88% answered, 0 fallback, p50/p95 5.8 s / 8.8 s, spend today $0.13 of the $10 cap, 11 active documents), questions-per-day chart, semantic-cache card with Clear cache |
| Admin conversations | [`screenshots/admin-conversations.png`](screenshots/admin-conversations.png) | filters (text, rating, status, cached, user, date) and every question with user, status, rating, latency |
| Admin documents | [`screenshots/admin-documents.png`](screenshots/admin-documents.png) | the corpus table (title, publisher link, program, authority, Active status), Upload button, indexing-jobs panel |
| Eight Q/A pairs verbatim, three weak ones explained | [`../EXAMPLES.md`](../EXAMPLES.md) | copied from `../reports/evals/v2_2026-10-18_0903/results.csv` and `v2_visual_2026-10-18_0916/results.csv` with the judge's grade and reason |
| Every evaluation run, baseline to production | `../reports/evals/<run>/` (`summary.md`, `results.csv`, `meta.json`); read with [`../EVALUATION.md`](../EVALUATION.md) §3 | accuracy, groundedness, Safe, latency, cost per run; the v2 production runs are `v2_2026-10-18_0903` and `v2_visual_2026-10-18_0916` |
| Per-question traces of the milestone runs | `../traces/` | model turns, tool calls and results, citations, timings, tokens |
| Second, independent scorer | `../reports/deepeval/<run>/deepeval.json` | DeepEval scores for ten runs ([`../EVALUATION.md`](../EVALUATION.md) §3.2) |
| Retrieval-only experiments | `../reports/retrieval/*/results.md` | Recall@k by chunking unit, embedder and reranker ([`../EVALUATION.md`](../EVALUATION.md) §3.4) |
| Parsing and figure extraction | `../reports/parsing/VISUAL_EXTRACTION.md` | what the vision pass read from flowcharts and how it was checked |
| Document lifecycle on production, 2026-10-18 | production run through the admin API; not a checked-in log | upload indexed 5 s after submission with the warm worker; `DELETE /api/v1/admin/documents/{id}/index` returned 200 with the removed counts; a question about the document then returned the no-answer sentence; re-index took 5 s and the question was answerable again |
| LangSmith traces | project `pharmassist` | one run per answer with child runs per model call, tool call and retrieval; access by invitation, not checked in |

## Reading the live-check log

The log was produced against production with the seeded `staff1` and `admin` accounts. Lines worth knowing:
`ask (fresh)` came back `cached=True` because the script's "fresh" question had already been asked earlier in
the session (the cache stats line counts 6 hits); the uncached path is the `paraphrase` line, 18.6 s on `gpt-5.5`,
which misses the 0.90 cache threshold by design. `admin/stats` shows 13 questions, 10 answered, 3 no-answer
(off-corpus tests included), 6 cached, 0 fallback, 3 helpful. `admin/documents` shows 12: the 11-document corpus
plus the live-check upload, which went from accepted (201) to `active` in 15 s with the worker scaling from zero
and was then cited in an answer alongside `ny_medicaid_pdl`.

## About the screenshots

All taken on 2026-10-18 against production with headless Chrome at 1440x900 (2x), light theme, after the
2026-10-18 frontend deploy (single-screen shell, restyled Ask page, Documents page with the Version column and
the Remove from index action). Staff views are signed in as `Staff One` (staff role), admin views as
`Administrator` (admin role).
