# Eval: v2_complete, 2026-10-18 18:19

- Agent: `gpt-5.5 (fallback claude-sonnet-5-5)` (effort medium), index setup `v2_complete`, max 6 lookups, 25 s deadline
- Judge: `claude-opus-5-5` (effort medium, 3 passes)
- Golden set: `evals/golden.jsonl`, 20 questions, each run once
- Code: commit `59eab45` (with uncommitted changes)
- Run date: 2026-10-18 18:19; per-question results in `results.csv`

## Results

| Metric | Result |
|---|---|
| Accuracy (judge) | 14 correct, 6 partial, 0 incorrect (score 0.85, partial = 0.5) |
| Judge passes unanimous on the grade | 19/20 |
| must_include terms present (judge, paraphrase counts) | 52/54 |
| must_include terms present (literal substring) | 20/54 |
| Recall@5 / @10 (direct hybrid search on the question, PDF gold) | 0.636 / 0.768 |
| Retrieval recall: all gold / PDF pages only (mean, any tool) | 0.925 / 0.925 |
| Gold sources returned by any tool (all questions) | 53/59 |
| Citation precision / recall: all gold (mean) | 0.631 / 0.815 |
| Citation recall: PDF pages only (mean) | 0.841 |
| Citations failing the in-code check | 0 |
| Groundedness (supported claims / claims, mean) | 0.942 |
| Answered without citations | 0 |
| **Safe**: no unsupported content shown (judge found 0 unsupported claims, or abstained) | 18/20 |
| **Useful**: answerable questions that received a non-abstaining answer | 19/19 |
| Over-abstention (abstained or unverified on an answerable question; graded incorrect) | 0 |
| Abstention correct | 20/20 |
| Opens with the assumption (unspecified program) | 4/4 |
| Startup warmup before timing (not in any latency) | 0.516 s (store 0.004 s, tables 0.461 s, search 0.052 s) |
| Latency, all | p50 19.2 s, p95 30.58 s (n=20) |
| Latency, cold (index not yet loaded) | p50 19.2 s, p95 30.58 s (n=20) |
| Latency, warm | none |
| Over 30 s | 1 |
| Rendered length incl. citations, words (mean / median / max) | 110.05 / 113.0 / 140 |
| Displayed content, words excl. labels and citations (mean; in 60-120) | 110.05; 14/20 |
| Needs review (not answered, uncited or a flagged citation) | 1 |
| Flags | budget_spent:tool_cap 2 |
| Failures by class | ingested but not retrieved 3, retrieved but answered wrong 3, answered right but cited wrong 4 |
| Cost | agent $3.46 ($0.173/question), judge $3.36, total $6.82 |

## Per question

| ID | Accuracy | Grounded | R@10 | Retrieval | Cite P / R | Abst. | Assum. | Time s | Words | Cost $ | Failure class |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Q01 | partial | 1.0 | 1.0 | 1.0 | 0.667 / 0.4 | True | – | 28.9 | 114 | 0.306 | retrieved but answered wrong |
| Q02 | correct | 1.0 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 17.2 | 111 | 0.278 | – |
| Q03 | correct | 0.875 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 62.6 | 114 | 0.455 | – |
| Q04 | correct | 1.0 | 0.5 | 0.667 | 0.4 / 0.667 | True | – | 22.9 | 104 | 0.609 | answered right but cited wrong |
| Q05 | correct | 0.875 | 1.0 | 1.0 | 0.667 / 1.0 | True | – | 23.2 | 140 | 0.466 | – |
| Q06 | partial | 1.0 | 0.5 | 0.75 | 0.375 / 0.75 | True | – | 18.6 | 117 | 0.351 | ingested but not retrieved |
| Q07 | partial | 0.75 | 0.25 | 0.5 | 0.4 / 0.5 | True | – | 22.7 | 129 | 0.629 | ingested but not retrieved |
| Q08 | correct | 0.857 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 17.0 | 111 | 0.234 | – |
| Q09 | correct | 1.0 | 1.0 | 1.0 | 0.5 / 1.0 | True | – | 19.9 | 99 | 0.422 | – |
| Q10 | partial | 1.0 | 0.333 | 0.667 | 0.25 / 0.667 | True | – | 19.2 | 109 | 0.546 | ingested but not retrieved |
| Q11 | correct | 1.0 | 1.0 | 1.0 | 0.5 / 1.0 | True | True | 19.0 | 112 | 0.191 | – |
| Q12 | correct | 1.0 | 1.0 | 1.0 | 0.667 / 0.5 | True | – | 15.2 | 101 | 0.178 | answered right but cited wrong |
| Q13 | partial | 1.0 | 0.667 | 1.0 | 0.667 / 0.667 | True | – | 18.7 | 115 | 0.309 | retrieved but answered wrong |
| Q14 | correct | 1.0 | 0.333 | 1.0 | 0.667 / 0.667 | True | True | 14.0 | 112 | 0.226 | answered right but cited wrong |
| Q15 | correct | 0.846 | 0.5 | 1.0 | 1.0 / 1.0 | True | – | 19.9 | 118 | 0.309 | – |
| Q16 | correct | 1.0 | 1.0 | 1.0 | 0.5 / 1.0 | True | True | 19.2 | 122 | 0.295 | – |
| Q17 | partial | 1.0 | 1.0 | 1.0 | 0.4 / 1.0 | True | – | 26.4 | 135 | 0.354 | retrieved but answered wrong |
| Q18 | correct | 0.8 | 0.5 | 1.0 | 0.333 / 1.0 | True | True | 20.3 | 130 | 0.343 | – |
| Q19 | correct | 0.9 | 1.0 | 1.0 | 1.0 / 0.667 | True | – | 15.4 | 102 | 0.247 | answered right but cited wrong |
| Q20 | correct | n/a | – | – | – / – | True | – | 9.9 | 6 | 0.077 | – |

## Lowest-scoring questions

Ranked by accuracy, then groundedness, citation recall and retrieval recall.

- **Q07** (synthesis): partial [ingested but not retrieved], groundedness 0.75, citation recall 0.5, retrieval 0.5
  - Judge: Covers indefinite continuation, BID/TID dosing and monitoring, but wrongly says buprenorphine may be preferred for pain (reference: insufficient evidence) and omits baseline/annual monitoring frequency.
  - Not fully supported: The usual target dose is 16/4 mg/day. (partial: The guide gives a target maintenance range of 12/3 mg to 16/4 mg/day. 16/4 mg/day is the Day 2 titration target and the top of that range, not a single usual target.) \| Doses up to 24 mg/day or higher may be used only with careful monitoring and documented rationale. (partial: The source lists 24 mg/day as the usual max dose. Only doses above 24 mg/day require careful monitoring and a documented rationale.)
- **Q01** (conflict across versions; synthesis): partial [retrieved but answered wrong], groundedness 1.0, citation recall 0.4, retrieval 1.0
  - Judge: Correct conclusion (SGLT2 first-line regardless of A1c, empagliflozin/canagliflozin) but omits the older 2020 metformin-first conflict and the formulary-coverage caveat.
  - Missing terms: older guide metformin-first
- **Q10** (apparent conflict; document purpose): partial [ingested but not retrieved], groundedness 1.0, citation recall 0.667, retrieval 0.667
  - Judge: Correctly applies the CPG's strong recommendation against initiation and treats the dosing table as non-prescriptive, but omits PBM's stated preference for non-opioid and non-pharmacologic care.
  - Missing terms: non-opioid preference
- **Q13** (prior auth process): partial [retrieved but answered wrong], groundedness 1.0, citation recall 0.667, retrieval 1.0
  - Judge: Contacts and the 72-hour supply are correct, but it doesn't name the Standard PA fax form and gives a general forms page instead of the reference's PDF URL.
- **Q06** (multi-document; structured formulary): partial [ingested but not retrieved], groundedness 1.0, citation recall 0.75, retrieval 0.75
  - Judge: Correctly says PA is needed for concurrent GLP-1 + DPP-4 use and that commercial is billed first, but omits the VA avoid-combination advice and pharmacist medication review recommendation.

## Random sample the judge marked correct

To check the judge isn't too lenient (sample seed 2488).

- **Q09** (silence vs absence): correct, groundedness 1.0, citation recall 1.0, retrieval 1.0
  - Judge: Correctly describes the override process (consult, document, submit appropriate override code at POS) and states no specific code is named; 569 clarified as not an override code.
- **Q05** (multi-document; override and payer coordination): correct, groundedness 0.875, citation recall 1.0, retrieval 1.0
  - Judge: Says don't bill NYRx, request Part D override, 7-day fill or coverage determination, and give CMS notice; matches reference on every key point.
  - Not fully supported: If no override, dispense up to 7 days or have the patient/prescriber request a standard or expedited coverage determination for the full 30 days. (partial: Sources support up to 7 days or a coverage determination (standard/expedited) for the full days supply as written; the 30-day figure is not stated in the cited sources.)
- **Q20** (absence): correct, groundedness n/a, citation recall –, retrieval –
  - Judge: Correctly declines; states no answer in knowledge base, matching reference that documents don't cover pediatric amoxicillin dosing. Lacks redirection but not required.

## Caveats

- **The judge is also a Claude model**, so it may share the agent's blind spots. Human spot checks of its grades (the two lists above) are the safeguard.
- **Each question ran once.** The agent isn't deterministic, so a one-question difference between setups may be noise.
- **VA formulary gold** (6 spreadsheet rows, from cells such as A1697:G1697) counts in the all-gold scores; a setup without the formulary lookup can't reach it, so compare setups on the PDF-pages-only scores too. Recall@k covers PDF pages only.
- **Failure classes are assigned by rule** (earliest stage that explains the miss), with ambiguous cases set by hand in `evals/failure_overrides.yaml`.
- **Citation precision is a lower bound**: a correct citation to a page outside the gold set counts against it. Read it together with groundedness.
- **Cold latency has n=20**: in one process only the first question loads the index, so the cold p95 is not a real percentile.
