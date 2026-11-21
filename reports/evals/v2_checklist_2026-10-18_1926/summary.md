# Eval: v2_checklist, 2026-10-18 19:26

- Agent: `gpt-5.5 (fallback claude-sonnet-5-5)` (effort medium), index setup `v2_checklist`, max 6 lookups, 25 s deadline
- Judge: `claude-opus-5-5` (effort medium, 3 passes)
- Golden set: `evals/golden.jsonl`, 20 questions, each run once
- Code: commit `0aaa897` (with uncommitted changes)
- Run date: 2026-10-18 19:26; per-question results in `results.csv`

## Results

| Metric | Result |
|---|---|
| Accuracy (judge) | 13 correct, 7 partial, 0 incorrect (score 0.825, partial = 0.5) |
| Judge passes unanimous on the grade | 18/20 |
| must_include terms present (judge, paraphrase counts) | 51/54 |
| must_include terms present (literal substring) | 21/54 |
| Recall@5 / @10 (direct hybrid search on the question, PDF gold) | 0.636 / 0.768 |
| Retrieval recall: all gold / PDF pages only (mean, any tool) | 0.908 / 0.947 |
| Gold sources returned by any tool (all questions) | 52/59 |
| Citation precision / recall: all gold (mean) | 0.781 / 0.786 |
| Citation recall: PDF pages only (mean) | 0.84 |
| Citations failing the in-code check | 0 |
| Groundedness (supported claims / claims, mean) | 0.957 |
| Answered without citations | 0 |
| **Safe**: no unsupported content shown (judge found 0 unsupported claims, or abstained) | 20/20 |
| **Useful**: answerable questions that received a non-abstaining answer | 19/19 |
| Over-abstention (abstained or unverified on an answerable question; graded incorrect) | 0 |
| Abstention correct | 20/20 |
| Opens with the assumption (unspecified program) | 4/4 |
| Startup warmup before timing (not in any latency) | 0.459 s (store 0.003 s, tables 0.435 s, search 0.02 s) |
| Latency, all | p50 12.69 s, p95 18.25 s (n=20) |
| Latency, cold (index not yet loaded) | p50 12.69 s, p95 18.25 s (n=20) |
| Latency, warm | none |
| Over 30 s | 0 |
| Rendered length incl. citations, words (mean / median / max) | 87.3 / 91.5 / 116 |
| Displayed content, words excl. labels and citations (mean; in 60-120) | 87.3; 19/20 |
| Needs review (not answered, uncited or a flagged citation) | 1 |
| Flags | budget_spent:tool_cap 4 |
| Failures by class | ingested but not retrieved 4, retrieved but answered wrong 3, answered right but cited wrong 5 |
| Cost | agent $2.71 ($0.136/question), judge $2.57, total $5.28 |

## Per question

| ID | Accuracy | Grounded | R@10 | Retrieval | Cite P / R | Abst. | Assum. | Time s | Words | Cost $ | Failure class |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Q01 | partial | 1.0 | 1.0 | 1.0 | 0.667 / 0.8 | True | – | 17.0 | 82 | 0.287 | retrieved but answered wrong |
| Q02 | correct | 1.0 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 11.7 | 91 | 0.183 | – |
| Q03 | correct | 0.857 | 1.0 | 1.0 | 1.0 / 0.714 | True | – | 19.9 | 104 | 0.382 | answered right but cited wrong |
| Q04 | partial | 1.0 | 0.5 | 0.833 | 1.0 / 0.833 | True | – | 18.2 | 116 | 0.641 | ingested but not retrieved |
| Q05 | correct | 0.833 | 1.0 | 1.0 | 0.75 / 0.75 | True | – | 16.2 | 109 | 0.398 | answered right but cited wrong |
| Q06 | partial | 1.0 | 0.5 | 0.75 | 0.75 / 0.75 | True | – | 12.2 | 83 | 0.228 | ingested but not retrieved |
| Q07 | partial | 1.0 | 0.25 | 0.75 | 0.5 / 0.5 | True | – | 13.7 | 94 | 0.470 | ingested but not retrieved |
| Q08 | correct | 0.857 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 8.1 | 95 | 0.166 | – |
| Q09 | correct | 0.833 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 13.8 | 99 | 0.310 | – |
| Q10 | partial | 1.0 | 0.333 | 0.667 | 0.667 / 0.667 | True | – | 14.9 | 86 | 0.396 | ingested but not retrieved |
| Q11 | correct | 1.0 | 1.0 | 1.0 | 0.5 / 1.0 | True | True | 5.2 | 70 | 0.121 | – |
| Q12 | correct | 1.0 | 1.0 | 0.25 | 0.5 / 0.25 | True | – | 13.4 | 92 | 0.149 | answered right but cited wrong |
| Q13 | partial | 1.0 | 0.667 | 1.0 | 0.667 / 0.667 | True | – | 12.1 | 96 | 0.245 | retrieved but answered wrong |
| Q14 | correct | 1.0 | 0.333 | 1.0 | 0.5 / 0.333 | True | True | 9.4 | 99 | 0.170 | answered right but cited wrong |
| Q15 | partial | 0.8 | 0.5 | 1.0 | 1.0 / 1.0 | True | – | 10.7 | 73 | 0.188 | retrieved but answered wrong |
| Q16 | correct | 1.0 | 1.0 | 1.0 | 0.667 / 1.0 | True | True | 15.0 | 100 | 0.240 | – |
| Q17 | correct | 1.0 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 13.2 | 78 | 0.197 | – |
| Q18 | correct | 1.0 | 0.5 | 1.0 | 0.667 / 1.0 | True | True | 9.6 | 91 | 0.194 | – |
| Q19 | correct | 1.0 | 1.0 | 1.0 | 1.0 / 0.667 | True | – | 11.1 | 82 | 0.197 | answered right but cited wrong |
| Q20 | correct | n/a | – | – | – / – | True | – | 9.6 | 6 | 0.117 | – |

## Lowest-scoring questions

Ranked by accuracy, then groundedness, citation recall and retrieval recall.

- **Q15** (step therapy): partial [retrieved but answered wrong], groundedness 0.8, citation recall 1.0, retrieval 1.0
  - Judge: Correctly says to try IR tramadol (preferred tablet) before ConZip or tramadol ER and notes opioid-naïve PA; omits the 4-Rx/30-day limit and PA for under-12 patients.
  - Not fully supported: For NYRx, tramadol ER is non-preferred with step therapy (ST) in the Opioids–Long-Acting class. (partial: The PDL lists tramadol ER as non-preferred with ST, but that status is 'as of 10/22/2026', after today (2026-10-18). The answer states it as current without noting the effective date.)
- **Q07** (synthesis): partial [ingested but not retrieved], groundedness 1.0, citation recall 0.5, retrieval 0.75
  - Judge: Covers indefinite continuation, BID/TID dosing and monitoring list, but omits the baseline/annual/initiation monitoring schedule and the CPG's insufficient evidence favoring any MOUD for pain.
- **Q10** (apparent conflict; document purpose): partial [ingested but not retrieved], groundedness 1.0, citation recall 0.667, retrieval 0.667
  - Judge: Correctly applies the CPG against initiation and treats the Butrans table as dosing info only, but omits PBM's preference for non-opioid and non-pharmacologic care.
  - Missing terms: non-opioid preference
- **Q13** (prior auth process): partial [retrieved but answered wrong], groundedness 1.0, citation recall 0.667, retrieval 1.0
  - Judge: Core routes, phone number, prescriber-only rule and 72-hour emergency supply are correct, but it omits PAXpress and gives a different fax form URL than the reference's PDF.
- **Q06** (multi-document; structured formulary): partial [ingested but not retrieved], groundedness 1.0, citation recall 0.75, retrieval 0.75
  - Judge: PA requirement and commercial-first billing are correct, but it omits the VA guidance to avoid the GLP-1 + DPP-4 combination and the recommended pharmacist medication review.

## Random sample the judge marked correct

To check the judge isn't too lenient (sample seed 6906).

- **Q18** (no program stated): correct, groundedness 1.0, citation recall 1.0, retrieval 1.0
  - Judge: States NY Medicaid assumption, OUD/MAT SL tablets no PA with 32 mg/day QL, generic patch preferred, Butrans/Belbuca non-preferred PA, and LA opioid criteria.
- **Q12** (different programs (not a conflict)): correct [answered right but cited wrong], groundedness 1.0, citation recall 0.25, retrieval 0.25
  - Judge: Matches reference: Ozempic pen preferred with CC, PA with DPP-4, tablets non-preferred, VA formulary doesn't govern NYRx. Omitting VA PA-F detail is not key.
- **Q09** (silence vs absence): correct, groundedness 0.833, citation recall 1.0, retrieval 1.0
  - Judge: States documents don't name a code, describes consult/document/submit override process, and directs to plan for code—matches reference.
  - Not fully supported: Plans must have a POS override mechanism. (partial: The source says CMS 'expects' sponsors to have a mechanism for overriding opioid safety alerts at POS. That mechanism is specifically for cases where the enrollee is exempt, not a general override mechanism.)

## Caveats

- **The judge is also a Claude model**, so it may share the agent's blind spots. Human spot checks of its grades (the two lists above) are the safeguard.
- **Each question ran once.** The agent isn't deterministic, so a one-question difference between setups may be noise.
- **VA formulary gold** (6 spreadsheet rows, from cells such as A1697:G1697) counts in the all-gold scores; a setup without the formulary lookup can't reach it, so compare setups on the PDF-pages-only scores too. Recall@k covers PDF pages only.
- **Failure classes are assigned by rule** (earliest stage that explains the miss), with ambiguous cases set by hand in `evals/failure_overrides.yaml`.
- **Citation precision is a lower bound**: a correct citation to a page outside the gold set counts against it. Read it together with groundedness.
- **Cold latency has n=20**: in one process only the first question loads the index, so the cold p95 is not a real percentile.
