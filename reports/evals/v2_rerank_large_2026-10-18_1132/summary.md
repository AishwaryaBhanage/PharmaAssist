# Eval: v2_rerank_large, 2026-10-18 11:32

- Agent: `gpt-5.5 (fallback claude-sonnet-5-5)` (effort medium), index setup `v2_rerank_large`, max 6 lookups, 25 s deadline
- Judge: `claude-opus-5-5` (effort medium, 3 passes)
- Golden set: `evals/golden.jsonl`, 20 questions, each run once
- Code: commit `1443b07` (with uncommitted changes)
- Run date: 2026-10-18 11:32; per-question results in `results.csv`

## Results

| Metric | Result |
|---|---|
| Accuracy (judge) | 9 correct, 5 partial, 0 incorrect, 6 errors (score 0.821, partial = 0.5) |
| Judge passes unanimous on the grade | 11/14 |
| must_include terms present (judge, paraphrase counts) | 36/37 |
| must_include terms present (literal substring) | 18/37 |
| Recall@5 / @10 (direct hybrid search on the question, PDF gold) | 0.764 / 0.851 |
| Retrieval recall: all gold / PDF pages only (mean, any tool) | 0.878 / 0.936 |
| Gold sources returned by any tool (all questions) | 27/33 |
| Citation precision / recall: all gold (mean) | 0.687 / 0.769 |
| Citation recall: PDF pages only (mean) | 0.827 |
| Citations failing the in-code check | 0 |
| Groundedness (supported claims / claims, mean) | 0.857 |
| Answered without citations | 0 |
| **Safe**: no unsupported content shown (judge found 0 unsupported claims, or abstained) | 13/14 |
| **Useful**: answerable questions that received a non-abstaining answer | 13/13 |
| Over-abstention (abstained or unverified on an answerable question; graded incorrect) | 0 |
| Abstention correct | 14/14 |
| Opens with the assumption (unspecified program) | 4/4 |
| Startup warmup before timing (not in any latency) | 0.391 s (store 0.002 s, tables 0.372 s, search 0.017 s) |
| Latency, all | p50 26.53 s, p95 55.1 s (n=14) |
| Latency, cold (index not yet loaded) | p50 26.53 s, p95 55.1 s (n=14) |
| Latency, warm | none |
| Over 30 s | 5 |
| Rendered length incl. citations, words (mean / median / max) | 82.643 / 87.0 / 125 |
| Displayed content, words excl. labels and citations (mean; in 60-120) | 82.643; 12/14 |
| Needs review (not answered, uncited or a flagged citation) | 1 |
| Flags | budget_spent:tool_cap 1, budget_spent:deadline 4 |
| Failures by class | ingested but not retrieved 2, retrieved but answered wrong 3, answered right but cited wrong 4 |
| Cost | agent $0.79 ($0.056/question), judge $1.79, total $2.57 |

## Per question

| ID | Accuracy | Grounded | R@10 | Retrieval | Cite P / R | Abst. | Assum. | Time s | Words | Cost $ | Failure class |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Q01 | error | – | 1.0 | – | – / – | – | – | – | – | 0.000 | – |
| Q02 | correct | 0.333 | 1.0 | 1.0 | 0.5 / 0.5 | True | – | 34.7 | 88 | 0.171 | answered right but cited wrong |
| Q03 | error | – | 0.75 | – | – / – | – | – | – | – | 0.000 | – |
| Q04 | error | – | 0.833 | – | – / – | – | – | – | – | 0.000 | – |
| Q05 | error | – | 1.0 | – | – / – | – | – | – | – | 0.000 | – |
| Q06 | partial | 0.9 | 0.75 | 0.75 | 0.6 / 0.75 | True | – | 61.4 | 125 | 0.222 | ingested but not retrieved |
| Q07 | partial | 1.0 | 0.5 | 0.75 | 0.667 / 0.5 | True | – | 24.9 | 87 | 0.234 | ingested but not retrieved |
| Q08 | correct | 0.833 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 23.9 | 87 | 0.148 | – |
| Q09 | error | – | 1.0 | – | – / – | – | – | – | – | 0.000 | – |
| Q10 | error | – | 0.333 | – | – / – | – | – | – | – | 0.000 | – |
| Q11 | correct | 1.0 | 1.0 | 1.0 | 0.5 / 1.0 | True | True | 7.2 | 86 | 0.123 | – |
| Q12 | correct | 1.0 | 1.0 | 0.25 | 0.5 / 0.25 | True | – | 13.0 | 92 | 0.164 | answered right but cited wrong |
| Q13 | partial | 0.667 | 0.667 | 1.0 | 0.5 / 0.667 | True | – | 51.7 | 93 | 0.224 | retrieved but answered wrong |
| Q14 | correct | 1.0 | 0.333 | 0.667 | 0.667 / 0.667 | True | True | 24.6 | 90 | 0.173 | answered right but cited wrong |
| Q15 | partial | 0.571 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 25.7 | 80 | 0.197 | retrieved but answered wrong |
| Q16 | correct | 1.0 | 1.0 | 1.0 | 0.667 / 1.0 | True | True | 27.2 | 87 | 0.200 | – |
| Q17 | correct | 1.0 | 1.0 | 1.0 | 0.667 / 1.0 | True | – | 48.7 | 78 | 0.182 | – |
| Q18 | partial | 0.833 | 1.0 | 1.0 | 0.667 / 1.0 | True | True | 25.9 | 80 | 0.214 | retrieved but answered wrong |
| Q19 | correct | 1.0 | 1.0 | 1.0 | 1.0 / 0.667 | True | – | 28.7 | 78 | 0.176 | answered right but cited wrong |
| Q20 | correct | n/a | – | – | – / – | True | – | 49.6 | 6 | 0.145 | – |

## Lowest-scoring questions

Ranked by accuracy, then groundedness, citation recall and retrieval recall.

- **Q01** (conflict across versions; synthesis): error, groundedness –, citation recall –, retrieval –
  - Judge: ask: AllProvidersFailed('openai: APITimeoutError; openai: APITimeoutError; anthropic: APITimeoutError')
- **Q03** (apparent conflict; dose vs coverage limit; multi-document): error, groundedness –, citation recall –, retrieval –
  - Judge: ask: AllProvidersFailed('openai: APITimeoutError; openai: APITimeoutError; anthropic: APITimeoutError')
- **Q04** (conflict across dates; screening vs restriction): error, groundedness –, citation recall –, retrieval –
  - Judge: ask: AllProvidersFailed('openai: APITimeoutError; openai: APITimeoutError; anthropic: APITimeoutError')
- **Q05** (multi-document; override and payer coordination): error, groundedness –, citation recall –, retrieval –
  - Judge: ask: AllProvidersFailed('openai: APITimeoutError; openai: APITimeoutError; anthropic: APITimeoutError')
- **Q09** (silence vs absence): error, groundedness –, citation recall –, retrieval –
  - Judge: ask: AllProvidersFailed('openai: APITimeoutError; openai: APITimeoutError; anthropic: APITimeoutError')

## Random sample the judge marked correct

To check the judge isn't too lenient (sample seed 303).

- **Q02** (conflict across versions): correct [answered right but cited wrong], groundedness 0.333, citation recall 0.5, retrieval 1.0
  - Judge: Says flag it, cites the 2025 guide's discontinue-DPP-4 instruction when prandial insulin is started, notes the 2020 handout conflicts, and defers to the pharmacist.
  - Not fully supported: The 2025 VA Clinician's Summary says that when starting prandial insulin, 'Discontinue sulfonylurea, meglitinides, and DPP-4 I.' (unsupported: The cited 2025 page (p8) covers prandial insulin but contains no such quote and says nothing about discontinuing DPP-4 inhibitors, sulfonylureas or meglitinides.) \| The 2025 VA guidance is newer than the 2020 handout, so it should be followed and the DPP-4 should be flagged for reassessment. (partial: The catalog dates confirm the 2025 summary is more recent than the 2020 guide. However, the cited 2025 page shows no conflicting instruction on DPP-4, so applying precedence to override the 2020 'continue DPP-4' advice is not borne out.)
- **Q12** (different programs (not a conflict)): correct [answered right but cited wrong], groundedness 1.0, citation recall 0.25, retrieval 0.25
  - Judge: States Ozempic pen is preferred on NYRx with clinical criteria and the DPP-4 PA rule, tablets non-preferred, and that VA doesn't apply. Omitting VA PA-F detail is minor.
- **Q16** (reject code): correct, groundedness 1.0, citation recall 1.0, retrieval 1.0
  - Judge: States NY Medicaid assumption, reject 22 as missing/invalid DAW, resubmit with DAW 9, and DAW 1 only for Brand Medically Necessary; extra detail doesn't contradict.

## Caveats

- **The judge is also a Claude model**, so it may share the agent's blind spots. Human spot checks of its grades (the two lists above) are the safeguard.
- **Each question ran once.** The agent isn't deterministic, so a one-question difference between setups may be noise.
- **VA formulary gold** (6 spreadsheet rows, from cells such as A1697:G1697) counts in the all-gold scores; a setup without the formulary lookup can't reach it, so compare setups on the PDF-pages-only scores too. Recall@k covers PDF pages only.
- **Failure classes are assigned by rule** (earliest stage that explains the miss), with ambiguous cases set by hand in `evals/failure_overrides.yaml`.
- **Citation precision is a lower bound**: a correct citation to a page outside the gold set counts against it. Read it together with groundedness.
- **Cold latency has n=14**: in one process only the first question loads the index, so the cold p95 is not a real percentile.
