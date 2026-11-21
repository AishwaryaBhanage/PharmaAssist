# Eval: v2_rerank_base, 2026-10-18 12:25

- Agent: `gpt-5.5 (fallback claude-sonnet-5-5)` (effort medium), index setup `v2_rerank_base`, max 6 lookups, 25 s deadline
- Judge: `claude-opus-5-5` (effort medium, 3 passes)
- Golden set: `evals/golden.jsonl`, 20 questions, each run once
- Code: commit `1443b07` (with uncommitted changes)
- Run date: 2026-10-18 12:25; per-question results in `results.csv`

## Results

| Metric | Result |
|---|---|
| Accuracy (judge) | 8 correct, 12 partial, 0 incorrect (score 0.7, partial = 0.5) |
| Judge passes unanimous on the grade | 18/20 |
| must_include terms present (judge, paraphrase counts) | 50/54 |
| must_include terms present (literal substring) | 20/54 |
| Recall@5 / @10 (direct hybrid search on the question, PDF gold) | 0.711 / 0.846 |
| Retrieval recall: all gold / PDF pages only (mean, any tool) | 0.924 / 0.925 |
| Gold sources returned by any tool (all questions) | 53/59 |
| Citation precision / recall: all gold (mean) | 0.773 / 0.731 |
| Citation recall: PDF pages only (mean) | 0.767 |
| Citations failing the in-code check | 0 |
| Groundedness (supported claims / claims, mean) | 0.867 |
| Answered without citations | 0 |
| **Safe**: no unsupported content shown (judge found 0 unsupported claims, or abstained) | 14/20 |
| **Useful**: answerable questions that received a non-abstaining answer | 19/19 |
| Over-abstention (abstained or unverified on an answerable question; graded incorrect) | 0 |
| Abstention correct | 20/20 |
| Opens with the assumption (unspecified program) | 4/4 |
| Startup warmup before timing (not in any latency) | 0.359 s (store 0.002 s, tables 0.349 s, search 0.008 s) |
| Latency, all | p50 13.93 s, p95 23.5 s (n=20) |
| Latency, cold (index not yet loaded) | p50 13.93 s, p95 23.5 s (n=20) |
| Latency, warm | none |
| Over 30 s | 0 |
| Rendered length incl. citations, words (mean / median / max) | 86.2 / 89.5 / 114 |
| Displayed content, words excl. labels and citations (mean; in 60-120) | 86.2; 19/20 |
| Needs review (not answered, uncited or a flagged citation) | 1 |
| Flags | budget_spent:tool_cap 1 |
| Failures by class | ingested but not retrieved 4, retrieved but answered wrong 8, answered right but cited wrong 3 |
| Cost | agent $2.00 ($0.100/question), judge $2.58, total $4.58 |

## Per question

| ID | Accuracy | Grounded | R@10 | Retrieval | Cite P / R | Abst. | Assum. | Time s | Words | Cost $ | Failure class |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Q01 | partial | 1.0 | 1.0 | 1.0 | 0.667 / 0.4 | True | – | 19.4 | 87 | 0.177 | retrieved but answered wrong |
| Q02 | correct | 1.0 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 11.9 | 80 | 0.150 | – |
| Q03 | correct | 0.857 | 1.0 | 0.714 | 1.0 / 0.571 | True | – | 21.0 | 101 | 0.273 | answered right but cited wrong |
| Q04 | correct | 0.833 | 0.833 | 1.0 | 0.8 / 0.667 | True | – | 23.5 | 90 | 0.425 | answered right but cited wrong |
| Q05 | correct | 0.857 | 1.0 | 1.0 | 0.8 / 1.0 | True | – | 14.8 | 114 | 0.260 | – |
| Q06 | partial | 0.889 | 0.5 | 0.75 | 0.75 / 0.75 | True | – | 14.7 | 94 | 0.248 | ingested but not retrieved |
| Q07 | partial | 1.0 | 0.25 | 0.75 | 0.5 / 0.5 | True | – | 14.9 | 103 | 0.434 | ingested but not retrieved |
| Q08 | partial | 0.75 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 11.1 | 97 | 0.198 | retrieved but answered wrong |
| Q09 | correct | 0.833 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 14.7 | 90 | 0.253 | – |
| Q10 | partial | 1.0 | 1.0 | 0.667 | 0.333 / 0.333 | True | – | 16.9 | 88 | 0.304 | ingested but not retrieved |
| Q11 | partial | 1.0 | 1.0 | 1.0 | 1.0 / 1.0 | True | True | 7.9 | 88 | 0.110 | retrieved but answered wrong |
| Q12 | correct | 1.0 | 1.0 | 1.0 | 0.667 / 0.5 | True | – | 11.3 | 86 | 0.152 | answered right but cited wrong |
| Q13 | partial | 0.857 | 0.667 | 1.0 | 0.667 / 0.667 | True | – | 9.1 | 92 | 0.209 | retrieved but answered wrong |
| Q14 | partial | 0.857 | 0.333 | 0.667 | 0.5 / 0.333 | True | True | 15.2 | 94 | 0.192 | ingested but not retrieved |
| Q15 | partial | 0.857 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 13.1 | 83 | 0.188 | retrieved but answered wrong |
| Q16 | partial | 0.5 | 1.0 | 1.0 | 0.333 / 0.5 | True | True | 11.1 | 89 | 0.237 | retrieved but answered wrong |
| Q17 | correct | 0.875 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 23.9 | 78 | 0.341 | – |
| Q18 | partial | 1.0 | 0.5 | 1.0 | 0.667 / 1.0 | True | True | 11.4 | 92 | 0.199 | retrieved but answered wrong |
| Q19 | partial | 0.5 | 1.0 | 1.0 | 1.0 / 0.667 | True | – | 8.9 | 72 | 0.144 | retrieved but answered wrong |
| Q20 | correct | n/a | – | – | – / – | True | – | 10.7 | 6 | 0.087 | – |

## Lowest-scoring questions

Ranked by accuracy, then groundedness, citation recall and retrieval recall.

- **Q16** (reject code): partial [retrieved but answered wrong], groundedness 0.5, citation recall 0.5, retrieval 1.0
  - Judge: DAW 9 and the DAW 1 exception are correct, but it omits that BLTG brands pay brand rate or U&C with generic copay. Code 22 is described only as a 'BLTG DAW edit'.
  - Not fully supported: On NY Medicaid, reject 22 on Victoza® is the BLTG DAW edit. (unsupported: No cited page mentions reject code 22 or describes a BLTG DAW edit.) \| Rebill brand Victoza® with DAW 9 ("Substitution Allowed by Prescriber but Plan Requests Brand"). (unsupported: The cited pages give no DAW codes. p77 says only that BLTG brands do not require DAW or Brand Medically Necessary on the prescription.) \| Do not use DAW 1 unless the Rx says Brand Medically Necessary; that is the stated exception. (unsupported: p77 states no such exception and does not mention DAW 1. It says BLTG brands do not require DAW or Brand Medically Necessary.)
- **Q19** (silence vs absence): partial [retrieved but answered wrong], groundedness 0.5, citation recall 0.667, retrieval 1.0
  - Judge: Correctly gives $1.00 copay for preferred brand Trulicity, but never states NY Medicaid has no copay tiers; it adopts the tier framing.
  - Missing terms: no tiers
  - Not fully supported: NYRx copay policy sets $1.00 for preferred brand-name drugs, so the copay is $1.00. (unsupported: The cited pharmacy manual page says NY Medicaid charges co-payments for many drugs but gives no amounts; no $1.00 figure for preferred brands appears.) \| The $1.00 copay applies unless the member or service is copay-exempt or the member has met the quarterly copay maximum. (unsupported: Neither cited page mentions copay exemptions or a quarterly copay maximum.)
- **Q08** (structured claim code; conditional policy): partial [retrieved but answered wrong], groundedness 0.75, citation recall 1.0, retrieval 1.0
  - Judge: NP in 439-E4, SCC 18, the three conditions, 30-day limit and call-the-Department fallback are right, but it widens eligibility to NH/N1–N9 where the reference specifies only 'NH'.
  - Not fully supported: The member must have been recently admitted to an eligible LTC facility, with eligibility returning NH/N1–N9. (partial: The New Patient conditions specify that "NH" returns on the eligibility response. N1–N9 appear only in the general LTC section applicability statement, not in the NP override conditions.) \| Submit Submission Clarification Code 18 in field 420-DK. (partial: The source gives SCC 18 (LTC Patient Admit/Readmit Indicator) but does not give the field number 420-DK.)
- **Q14** (quantity limit): partial [ingested but not retrieved], groundedness 0.857, citation recall 0.333, retrieval 0.667
  - Judge: Correctly states NY Medicaid assumption, no QL listed, preferred with clinical criteria, and call center number, but omits the distinction from Wegovy's F/Q/D criteria and lifetime limit.
  - Not fully supported: The NY Medicaid Clinical Call Center number is 877-309-9493. (unsupported: Neither cited page gives a Clinical Call Center phone number.)
- **Q13** (prior auth process): partial [retrieved but answered wrong], groundedness 0.857, citation recall 0.667, retrieval 1.0
  - Judge: Prescriber-only rule, call center number, PAXpress, CoverMyMeds and 72-hour supply are correct, but the fax form isn't the Standardized PA form and the URL differs from the reference.
  - Not fully supported: For a non-preferred PDP drug, PA is required and is handled through NYRx/Prime. (partial: The PDL says non-preferred drugs require PA and that NYRx accepts PA requests. Prime appears only in an Education & Outreach email address; no source names it as the PA processor.)

## Random sample the judge marked correct

To check the judge isn't too lenient (sample seed 6239).

- **Q20** (absence): correct, groundedness n/a, citation recall –, retrieval –
  - Judge: Correctly declines; states no answer found in knowledge base, matching reference that the documents don't cover this. Lacks redirect, but conclusion matches.
- **Q17** (effective dates): correct, groundedness 0.875, citation recall 1.0, retrieval 1.0
  - Judge: Lists all five products with correct direction and effective date 10/22/2026, notes no GLP-1/DPP-4/SGLT2 changes; consistent with reference.
  - Not fully supported: The DPP-4, long-acting insulin, and insulin mix class pages show no 10/22/2026 preferred-status changes. (unsupported: Neither cited page covers the DPP-4, long-acting insulin, or insulin mix classes.)
- **Q02** (conflict across versions): correct, groundedness 1.0, citation recall 1.0, retrieval 1.0
  - Judge: Matches reference: flag, 2025 guide discontinues DPP-4 with prandial insulin, 2020 said continue, newer applies, no independent discontinuation.

## Caveats

- **The judge is also a Claude model**, so it may share the agent's blind spots. Human spot checks of its grades (the two lists above) are the safeguard.
- **Each question ran once.** The agent isn't deterministic, so a one-question difference between setups may be noise.
- **VA formulary gold** (6 spreadsheet rows, from cells such as A1697:G1697) counts in the all-gold scores; a setup without the formulary lookup can't reach it, so compare setups on the PDF-pages-only scores too. Recall@k covers PDF pages only.
- **Failure classes are assigned by rule** (earliest stage that explains the miss), with ambiguous cases set by hand in `evals/failure_overrides.yaml`.
- **Citation precision is a lower bound**: a correct citation to a page outside the gold set counts against it. Read it together with groundedness.
- **Cold latency has n=20**: in one process only the first question loads the index, so the cold p95 is not a real percentile.
