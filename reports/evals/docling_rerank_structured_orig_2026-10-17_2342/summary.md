# Eval: docling_rerank_structured, 2026-10-17 23:42

- Agent: `claude-sonnet-5-5` (effort medium), index setup `docling_rerank_structured`, max 6 lookups, 25 s deadline
- Judge: `claude-opus-5-5` (effort medium, 3 passes)
- Golden set: `evals/golden.jsonl`, 20 questions, each run once
- Code: commit `005e08c` (with uncommitted changes)
- Run date: 2026-10-17 23:42; per-question results in `results.csv`

## Results

| Metric | Result |
|---|---|
| Accuracy (judge) | 17 correct, 3 partial, 0 incorrect (score 0.925, partial = 0.5) |
| Judge passes unanimous on the grade | 18/20 |
| must_include terms present (judge, paraphrase counts) | 54/54 |
| must_include terms present (literal substring) | 22/54 |
| Recall@5 / @10 (direct hybrid search on the question, PDF gold) | 0.729 / 0.842 |
| Retrieval recall: all gold / PDF pages only (mean, any tool) | 0.909 / 0.956 |
| Gold sources returned by any tool (all questions) | 52/59 |
| Citation precision / recall: all gold (mean) | 0.791 / 0.816 |
| Citation recall: PDF pages only (mean) | 0.865 |
| Citations failing the in-code check | 0 |
| Groundedness (supported claims / claims, mean) | 0.887 |
| Answered without citations | 0 |
| **Safe**: no unsupported content shown (judge found 0 unsupported claims, or abstained) | 16/20 |
| **Useful**: answerable questions that received a non-abstaining answer | 19/19 |
| Over-abstention (abstained or unverified on an answerable question; graded incorrect) | 0 |
| Abstention correct | 20/20 |
| Opens with the assumption (unspecified program) | 4/4 |
| Startup warmup before timing (not in any latency) | 15.917 s (drug_tables 0.029 s, drug_vocabulary 0.007 s, index 15.602 s) |
| Latency, all | p50 10.56 s, p95 22.16 s (n=20) |
| Latency, cold (index not yet loaded) | none |
| Latency, warm | p50 10.56 s, p95 22.16 s (n=20) |
| Over 30 s | 0 |
| Rendered length incl. citations, words (mean / median / max) | 111 / 112.0 / 159 |
| Displayed content, words excl. labels and citations (mean; in 60-120) | 111; 14/20 |
| Needs review (not answered, uncited or a flagged citation) | 1 |
| Flags | none |
| Failures by class | ingested but not retrieved 2, retrieved but answered wrong 1, answered right but cited wrong 7 |
| Cost | agent $1.29 ($0.064/question), judge $3.08, total $4.37 |

## Per question

| ID | Accuracy | Grounded | R@10 | Retrieval | Cite P / R | Abst. | Assum. | Time s | Words | Cost $ | Failure class |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Q01 | correct | 0.778 | 1.0 | 1.0 | 0.6 / 0.6 | True | – | 29.5 | 105 | 0.279 | answered right but cited wrong |
| Q02 | correct | 1.0 | 1.0 | 1.0 | 0.667 / 1.0 | True | – | 21.8 | 115 | 0.173 | – |
| Q03 | correct | 1.0 | 0.75 | 0.857 | 1.0 / 0.571 | True | – | 20.7 | 126 | 0.250 | answered right but cited wrong |
| Q04 | correct | 0.75 | 0.833 | 1.0 | 1.0 / 0.833 | True | – | 15.2 | 137 | 0.286 | answered right but cited wrong |
| Q05 | correct | 0.778 | 1.0 | 1.0 | 0.8 / 1.0 | True | – | 18.5 | 159 | 0.306 | – |
| Q06 | partial | 1.0 | 0.5 | 0.75 | 0.75 / 0.75 | True | – | 13.3 | 117 | 0.236 | ingested but not retrieved |
| Q07 | partial | 0.923 | 0.25 | 0.75 | 0.4 / 0.5 | True | – | 9.2 | 117 | 0.310 | ingested but not retrieved |
| Q08 | correct | 1.0 | 1.0 | 1.0 | 0.5 / 1.0 | True | – | 9.4 | 134 | 0.212 | – |
| Q09 | correct | 0.857 | 1.0 | 1.0 | 0.5 / 1.0 | True | – | 10.4 | 123 | 0.193 | – |
| Q10 | correct | 0.8 | 0.667 | 1.0 | 0.4 / 0.667 | True | – | 13.2 | 136 | 0.408 | answered right but cited wrong |
| Q11 | correct | 0.833 | 1.0 | 1.0 | 1.0 / 1.0 | True | True | 5.5 | 77 | 0.117 | – |
| Q12 | correct | 0.833 | 1.0 | 0.25 | 1.0 / 0.25 | True | – | 4.6 | 85 | 0.119 | answered right but cited wrong |
| Q13 | partial | 0.9 | 0.667 | 1.0 | 0.75 / 1.0 | True | – | 8.8 | 106 | 0.229 | retrieved but answered wrong |
| Q14 | correct | 1.0 | 0.333 | 0.667 | 1.0 / 0.667 | True | True | 8.9 | 97 | 0.165 | answered right but cited wrong |
| Q15 | correct | 0.909 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 12.1 | 105 | 0.205 | – |
| Q16 | correct | 0.75 | 1.0 | 1.0 | 0.667 / 1.0 | True | True | 10.2 | 103 | 0.212 | – |
| Q17 | correct | 1.0 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 16.8 | 81 | 0.180 | – |
| Q18 | correct | 0.75 | 1.0 | 1.0 | 1.0 / 1.0 | True | True | 8.9 | 115 | 0.218 | – |
| Q19 | correct | 1.0 | 1.0 | 1.0 | 1.0 / 0.667 | True | – | 10.8 | 109 | 0.203 | answered right but cited wrong |
| Q20 | correct | n/a | – | – | – / – | True | – | 7.6 | 73 | 0.067 | – |

## Lowest-scoring questions

Ranked by accuracy, then groundedness, citation recall and retrieval recall.

- **Q13** (prior auth process): partial [retrieved but answered wrong], groundedness 0.9, citation recall 1.0, retrieval 1.0
  - Judge: Covers prescriber-only requests, the call center number, CoverMyMeds/PAXpress and the 72-hour supply, but omits the Standard PA fax form and its specific PDF URL.
  - Not fully supported: The NYRx Clinical Call Center (Prime Therapeutics) can be called at 1-877-309-9493 and is open 24/7. (partial: The phone number and 24/7 availability are supported. No cited page says Prime Therapeutics operates the Clinical Call Center; Prime appears only in the Education & Outreach email address.)
- **Q07** (synthesis): partial [ingested but not retrieved], groundedness 0.923, citation recall 0.5, retrieval 0.75
  - Judge: All three conclusions are right, but it says buprenorphine 'may be preferred' for co-occurring pain, contradicting the CPG's insufficient evidence. It also omits COWS, CBC and infectious disease testing.
  - Not fully supported: Use caution with CNS depressants. (unsupported: None of the cited pages mention CNS depressants.)
- **Q06** (multi-document; structured formulary): partial [ingested but not retrieved], groundedness 1.0, citation recall 0.75, retrieval 0.75
  - Judge: Correctly requires PA for concurrent GLP-1/DPP-4 use and bills commercial before NYRx, but omits the VA advice to avoid the combination and the recommended pharmacist medication review.
- **Q04** (conflict across dates; screening vs restriction): correct [answered right but cited wrong], groundedness 0.75, citation recall 0.833, retrieval 1.0
  - Judge: Matches reference: DMPs mandatory from 2022 (no true conflict), buprenorphine counts for prescribers/pharmacies but excluded from MME, MAT not FAD and not blocked.
  - Not fully supported: Buprenorphine for MAT is not a frequently abused drug (FAD) under the DMP, so a DMP limit shouldn't apply to it. (partial: The FAD definition excluding MAT buprenorphine is stated for plan year 2019 only. The memo says to consult later Call Letters for changes in 2020 and beyond.) \| The plan must run case management, send notices and get prescriber agreement before any limit on other opioids. (partial: Case management with prescribers and written notice before a limitation are supported. A requirement to obtain prescriber agreement is not stated in the cited pages.)
- **Q16** (reject code): correct, groundedness 0.75, citation recall 1.0, retrieval 1.0
  - Judge: Assumes NY Medicaid, defines reject 22 as missing/invalid DAW, and advises DAW 9 with the DAW 1 exception. Omits the brand-rate/U&C pricing and generic copay, a minor gap.
  - Not fully supported: Resubmit with DAW 9 (substitution allowed by prescriber, plan requests brand) in field 408-D8. (partial: DAW 9 is supported; the field number 408-D8 is not in the cited source.) \| Generic liraglutide is non-preferred and needs PA. (partial: Non-preferred status is supported; the cited page does not state that liraglutide requires PA.)

## Random sample the judge marked correct

To check the judge isn't too lenient (sample seed 265).

- **Q16** (reject code): correct, groundedness 0.75, citation recall 1.0, retrieval 1.0
  - Judge: Assumes NY Medicaid, defines reject 22 as missing/invalid DAW, and advises DAW 9 with the DAW 1 exception. Omits the brand-rate/U&C pricing and generic copay, a minor gap.
  - Not fully supported: Resubmit with DAW 9 (substitution allowed by prescriber, plan requests brand) in field 408-D8. (partial: DAW 9 is supported; the field number 408-D8 is not in the cited source.) \| Generic liraglutide is non-preferred and needs PA. (partial: Non-preferred status is supported; the cited page does not state that liraglutide requires PA.)
- **Q19** (silence vs absence): correct [answered right but cited wrong], groundedness 1.0, citation recall 0.667, retrieval 1.0
  - Judge: States no tiers, Trulicity preferred brand, $1.00 copay, and gives exemptions; omissions like OTC copay and the can't-refuse rule are minor.
- **Q17** (effective dates): correct, groundedness 1.0, citation recall 1.0, retrieval 1.0
  - Judge: Lists all five products with correct status and the 10/22/2026 effective date; minor hedging on unchecked classes doesn't contradict the reference.

## Caveats

- **The judge is also a Claude model**, so it may share the agent's blind spots. Human spot checks of its grades (the two lists above) are the safeguard.
- **Each question ran once.** The agent isn't deterministic, so a one-question difference between setups may be noise.
- **VA formulary gold** (6 spreadsheet rows, from cells such as A1697:G1697) counts in the all-gold scores; a setup without the formulary lookup can't reach it, so compare setups on the PDF-pages-only scores too. Recall@k covers PDF pages only.
- **Failure classes are assigned by rule** (earliest stage that explains the miss), with ambiguous cases set by hand in `evals/failure_overrides.yaml`.
- **Citation precision is a lower bound**: a correct citation to a page outside the gold set counts against it. Read it together with groundedness.
- **Cold latency has n=0**: in one process only the first question loads the index, so the cold p95 is not a real percentile.
