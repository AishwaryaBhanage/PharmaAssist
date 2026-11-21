# Eval: sections_rerank_structured, 2026-10-16 20:54

- Agent: `claude-sonnet-5-5` (effort medium), index setup `sections_rerank_structured`, max 6 lookups, 25 s deadline
- Judge: `claude-opus-5-5` (effort medium)
- Golden set: `evals/golden.jsonl`, 20 questions, each run once
- Code: commit `5962202`
- Run date: 2026-10-16 20:54; per-question results in `results.csv`

## Results

| Metric | Result |
|---|---|
| Accuracy (judge) | 14 correct, 6 partial, 0 incorrect (score 0.85, partial = 0.5) |
| Judge passes unanimous on the grade | 20/20 |
| must_include terms present (judge, paraphrase counts) | 50/54 |
| must_include terms present (literal substring) | 21/54 |
| Recall@5 / @10 (direct hybrid search on the question, PDF gold) | 0.675 / 0.882 |
| Retrieval recall: all gold / PDF pages only (mean, any tool) | 0.792 / 0.839 |
| Gold sources returned by any tool (all questions) | 43/59 |
| Citation precision / recall: all gold (mean) | 0.725 / 0.753 |
| Citation recall: PDF pages only (mean) | 0.802 |
| Citations failing the in-code check | 0 |
| Groundedness (supported claims / claims, mean) | 0.859 |
| Answered without citations | 0 |
| Abstention correct | 20/20 |
| Opens with the assumption (unspecified program) | 4/4 |
| Latency, all | p50 9.24 s, p95 13.89 s (n=20) |
| Latency, cold (index not yet loaded) | p50 17.0 s, p95 17.0 s (n=1) |
| Latency, warm | p50 9.19 s, p95 13.42 s (n=19) |
| Over 30 s | 0 |
| Words (mean; within 60–120) | 110.4; 15/20 |
| Flags | none |
| Failures by class | ingested but not retrieved 5, retrieved but answered wrong 1, answered right but cited wrong 4 |
| Cost | agent $1.00 ($0.050/question), judge $3.10, total $4.11 |

## Per question

| ID | Accuracy | Grounded | R@10 | Retrieval | Cite P / R | Abst. | Assum. | Time s | Words | Cost $ | Failure class |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Q01 | partial | 0.778 | 1.0 | 0.6 | 0.5 / 0.4 | True | – | 17.0 | 107 | 0.239 | ingested but not retrieved |
| Q02 | correct | 1.0 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 9.3 | 99 | 0.165 | – |
| Q03 | correct | 0.909 | 1.0 | 0.857 | 1.0 / 0.571 | True | – | 10.0 | 132 | 0.197 | answered right but cited wrong |
| Q04 | partial | 0.9 | 1.0 | 0.667 | 0.8 / 0.667 | True | – | 10.5 | 115 | 0.307 | ingested but not retrieved |
| Q05 | correct | 0.667 | 1.0 | 1.0 | 0.75 / 0.75 | True | – | 13.4 | 143 | 0.285 | answered right but cited wrong |
| Q06 | partial | 0.769 | 0.5 | 0.75 | 0.6 / 0.75 | True | – | 11.6 | 137 | 0.277 | ingested but not retrieved |
| Q07 | partial | 0.833 | 0.25 | 0.25 | 0.2 / 0.25 | True | – | 10.8 | 154 | 0.287 | ingested but not retrieved |
| Q08 | correct | 1.0 | 1.0 | 1.0 | 0.5 / 1.0 | True | – | 8.1 | 106 | 0.179 | – |
| Q09 | correct | 1.0 | 1.0 | 1.0 | 0.5 / 1.0 | True | – | 8.6 | 114 | 0.160 | – |
| Q10 | correct | 0.889 | 0.667 | 1.0 | 0.5 / 1.0 | True | – | 13.7 | 124 | 0.323 | – |
| Q11 | correct | 0.667 | 1.0 | 1.0 | 1.0 / 1.0 | True | True | 4.7 | 99 | 0.125 | – |
| Q12 | correct | 0.8 | 1.0 | 0.25 | 1.0 / 0.25 | True | – | 4.6 | 81 | 0.119 | answered right but cited wrong |
| Q13 | correct | 0.9 | 1.0 | 1.0 | 0.75 / 1.0 | True | – | 9.0 | 110 | 0.208 | – |
| Q14 | correct | 0.889 | 0.333 | 0.333 | 1.0 / 0.333 | True | True | 8.1 | 100 | 0.163 | answered right but cited wrong |
| Q15 | correct | 1.0 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 8.1 | 105 | 0.185 | – |
| Q16 | correct | 1.0 | 1.0 | 1.0 | 0.667 / 1.0 | True | True | 9.2 | 106 | 0.213 | – |
| Q17 | correct | 0.714 | 1.0 | 1.0 | 0.5 / 1.0 | True | – | 12.3 | 70 | 0.207 | – |
| Q18 | partial | 0.778 | 1.0 | 1.0 | 0.5 / 1.0 | True | True | 10.2 | 115 | 0.239 | retrieved but answered wrong |
| Q19 | partial | 0.833 | 1.0 | 0.333 | 1.0 / 0.333 | True | – | 8.5 | 109 | 0.155 | ingested but not retrieved |
| Q20 | correct | n/a | – | – | – / – | True | – | 7.8 | 82 | 0.072 | – |

## Lowest-scoring questions

Ranked by accuracy, then groundedness, citation recall and retrieval recall.

- **Q06** (multi-document; structured formulary): partial [ingested but not retrieved], groundedness 0.769, citation recall 0.75, retrieval 0.75
  - Judge: PA for concurrent GLP-1/DPP-4 use and billing commercial first are correct, but it omits the VA guidance to avoid the combination and the recommended pharmacist medication review.
  - Not fully supported: Ozempic pen is preferred on the PDL with no PA flag. (partial: The PDL marks status as 'Preferred as of 10/22/2026', which is after today (2026-10-16). The answer presents it as current without noting this.) \| Januvia is also preferred on the PDL. (partial: The listed status takes effect 10/22/2026, which is after today. The DO/BLTG flags on Januvia are also not mentioned.) \| The PA is requested through ePA/PAXpress. (partial: The cited page mentions ePA via CoverMyMeds; PAXpress is not mentioned.)
- **Q01** (conflict across versions; synthesis): partial [ingested but not retrieved], groundedness 0.778, citation recall 0.4, retrieval 0.6
  - Judge: Correct conclusion: SGLT2 can start now regardless of A1c, per the 2025 guide. Omits the version conflict with the older 2020 guide's metformin-first sequence.
  - Missing terms: older guide metformin-first
  - Not fully supported: Empagliflozin TAB has no restriction listed (the PA column is blank) in the 09/2026 VANF. (partial: The Restriction field is blank, but the formulary row has no PA column; the column is labeled 'Restriction'.) \| Check that eGFR is ≥20 before starting. (unsupported: No cited source gives an eGFR threshold for empagliflozin.)
- **Q18** (no program stated): partial [retrieved but answered wrong], groundedness 0.778, citation recall 1.0, retrieval 1.0
  - Judge: Correctly assumes NY Medicaid, says MAT needs no PA, and covers the patch, but omits that Butrans and Belbuca are non-preferred and need PA.
  - Missing terms: Butrans/Belbuca non-preferred
  - Not fully supported: Buprenorphine patch is preferred on the PDL. (partial: The PDL lists preferred status as of 10/22/2026, which is after today's date (2026-10-16). The answer does not mention that this status is not yet in effect.) \| Long-acting opioid class criteria require PA for new long-acting opioid starts. (partial: The PDL requires PA for long-acting initiation specifically in opioid-naïve patients, and for an additional long-acting opioid in patients already on one. It does not require PA for all new starts.)
- **Q07** (synthesis): partial [ingested but not retrieved], groundedness 0.833, citation recall 0.25, retrieval 0.25
  - Judge: Split dosing and monitoring are covered. It never says buprenorphine continues indefinitely or shouldn't stop after return to use; monitoring omits COWS, CBC and infectious disease testing.
  - Missing terms: continue indefinitely
  - Not fully supported: The CPG rates buprenorphine, methadone and XR-naltrexone as equivalent for patients with OUD and co-occurring chronic pain (insufficient evidence). (partial: The CPG says there is insufficient evidence to recommend any one over the others (neither for nor against). It does not call them equivalent.) \| SUD is a relative contraindication only. (unsupported: No cited source calls SUD a relative contraindication. The CPG gives a 'Strong against' recommendation for long-term opioid therapy in SUD.)
- **Q19** (silence vs absence): partial [ingested but not retrieved], groundedness 0.833, citation recall 0.333, retrieval 0.333
  - Judge: Correctly says no tiers and identifies Trulicity as preferred, but omits the flat $1.00 copay the reference gives, leaving the copay question unanswered.
  - Missing terms: $1.00
  - Not fully supported: The Part D documents cover opioid policy only and have no formulary tiers. (unsupported: No Part D document is cited, so this description of the Part D documents can't be checked.)

## Random sample the judge marked correct

To check the judge isn't too lenient (sample seed 3476).

- **Q20** (absence): correct, groundedness n/a, citation recall –, retrieval –
  - Judge: Correctly states the documents don't cover pediatric amoxicillin otitis dosing, notes corpus scope and the H. pylori listing, and redirects to a pediatric reference.
- **Q17** (effective dates): correct, groundedness 0.714, citation recall 1.0, retrieval 1.0
  - Judge: Lists all changes: Humalog products and glucagon/Gvoke becoming preferred, insulin aspart non-preferred, effective 10/22/2026; notes no GLP-1/SGLT2/DPP-4 changes.
  - Not fully supported: There are no flagged changes in the biguanide or TZD classes. (unsupported: None of the cited pages cover biguanide or TZD classes.) \| Non-preferred drugs need PA. (unsupported: The cited pages show a PA fax form link but do not state that non-preferred drugs require PA.)
- **Q12** (different programs (not a conflict)): correct [answered right but cited wrong], groundedness 0.8, citation recall 0.25, retrieval 0.25
  - Judge: States Ozempic pen preferred with clinical criteria (covered indication, PA with DPP-4), tablets non-preferred, and VA formulary doesn't apply. Matches reference.
  - Not fully supported: Ozempic tablets are non-preferred, so PA is required (partial: The page lists Ozempic tablets as non-preferred but does not explicitly state that non-preferred status requires PA.)

## Caveats

- **The judge is also a Claude model**, so it may share the agent's blind spots. Human spot checks of its grades (the two lists above) are the safeguard.
- **Each question ran once.** The agent isn't deterministic, so a one-question difference between setups may be noise.
- **VA formulary gold** (6 spreadsheet rows, from cells such as A1697:G1697) counts in the all-gold scores; a setup without the formulary lookup can't reach it, so compare setups on the PDF-pages-only scores too. Recall@k covers PDF pages only.
- **Failure classes are assigned by rule** (earliest stage that explains the miss), with ambiguous cases set by hand in `evals/failure_overrides.yaml`.
- **Citation precision is a lower bound**: a correct citation to a page outside the gold set counts against it. Read it together with groundedness.
- **Cold latency has n=1**: in one process only the first question loads the index, so the cold p95 is not a real percentile.
