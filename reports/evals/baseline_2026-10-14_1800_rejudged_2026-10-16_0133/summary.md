# Eval: baseline, 2026-10-14 22:00 UTC, re-judged 2026-10-16 01:33

- Agent: `claude-sonnet-5-5` (effort medium), index setup `baseline`, max 6 lookups, 25 s deadline
- Judge: `claude-opus-5-5` (effort medium)
- Golden set: `evals/golden.jsonl`, 20 questions, each run once
- Code: commit `36bddaa` (with uncommitted changes)
- Run date: 2026-10-14 22:00 UTC, re-judged 2026-10-16 01:33; per-question results in `results.csv`
- Re-judged from `reports/evals/baseline_2026-10-14_1800` with the current judges; the agent wasn't rerun

## Results

| Metric | Result |
|---|---|
| Accuracy (judge) | 8 correct, 12 partial, 0 incorrect (score 0.7, partial = 0.5) |
| Judge passes unanimous on the grade | 17/20 |
| must_include terms present (judge, paraphrase counts) | 48/54 |
| must_include terms present (literal substring) | 22/54 |
| Recall@5 / @10 (direct hybrid search on the question, PDF gold) | 0.552 / 0.646 |
| Retrieval recall: all gold / PDF pages only (mean, any tool) | 0.675 / 0.732 |
| Gold sources returned by any tool (all questions) | 35/59 |
| Citation precision / recall: all gold (mean) | 0.768 / 0.675 |
| Citation recall: PDF pages only (mean) | 0.732 |
| Citations failing the in-code check | 0 |
| Groundedness (supported claims / claims, mean) | 0.91 |
| Answered without citations | 0 |
| Abstention correct | 20/20 |
| Opens with the assumption (unspecified program) | 4/4 |
| Latency, all | p50 7.24 s, p95 10.97 s (n=20) |
| Latency, cold (index not yet loaded) | p50 13.91 s, p95 13.91 s (n=1) |
| Latency, warm | p50 7.14 s, p95 9.75 s (n=19) |
| Over 30 s | 0 |
| Words (mean; within 60–120) | 114.2; 12/20 |
| Flags | budget_spent:tool_cap 1 |
| Failures by class | source not ingested 2, ingested but not retrieved 9, retrieved but answered wrong 1, answered right but cited wrong 2 |
| Cost | agent $0.66 ($0.033/question), judge $2.92, total $3.57 |

## Per question

| ID | Accuracy | Grounded | R@10 | Retrieval | Cite P / R | Abst. | Assum. | Time s | Words | Cost $ | Failure class |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Q01 | partial | 0.889 | 0.6 | 0.4 | 0.5 / 0.4 | True | – | 13.9 | 152 | 0.190 | ingested but not retrieved |
| Q02 | correct | 1.0 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 8.8 | 97 | 0.118 | – |
| Q03 | partial | 1.0 | 0.5 | 0.429 | 1.0 / 0.429 | True | – | 7.9 | 124 | 0.211 | source not ingested |
| Q04 | partial | 0.909 | 0.667 | 0.667 | 0.8 / 0.667 | True | – | 7.9 | 121 | 0.266 | ingested but not retrieved |
| Q05 | correct | 0.75 | 0.5 | 0.75 | 1.0 / 0.75 | True | – | 7.3 | 139 | 0.201 | answered right but cited wrong |
| Q06 | partial | 1.0 | 0.75 | 0.75 | 0.6 / 0.75 | True | – | 7.6 | 128 | 0.256 | ingested but not retrieved |
| Q07 | partial | 1.0 | 0.25 | 0.25 | 0.2 / 0.25 | True | – | 10.8 | 151 | 0.275 | ingested but not retrieved |
| Q08 | correct | 1.0 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 9.2 | 111 | 0.130 | – |
| Q09 | correct | 0.833 | 1.0 | 1.0 | 0.5 / 1.0 | True | – | 6.9 | 112 | 0.149 | – |
| Q10 | partial | 1.0 | 0.0 | 0.667 | 0.5 / 0.667 | True | – | 8.7 | 122 | 0.259 | ingested but not retrieved |
| Q11 | correct | 1.0 | 1.0 | 1.0 | 1.0 / 1.0 | True | True | 7.1 | 92 | 0.126 | – |
| Q12 | partial | 1.0 | 1.0 | 0.25 | 1.0 / 0.25 | True | – | 7.0 | 98 | 0.147 | source not ingested |
| Q13 | partial | 1.0 | 1.0 | 0.667 | 0.667 / 0.667 | True | – | 6.1 | 115 | 0.172 | ingested but not retrieved |
| Q14 | correct | 0.667 | 0.667 | 0.667 | 1.0 / 0.667 | True | True | 7.1 | 108 | 0.186 | answered right but cited wrong |
| Q15 | correct | 0.667 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 6.1 | 103 | 0.171 | – |
| Q16 | partial | 1.0 | 0.5 | 0.5 | 0.333 / 0.5 | True | True | 7.0 | 132 | 0.199 | ingested but not retrieved |
| Q17 | partial | 1.0 | 0.5 | 1.0 | 1.0 / 1.0 | True | – | 9.6 | 90 | 0.154 | retrieved but answered wrong |
| Q18 | partial | 0.857 | 0.0 | 0.5 | 0.5 / 0.5 | True | True | 6.2 | 111 | 0.173 | ingested but not retrieved |
| Q19 | partial | 0.714 | 0.333 | 0.333 | 1.0 / 0.333 | True | – | 6.5 | 107 | 0.147 | ingested but not retrieved |
| Q20 | correct | n/a | – | – | – / – | True | – | 5.7 | 71 | 0.043 | – |

## Lowest-scoring questions

Ranked by accuracy, then groundedness, citation recall and retrieval recall.

- **Q19** (silence vs absence): partial [ingested but not retrieved], groundedness 0.714, citation recall 0.333, retrieval 0.333
  - Judge: Correctly says no tiers and Trulicity is preferred, but wrongly claims documents give no copay amount; misses the $1.00 flat copay.
  - Missing terms: $1.00
  - Not fully supported: NYRx doesn't use copay tiers; the PDL only lists preferred or non-preferred status. (partial: The page shows only preferred/non-preferred columns, but it does not say that NYRx has no copay tiers.) \| The PDL is marked BLTG for Trulicity. (unsupported: The BLTG marker appears next to Victoza, not Trulicity.)
- **Q18** (no program stated): partial [ingested but not retrieved], groundedness 0.857, citation recall 0.5, retrieval 0.5
  - Judge: Correctly assumes NY Medicaid and no PA for MAT, but omits the pain-indication part (generic patch preferred, Butrans/Belbuca non-preferred, long-acting opioid criteria), wrongly claiming documents don't cover it.
  - Missing terms: Butrans/Belbuca non-preferred
  - Not fully supported: The pharmacist's only PA is the 72-hour emergency supply. (partial: The source allows the pharmacist to obtain a PA for up to a 72-hour emergency supply. This applies only when the prescriber hasn't obtained a PA and can't be reached, and that condition is omitted. The same page also lets pharmacies start ePA requests via CoverMyMeds for the prescriber to complete.)
- **Q01** (conflict across versions; synthesis): partial [ingested but not retrieved], groundedness 0.889, citation recall 0.4, retrieval 0.4
  - Judge: Correct conclusion: start the SGLT2i regardless of A1c. Omits the older 2020 guide's metformin-first sequence (the version conflict) and names only empagliflozin, not canagliflozin.
  - Missing terms: older guide metformin-first
  - Not fully supported: The VA/DoD CPG (2023) says a GLP-1 RA or SGLT2i should be part of the regimen regardless of A1c. (partial: The CPG states this specifically for adults with T2DM and ASCVD, and only for agents with proven CV benefit; the answer omits these conditions.)
- **Q04** (conflict across dates; screening vs restriction): partial [ingested but not retrieved], groundedness 0.909, citation recall 0.667, retrieval 0.667
  - Judge: Counting, MME exclusion, non-FAD status and MAT access match. It never says DMPs are mandatory from 2022 under the SUPPORT Act; it calls them voluntary but expected.
  - Missing terms: DMPs mandatory
  - Not fully supported: A DMP limit (prescriber/pharmacy lock-in or beneficiary-specific POS edit) shouldn't restrict Suboxone. (partial: The sources exclude buprenorphine for MAT from FADs and describe the DMP limit types (p2), but they never name Suboxone or say it is a buprenorphine product.)
- **Q07** (synthesis): partial [ingested but not retrieved], groundedness 1.0, citation recall 0.25, retrieval 0.25
  - Judge: Splitting and the main monitoring are covered, but it omits not stopping on return to use and misses COWS, CBC and infectious disease testing.
  - Missing terms: continue indefinitely

## Random sample the judge marked correct

To check the judge isn't too lenient (sample seed 1035).

- **Q20** (absence): correct, groundedness n/a, citation recall –, retrieval –
  - Judge: Correctly states the documents don't cover pediatric amoxicillin otitis dosing, describes the corpus scope, and refers to a pediatric reference or the prescriber.
- **Q05** (multi-document; override and payer coordination): correct [answered right but cited wrong], groundedness 0.75, citation recall 0.75, retrieval 0.75
  - Judge: Says don't bill NYRx, explains Part D primacy for full-benefit duals, and gives override, 7-day/coverage determination, and CMS notice steps, matching the reference.
  - Not fully supported: Opioids aren't in the Part D-excluded group that Medicaid pays for. (partial: The excluded-class list is illustrative ('such as') and no source explicitly states that opioids are not excluded. The CMS document's Part D opioid edits imply Part D coverage but do not say so directly.) \| If there is no override, dispense up to 7 days or have the prescriber or enrollee request a coverage determination for the full days supply. (partial: The source says the enrollee may request a coverage determination. It does not mention the prescriber requesting one.)
- **Q08** (structured claim code; conditional policy): correct, groundedness 1.0, citation recall 1.0, retrieval 1.0
  - Judge: Gives NP in 439-E4, SCC 18, all three conditions, 30-day limit with short-cycle exception, and the call-the-Department fallback; nothing contradicts the reference.

## Caveats

- **The judge is also a Claude model**, so it may share the agent's blind spots. Human spot checks of its grades (the two lists above) are the safeguard.
- **Each question ran once.** The agent isn't deterministic, so a one-question difference between setups may be noise.
- **VA formulary gold** (6 spreadsheet rows, from cells such as A1697:G1697) counts in the all-gold scores; a setup without the formulary lookup can't reach it, so compare setups on the PDF-pages-only scores too. Recall@k covers PDF pages only.
- **Failure classes are assigned by rule** (earliest stage that explains the miss), with ambiguous cases set by hand in `evals/failure_overrides.yaml`.
- **Citation precision is a lower bound**: a correct citation to a page outside the gold set counts against it. Read it together with groundedness.
- **Cold latency has n=1**: in one process only the first question loads the index, so the cold p95 is not a real percentile.
