# Eval: sections_rerank_structured, 2026-10-16 12:41

- Agent: `claude-sonnet-5-5` (effort medium), index setup `sections_rerank_structured`, max 6 lookups, 25 s deadline
- Judge: `claude-opus-5-5` (effort medium)
- Golden set: `evals/golden.jsonl`, 20 questions, each run once
- Code: commit `36bddaa` (with uncommitted changes)
- Run date: 2026-10-16 12:41; per-question results in `results.csv`

## Results

| Metric | Result |
|---|---|
| Accuracy (judge) | 13 correct, 6 partial, 1 incorrect (score 0.8, partial = 0.5) |
| Judge passes unanimous on the grade | 18/20 |
| must_include terms present (judge, paraphrase counts) | 51/54 |
| must_include terms present (literal substring) | 22/54 |
| Recall@5 / @10 (direct hybrid search on the question, PDF gold) | 0.675 / 0.882 |
| Retrieval recall: all gold / PDF pages only (mean, any tool) | 0.805 / 0.852 |
| Gold sources returned by any tool (all questions) | 44/59 |
| Citation precision / recall: all gold (mean) | 0.767 / 0.766 |
| Citation recall: PDF pages only (mean) | 0.815 |
| Citations failing the in-code check | 0 |
| Groundedness (supported claims / claims, mean) | 0.889 |
| Answered without citations | 0 |
| Abstention correct | 20/20 |
| Opens with the assumption (unspecified program) | 4/4 |
| Latency, all | p50 9.99 s, p95 19.97 s (n=20) |
| Latency, cold (index not yet loaded) | p50 19.83 s, p95 19.83 s (n=1) |
| Latency, warm | p50 9.85 s, p95 15.79 s (n=19) |
| Over 30 s | 0 |
| Words (mean; within 60–120) | 110.15; 13/20 |
| Flags | none |
| Failures by class | ingested but not retrieved 5, retrieved but answered wrong 2, answered right but cited wrong 4 |
| Cost | agent $1.04 ($0.052/question), judge $3.09, total $4.13 |

## Per question

| ID | Accuracy | Grounded | R@10 | Retrieval | Cite P / R | Abst. | Assum. | Time s | Words | Cost $ | Failure class |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Q01 | partial | 0.875 | 1.0 | 0.6 | 0.4 / 0.4 | True | – | 19.8 | 129 | 0.225 | ingested but not retrieved |
| Q02 | correct | 0.75 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 9.6 | 99 | 0.156 | – |
| Q03 | correct | 0.875 | 1.0 | 0.857 | 1.0 / 0.571 | True | – | 15.0 | 133 | 0.235 | answered right but cited wrong |
| Q04 | partial | 0.917 | 1.0 | 0.667 | 1.0 / 0.667 | True | – | 10.8 | 124 | 0.283 | ingested but not retrieved |
| Q05 | correct | 1.0 | 1.0 | 1.0 | 0.75 / 0.75 | True | – | 13.6 | 132 | 0.229 | answered right but cited wrong |
| Q06 | partial | 1.0 | 0.5 | 0.75 | 0.6 / 0.75 | True | – | 11.2 | 119 | 0.265 | ingested but not retrieved |
| Q07 | partial | 0.846 | 0.25 | 0.5 | 0.4 / 0.5 | True | – | 10.2 | 132 | 0.314 | ingested but not retrieved |
| Q08 | partial | 1.0 | 1.0 | 1.0 | 0.5 / 1.0 | True | – | 9.3 | 116 | 0.193 | retrieved but answered wrong |
| Q09 | correct | 0.8 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 8.9 | 107 | 0.176 | – |
| Q10 | correct | 0.8 | 0.667 | 1.0 | 0.5 / 1.0 | True | – | 14.8 | 137 | 0.345 | – |
| Q11 | correct | 0.857 | 1.0 | 1.0 | 1.0 / 1.0 | True | True | 5.2 | 89 | 0.118 | – |
| Q12 | correct | 0.833 | 1.0 | 0.25 | 1.0 / 0.25 | True | – | 4.6 | 90 | 0.121 | answered right but cited wrong |
| Q13 | correct | 0.9 | 1.0 | 1.0 | 0.75 / 1.0 | True | – | 8.6 | 117 | 0.206 | – |
| Q14 | correct | 1.0 | 0.333 | 0.333 | 1.0 / 0.333 | True | True | 8.1 | 100 | 0.155 | answered right but cited wrong |
| Q15 | correct | 0.833 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 9.5 | 116 | 0.200 | – |
| Q16 | correct | 0.889 | 1.0 | 1.0 | 0.667 / 1.0 | True | True | 10.1 | 96 | 0.215 | – |
| Q17 | correct | 0.875 | 1.0 | 1.0 | 0.5 / 1.0 | True | – | 14.5 | 81 | 0.204 | – |
| Q18 | partial | 1.0 | 1.0 | 1.0 | 0.5 / 1.0 | True | True | 9.8 | 121 | 0.269 | retrieved but answered wrong |
| Q19 | incorrect | 0.833 | 1.0 | 0.333 | 1.0 / 0.333 | True | – | 22.7 | 97 | 0.154 | ingested but not retrieved |
| Q20 | correct | n/a | – | – | – / – | True | – | 7.9 | 68 | 0.071 | – |

## Lowest-scoring questions

Ranked by accuracy, then groundedness, citation recall and retrieval recall.

- **Q19** (silence vs absence): incorrect [ingested but not retrieved], groundedness 0.833, citation recall 0.333, retrieval 0.333
  - Judge: Says documents give no copay amount, contradicting reference's $1.00 flat copay for preferred brands; declines the answerable copay part.
  - Missing terms: $1.00
  - Not fully supported: NYRx doesn't use copay tiers for the PDL; it uses preferred/non-preferred status. (partial: The page uses preferred/non-preferred status, but it doesn't say that NYRx doesn't use copay tiers.)
- **Q07** (synthesis): partial [ingested but not retrieved], groundedness 0.846, citation recall 0.5, retrieval 0.5
  - Judge: Says long-term use is fine but omits indefinite continuation and not stopping on return to use. Monitoring omits COWS, CBC and infectious disease testing; 'possibly preferred' blurs evidence neutrality.
  - Not fully supported: Avoid benzodiazepines and other CNS depressants. (partial: The CPG recommends against concurrent benzodiazepines and opioids. No cited page mentions other CNS depressants.) \| The CPG advises urine drug screening for long-term opioid therapy. (unsupported: The cited CPG pages do not mention UDS. The UDS recommendation appears only in the PBM clinician guide (IB 10-1497), not the CPG.)
- **Q01** (conflict across versions; synthesis): partial [ingested but not retrieved], groundedness 0.875, citation recall 0.4, retrieval 0.6
  - Judge: Correct conclusion with 2025 regardless-of-A1c guidance, empagliflozin/canagliflozin, and CPG support, but omits the older 2020 guide's conflicting metformin-first sequence.
  - Missing terms: older guide metformin-first
  - Not fully supported: The VA/DoD CPG (2023) suggests considering an SGLT2 or GLP-1 RA even when A1c is at goal, using shared decision-making. (partial: The CPG recommendation is limited to adults with T2DM who have cardiovascular or renal disease; the answer omits this condition.)
- **Q04** (conflict across dates; screening vs restriction): partial [ingested but not retrieved], groundedness 0.917, citation recall 0.667, retrieval 0.667
  - Judge: Counting, MME exclusion, non-FAD MAT status and no blocking are all correct. It wrongly calls the 2019 memo superseded; that memo itself anticipated mandatory DMPs from 2022.
  - Not fully supported: The 2019 memo describes DMPs as optional, and this wording is superseded by the newer 2022 rule. (unsupported: The cited 2019 memo pages contain no wording describing DMPs as optional, so there is no conflict on the cited pages to resolve.)
- **Q06** (multi-document; structured formulary): partial [ingested but not retrieved], groundedness 1.0, citation recall 0.75, retrieval 0.75
  - Judge: Correctly says PA is required for concurrent GLP-1 + DPP-4 use and to bill the commercial plan first. Omits the VA advice to avoid the combination and the recommended pharmacist medication review.

## Random sample the judge marked correct

To check the judge isn't too lenient (sample seed 8109).

- **Q05** (multi-document; override and payer coordination): correct [answered right but cited wrong], groundedness 1.0, citation recall 0.75, retrieval 1.0
  - Judge: Says don't bill NYRx, gives Part D override with opioid history, 7-day dispense or coverage determination, and the CMS rights notice; extra detail doesn't contradict.
- **Q03** (apparent conflict; dose vs coverage limit; multi-document): correct [answered right but cited wrong], groundedness 0.875, citation recall 0.571, retrieval 0.857
  - Judge: Matches reference: 32 mg/day fits NYRx QL with no PA, VA 24 mg is a usual max allowing higher with monitoring, patch is a pain product and not a substitute.
  - Not fully supported: The documents show the buprenorphine patch is not FDA-approved for OUD. (partial: The pain guide lists Butrans as FDA-approved for chronic pain, and the cited OUD page does not list the patch. But that OUD page is a continuation of the table, and no cited page explicitly says the patch is not approved for OUD.)
- **Q16** (reject code): correct, groundedness 0.889, citation recall 1.0, retrieval 1.0
  - Judge: States NY Medicaid assumption, reject 22 as a missing/invalid DAW code, and resubmission with DAW 9 (or DAW 1 if brand medically necessary), matching the reference.
  - Not fully supported: Generic liraglutide is non-preferred and needs PA. (partial: The page layout lists liraglutide (gen Victoza) on the non-preferred side, but the cited text does not state that non-preferred drugs require PA.)

## Caveats

- **The judge is also a Claude model**, so it may share the agent's blind spots. Human spot checks of its grades (the two lists above) are the safeguard.
- **Each question ran once.** The agent isn't deterministic, so a one-question difference between setups may be noise.
- **VA formulary gold** (6 spreadsheet rows, from cells such as A1697:G1697) counts in the all-gold scores; a setup without the formulary lookup can't reach it, so compare setups on the PDF-pages-only scores too. Recall@k covers PDF pages only.
- **Failure classes are assigned by rule** (earliest stage that explains the miss), with ambiguous cases set by hand in `evals/failure_overrides.yaml`.
- **Citation precision is a lower bound**: a correct citation to a page outside the gold set counts against it. Read it together with groundedness.
- **Cold latency has n=1**: in one process only the first question loads the index, so the cold p95 is not a real percentile.
