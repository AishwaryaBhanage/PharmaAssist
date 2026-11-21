# Eval: v2, 2026-10-18 09:03

- Agent: `gpt-5.5 (fallback claude-sonnet-5-5)` (effort medium), index setup `v2`, max 6 lookups, 25 s deadline
- Judge: `claude-opus-5-5` (effort medium, 3 passes)
- Golden set: `evals/golden.jsonl`, 20 questions, each run once
- Code: commit `a114ef9`
- Run date: 2026-10-18 09:03; per-question results in `results.csv`

## Results

| Metric | Result |
|---|---|
| Accuracy (judge) | 14 correct, 6 partial, 0 incorrect (score 0.85, partial = 0.5) |
| Judge passes unanimous on the grade | 18/20 |
| must_include terms present (judge, paraphrase counts) | 52/54 |
| must_include terms present (literal substring) | 21/54 |
| Recall@5 / @10 (direct hybrid search on the question, PDF gold) | 0.636 / 0.768 |
| Retrieval recall: all gold / PDF pages only (mean, any tool) | 0.931 / 0.939 |
| Gold sources returned by any tool (all questions) | 53/59 |
| Citation precision / recall: all gold (mean) | 0.743 / 0.793 |
| Citation recall: PDF pages only (mean) | 0.834 |
| Citations failing the in-code check | 0 |
| Groundedness (supported claims / claims, mean) | 0.937 |
| Answered without citations | 0 |
| **Safe**: no unsupported content shown (judge found 0 unsupported claims, or abstained) | 17/20 |
| **Useful**: answerable questions that received a non-abstaining answer | 19/19 |
| Over-abstention (abstained or unverified on an answerable question; graded incorrect) | 0 |
| Abstention correct | 20/20 |
| Opens with the assumption (unspecified program) | 4/4 |
| Startup warmup before timing (not in any latency) | 0.349 s (store 0.001 s, tables 0.341 s, search 0.007 s) |
| Latency, all | p50 10.79 s, p95 21.43 s (n=20) |
| Latency, cold (index not yet loaded) | p50 10.79 s, p95 21.43 s (n=20) |
| Latency, warm | none |
| Over 30 s | 0 |
| Rendered length incl. citations, words (mean / median / max) | 83.95 / 88.0 / 113 |
| Displayed content, words excl. labels and citations (mean; in 60-120) | 83.95; 19/20 |
| Needs review (not answered, uncited or a flagged citation) | 1 |
| Flags | budget_spent:tool_cap 1 |
| Failures by class | ingested but not retrieved 3, retrieved but answered wrong 3, answered right but cited wrong 5 |
| Cost | agent $2.20 ($0.110/question), judge $2.61, total $4.81 |

## Per question

| ID | Accuracy | Grounded | R@10 | Retrieval | Cite P / R | Abst. | Assum. | Time s | Words | Cost $ | Failure class |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Q01 | partial | 1.0 | 1.0 | 1.0 | 0.6 / 0.6 | True | – | 10.8 | 96 | 0.234 | retrieved but answered wrong |
| Q02 | correct | 1.0 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 14.8 | 76 | 0.251 | – |
| Q03 | correct | 1.0 | 1.0 | 0.857 | 1.0 / 0.714 | True | – | 21.6 | 100 | 0.353 | answered right but cited wrong |
| Q04 | correct | 1.0 | 0.5 | 0.667 | 0.8 / 0.667 | True | – | 12.2 | 112 | 0.354 | answered right but cited wrong |
| Q05 | correct | 0.875 | 1.0 | 1.0 | 0.8 / 1.0 | True | – | 12.0 | 113 | 0.298 | – |
| Q06 | partial | 1.0 | 0.5 | 0.75 | 0.75 / 0.75 | True | – | 10.9 | 82 | 0.243 | ingested but not retrieved |
| Q07 | partial | 1.0 | 0.25 | 0.75 | 0.667 / 0.5 | True | – | 14.6 | 94 | 0.544 | ingested but not retrieved |
| Q08 | correct | 0.833 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 7.2 | 90 | 0.156 | – |
| Q09 | correct | 1.0 | 1.0 | 1.0 | 0.5 / 1.0 | True | – | 12.8 | 84 | 0.314 | – |
| Q10 | partial | 1.0 | 0.333 | 0.667 | 0.5 / 0.667 | True | – | 10.8 | 89 | 0.305 | ingested but not retrieved |
| Q11 | correct | 1.0 | 1.0 | 1.0 | 0.5 / 1.0 | True | True | 5.2 | 78 | 0.112 | – |
| Q12 | correct | 0.833 | 1.0 | 1.0 | 1.0 / 0.5 | True | – | 8.7 | 87 | 0.129 | answered right but cited wrong |
| Q13 | partial | 1.0 | 0.667 | 1.0 | 0.667 / 0.667 | True | – | 9.1 | 96 | 0.187 | retrieved but answered wrong |
| Q14 | correct | 0.857 | 0.333 | 1.0 | 0.333 / 0.333 | True | True | 9.8 | 90 | 0.214 | answered right but cited wrong |
| Q15 | correct | 0.6 | 0.5 | 1.0 | 1.0 / 1.0 | True | – | 10.3 | 82 | 0.196 | – |
| Q16 | correct | 1.0 | 1.0 | 1.0 | 0.667 / 1.0 | True | True | 9.1 | 91 | 0.193 | – |
| Q17 | correct | 1.0 | 1.0 | 1.0 | 0.667 / 1.0 | True | – | 21.4 | 64 | 0.257 | – |
| Q18 | partial | 1.0 | 0.5 | 1.0 | 0.667 / 1.0 | True | True | 11.0 | 86 | 0.203 | retrieved but answered wrong |
| Q19 | correct | 0.8 | 1.0 | 1.0 | 1.0 / 0.667 | True | – | 7.2 | 63 | 0.148 | answered right but cited wrong |
| Q20 | correct | n/a | – | – | – / – | True | – | 10.2 | 6 | 0.124 | – |

## Lowest-scoring questions

Ranked by accuracy, then groundedness, citation recall and retrieval recall.

- **Q07** (synthesis): partial [ingested but not retrieved], groundedness 1.0, citation recall 0.5, retrieval 0.75
  - Judge: Covers continuation, BID/TID splitting and monitoring, but claims BUP/NX may be preferred for pain, contradicting the reference's insufficient-evidence point; also omits monitoring frequency.
- **Q01** (conflict across versions; synthesis): partial [retrieved but answered wrong], groundedness 1.0, citation recall 0.6, retrieval 1.0
  - Judge: Correct conclusion with SGLT2 first-line regardless of A1c and agents named, but omits the older 2020 metformin-first sequence conflict and the coverage caveat.
  - Missing terms: older guide metformin-first
- **Q10** (apparent conflict; document purpose): partial [ingested but not retrieved], groundedness 1.0, citation recall 0.667, retrieval 0.667
  - Judge: Correctly applies the CPG against initiation and treats the dosing table as non-directive, but omits PBM's stated preference for non-opioid and non-pharmacologic care.
  - Missing terms: non-opioid preference
- **Q13** (prior auth process): partial [retrieved but answered wrong], groundedness 1.0, citation recall 0.667, retrieval 1.0
  - Judge: Gives prescriber-only rule, call center number, CoverMyMeds, and 72-hour supply, but omits PAXpress and gives a different fax-form URL instead of the Standardized PDF.
- **Q06** (multi-document; structured formulary): partial [ingested but not retrieved], groundedness 1.0, citation recall 0.75, retrieval 0.75
  - Judge: Correct PA requirement and billing order, but omits the VA guidance to avoid the combination and the recommendation for a pharmacist medication review.

## Random sample the judge marked correct

To check the judge isn't too lenient (sample seed 7007).

- **Q15** (step therapy): correct, groundedness 0.6, citation recall 1.0, retrieval 1.0
  - Judge: States IR tramadol first for ConZip/tramadol ER (non-preferred, ST), tramadol tablet preferred, and opioid-naïve PA; omits minor 4-Rx/30-day and under-12 PA details.
  - Not fully supported: On NY Medicaid, tramadol ER is non-preferred. (partial: The PDL lists tramadol ER as non-preferred only as of 10/22/2026, which is after today (2026-10-18). The answer presents this as current status without that effective date.) \| Tramadol tablet is listed as preferred in the Opioids – Short-Acting class. (partial: Tramadol tablet is preferred as of 10/22/2026, which is not yet in effect. The page also lists tramadol 25mg and 75mg tablets as non-preferred, and the answer omits this.)
- **Q14** (quantity limit): correct [answered right but cited wrong], groundedness 0.857, citation recall 0.333, retrieval 1.0
  - Judge: Assumes NY Medicaid, says no Ozempic QL listed, and notes preferred status with clinical criteria and DPP-4 PA. It omits the Wegovy distinction and phone number, which are minor.
  - Not fully supported: Claim messaging should guide the pharmacy on F/Q/D edits, and questions can go to the Clinical Call Center. (unsupported: No cited page mentions claim messaging for F/Q/D edits or a Clinical Call Center.)
- **Q09** (silence vs absence): correct, groundedness 1.0, citation recall 1.0, retrieval 1.0
  - Judge: States no code specified, describes consult/document/submit override process, directs to plan instructions; 569 clarification doesn't contradict reference.

## Caveats

- **The judge is also a Claude model**, so it may share the agent's blind spots. Human spot checks of its grades (the two lists above) are the safeguard.
- **Each question ran once.** The agent isn't deterministic, so a one-question difference between setups may be noise.
- **VA formulary gold** (6 spreadsheet rows, from cells such as A1697:G1697) counts in the all-gold scores; a setup without the formulary lookup can't reach it, so compare setups on the PDF-pages-only scores too. Recall@k covers PDF pages only.
- **Failure classes are assigned by rule** (earliest stage that explains the miss), with ambiguous cases set by hand in `evals/failure_overrides.yaml`.
- **Citation precision is a lower bound**: a correct citation to a page outside the gold set counts against it. Read it together with groundedness.
- **Cold latency has n=20**: in one process only the first question loads the index, so the cold p95 is not a real percentile.
