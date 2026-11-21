# Eval: fixed_openai_structured, 2026-10-16 01:32

- Agent: `claude-sonnet-5-5` (effort medium), index setup `fixed_openai_structured`, max 6 lookups, 25 s deadline
- Judge: `claude-opus-5-5` (effort medium)
- Golden set: `evals/golden.jsonl`, 20 questions, each run once
- Code: commit `36bddaa` (with uncommitted changes)
- Run date: 2026-10-16 01:32; per-question results in `results.csv`

## Results

| Metric | Result |
|---|---|
| Accuracy (judge) | 12 correct, 7 partial, 1 incorrect (score 0.775, partial = 0.5) |
| Judge passes unanimous on the grade | 19/20 |
| must_include terms present (judge, paraphrase counts) | 50/54 |
| must_include terms present (literal substring) | 20/54 |
| Recall@5 / @10 (direct hybrid search on the question, PDF gold) | 0.567 / 0.713 |
| Retrieval recall: all gold / PDF pages only (mean, any tool) | 0.8 / 0.847 |
| Gold sources returned by any tool (all questions) | 45/59 |
| Citation precision / recall: all gold (mean) | 0.765 / 0.722 |
| Citation recall: PDF pages only (mean) | 0.771 |
| Citations failing the in-code check | 0 |
| Groundedness (supported claims / claims, mean) | 0.882 |
| Answered without citations | 0 |
| Abstention correct | 19/20 |
| Opens with the assumption (unspecified program) | 4/4 |
| Latency, all | p50 7.55 s, p95 10.18 s (n=20) |
| Latency, cold (index not yet loaded) | p50 7.54 s, p95 7.54 s (n=1) |
| Latency, warm | p50 7.56 s, p95 10.19 s (n=19) |
| Over 30 s | 0 |
| Words (mean; within 60–120) | 110.75; 14/20 |
| Flags | budget_spent:tool_cap 1 |
| Failures by class | ingested but not retrieved 6, retrieved but answered wrong 2, answered right but cited wrong 5 |
| Cost | agent $0.65 ($0.033/question), judge $2.99, total $3.64 |

## Per question

| ID | Accuracy | Grounded | R@10 | Retrieval | Cite P / R | Abst. | Assum. | Time s | Words | Cost $ | Failure class |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Q01 | partial | 0.857 | 0.8 | 0.6 | 0.5 / 0.4 | True | – | 7.5 | 127 | 0.224 | ingested but not retrieved |
| Q02 | correct | 1.0 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 6.4 | 87 | 0.116 | – |
| Q03 | partial | 0.9 | 0.75 | 0.857 | 1.0 / 0.571 | True | – | 7.6 | 113 | 0.225 | ingested but not retrieved |
| Q04 | partial | 0.818 | 0.833 | 0.833 | 1.0 / 0.667 | True | – | 10.2 | 118 | 0.255 | ingested but not retrieved |
| Q05 | correct | 1.0 | 1.0 | 1.0 | 0.75 / 0.75 | True | – | 8.3 | 143 | 0.210 | answered right but cited wrong |
| Q06 | partial | 1.0 | 0.75 | 0.75 | 0.6 / 0.75 | True | – | 7.8 | 127 | 0.244 | ingested but not retrieved |
| Q07 | partial | 1.0 | 0.25 | 0.75 | 0.333 / 0.5 | True | – | 10.4 | 141 | 0.334 | ingested but not retrieved |
| Q08 | correct | 0.889 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 5.8 | 121 | 0.151 | – |
| Q09 | correct | 0.714 | 1.0 | 1.0 | 0.5 / 1.0 | True | – | 6.6 | 119 | 0.165 | – |
| Q10 | correct | 0.889 | 0.0 | 0.667 | 0.25 / 0.333 | True | – | 8.6 | 130 | 0.256 | answered right but cited wrong |
| Q11 | correct | 0.875 | 1.0 | 1.0 | 1.0 / 1.0 | True | True | 5.2 | 79 | 0.123 | – |
| Q12 | correct | 0.8 | 1.0 | 0.25 | 1.0 / 0.25 | True | – | 4.6 | 81 | 0.116 | answered right but cited wrong |
| Q13 | correct | 0.889 | 1.0 | 1.0 | 0.6 / 1.0 | True | – | 7.6 | 105 | 0.216 | – |
| Q14 | correct | 0.75 | 0.333 | 0.667 | 1.0 / 0.667 | True | True | 7.5 | 112 | 0.172 | answered right but cited wrong |
| Q15 | correct | 0.9 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 6.5 | 116 | 0.181 | – |
| Q16 | correct | 0.889 | 0.5 | 0.5 | 0.5 / 0.5 | True | True | 8.9 | 104 | 0.185 | answered right but cited wrong |
| Q17 | partial | 0.714 | 0.5 | 1.0 | 0.5 / 1.0 | True | – | 9.7 | 89 | 0.201 | retrieved but answered wrong |
| Q18 | partial | 1.0 | 0.5 | 1.0 | 1.0 / 1.0 | True | True | 8.8 | 118 | 0.176 | retrieved but answered wrong |
| Q19 | incorrect | n/a | 0.333 | 0.333 | 1.0 / 0.333 | False | – | 6.3 | 108 | 0.054 | ingested but not retrieved |
| Q20 | correct | n/a | – | – | – / – | True | – | 4.7 | 77 | 0.042 | – |

## Lowest-scoring questions

Ranked by accuracy, then groundedness, citation recall and retrieval recall.

- **Q19** (silence vs absence): incorrect [ingested but not retrieved], groundedness n/a, citation recall 0.333, retrieval 0.333
  - Judge: Declines as not_in_documents and never gives the $1.00 flat copay for preferred brands; the reference says the copay is answerable from the documents.
  - Missing terms: $1.00
- **Q17** (effective dates): partial [retrieved but answered wrong], groundedness 0.714, citation recall 1.0, retrieval 1.0
  - Judge: Correctly lists Humalog products and insulin aspart with the 10/22/2026 date, but omits the glucagon kit and Gvoke becoming preferred.
  - Missing terms: Gvoke
  - Not fully supported: Three diabetes-related products carry a 10/22/2026 change marker on the NY Medicaid PDL. (partial: p37 shows the three insulin markers, but cited p34 also marks glucagon HCl emergency kit and Gvoke (glucagon agents, used for diabetic hypoglycemia) as preferred as of 10/22/2026, so the count of three is incomplete.) \| There are no change markers on the GLP-1, DPP-4, SGLT2, biguanide, long-acting insulin or insulin mix rows. (partial: GLP-1 (p34), DPP-4 (p33), SGLT2 (p37), and long-acting and mix insulin (p36) rows show no markers. No cited page covers biguanides.)
- **Q04** (conflict across dates; screening vs restriction): partial [ingested but not retrieved], groundedness 0.818, citation recall 0.667, retrieval 0.833
  - Judge: Conclusions and key facts match: mandatory DMPs, buprenorphine counted but excluded from MME, and MAT not blocked. Minor error: it calls the memo 2018, not 2019.
  - Not fully supported: Plans are expected to allow POS overrides (for MAT/DMP limits). (partial: The sheet says plans should allow opioid safety alerts to be overridden at POS when the enrollee is exempt. It does not describe POS overrides for DMP limits or MAT specifically.) \| The newer 2022 sheet is consistent with DMPs being mandatory. (partial: The sheet mentions drug management programs but does not address whether they are mandatory.)
- **Q01** (conflict across versions; synthesis): partial [ingested but not retrieved], groundedness 0.857, citation recall 0.4, retrieval 0.6
  - Judge: Correctly concludes the SGLT2 can start regardless of A1c per the 2025 guide and CPG, but omits the older 2020 metformin-first sequence and canagliflozin.
  - Missing terms: older guide metformin-first
  - Not fully supported: Empagliflozin is the formulary agent named for ASCVD. (partial: Empagliflozin is the agent named for ASCVD, but its formulary status is marked only by bolding (per p5's legend), which isn't visible in the extracted text.)
- **Q03** (apparent conflict; dose vs coverage limit; multi-document): partial [ingested but not retrieved], groundedness 0.9, citation recall 0.571, retrieval 0.857
  - Judge: Conclusions are right, but it omits that doses above the VA 24 mg usual maximum need careful monitoring and documented rationale, and that MAT needs no PA.
  - Not fully supported: Switching products needs a new prescription from the prescriber (unsupported: No cited source addresses whether switching to the patch requires a new prescription.)

## Random sample the judge marked correct

To check the judge isn't too lenient (sample seed 4820).

- **Q05** (multi-document; override and payer coordination): correct [answered right but cited wrong], groundedness 1.0, citation recall 0.75, retrieval 1.0
  - Judge: Says don't bill NYRx, explains Medicaid doesn't cover Part D classes, and lists override, 7-day/coverage determination, and CMS notice steps matching the reference.
- **Q16** (reject code): correct [answered right but cited wrong], groundedness 0.889, citation recall 0.5, retrieval 0.5
  - Judge: Assumes NY Medicaid, defines reject 22 as missing/invalid DAW, notes BLTG, and gives DAW 9 with the DAW 1 exception. It omits the payment and copay details.
  - Not fully supported: Generic liraglutide is non-preferred (PA needed). (partial: The page lists generic liraglutide as non-preferred but does not state that non-preferred drugs require PA.)
- **Q20** (absence): correct, groundedness n/a, citation recall –, retrieval –
  - Judge: Correctly states the documents don't cover pediatric amoxicillin dosing, describes the corpus scope, and refers the user to an outside pediatric reference.

## Caveats

- **The judge is also a Claude model**, so it may share the agent's blind spots. Human spot checks of its grades (the two lists above) are the safeguard.
- **Each question ran once.** The agent isn't deterministic, so a one-question difference between setups may be noise.
- **VA formulary gold** (6 spreadsheet rows, from cells such as A1697:G1697) counts in the all-gold scores; a setup without the formulary lookup can't reach it, so compare setups on the PDF-pages-only scores too. Recall@k covers PDF pages only.
- **Failure classes are assigned by rule** (earliest stage that explains the miss), with ambiguous cases set by hand in `evals/failure_overrides.yaml`.
- **Citation precision is a lower bound**: a correct citation to a page outside the gold set counts against it. Read it together with groundedness.
- **Cold latency has n=1**: in one process only the first question loads the index, so the cold p95 is not a real percentile.
