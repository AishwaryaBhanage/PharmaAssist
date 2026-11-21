# Eval: sections_rerank_structured, 2026-10-17 19:26 UTC, re-judged 2026-10-17 15:30

- Agent: `claude-sonnet-5-5` (effort medium), index setup `sections_rerank_structured`, max 6 lookups, 25 s deadline
- Judge: `claude-opus-5-5` (effort medium, 1 pass)
- Golden set: `evals/golden.jsonl`, 20 questions, each run once
- Code: commit `5ea6601`
- System under test (agent) commit: `d804f380c9f0f01c96ee9e8db12f8aa2ab8b420b`; evaluation harness: commit `5ea6601`
- Run date: 2026-10-17 19:26 UTC, re-judged 2026-10-17 15:30; per-question results in `results.csv`
- Re-judged from `reports/evals/evalB_ungated_d804f38_answers_2026-10-17_1525` with the current judges; the agent wasn't rerun

## Results

| Metric | Result |
|---|---|
| Accuracy (judge) | 15 correct, 5 partial, 0 incorrect (score 0.875, partial = 0.5) |
| Judge passes unanimous on the grade | 20/20 |
| must_include terms present (judge, paraphrase counts) | 52/54 |
| must_include terms present (literal substring) | 23/54 |
| Recall@5 / @10 (direct hybrid search on the question, PDF gold) | 0.675 / 0.882 |
| Retrieval recall: all gold / PDF pages only (mean, any tool) | 0.865 / 0.912 |
| Gold sources returned by any tool (all questions) | 49/59 |
| Citation precision / recall: all gold (mean) | 0.742 / 0.775 |
| Citation recall: PDF pages only (mean) | 0.824 |
| Citations failing the in-code check | 0 |
| Groundedness (supported claims / claims, mean) | 0.889 |
| Answered without citations | 0 |
| **Safe**: no unsupported content shown (judge found 0 unsupported claims, or abstained) | 18/20 |
| **Useful**: answerable questions that received a non-abstaining answer | 19/19 |
| Over-abstention (abstained or unverified on an answerable question; graded incorrect) | 0 |
| Abstention correct | 20/20 |
| Opens with the assumption (unspecified program) | 4/4 |
| Latency, all | p50 11.7 s, p95 20.1 s (n=20) |
| Latency, cold (index not yet loaded) | p50 22.21 s, p95 22.21 s (n=1) |
| Latency, warm | p50 11.58 s, p95 19.78 s (n=19) |
| Over 30 s | 0 |
| Rendered length incl. citations, words (mean / median / max) | 110.35 / 112.5 / 142 |
| Displayed content, words excl. labels and citations (mean; in 60-120) | None; 0/0 |
| Outcome: answered / answered with claims omitted / abstained (needs review = the last two) | 0 / 0 / 0 |
| Direct claim check label: verified / values_checked / unchecked | 0 / 0 / 0 |
| Flags | none |
| Failures by class | ingested but not retrieved 2, retrieved but answered wrong 3, answered right but cited wrong 5 |
| Cost | agent $1.39 ($0.069/question), judge $0.98, total $2.37 |

## Per question

| ID | Accuracy | Grounded | R@10 | Retrieval | Cite P / R | Abst. | Assum. | Time s | Words | Cost $ | Failure class |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Q01 | partial | 0.889 | 1.0 | 1.0 | 0.5 / 0.4 | True | – | 22.2 | 120 | 0.123 | retrieved but answered wrong |
| Q02 | correct | 1.0 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 12.7 | 107 | 0.091 | – |
| Q03 | correct | 1.0 | 1.0 | 0.857 | 1.0 / 0.571 | True | – | 13.6 | 124 | 0.132 | answered right but cited wrong |
| Q04 | partial | 0.917 | 1.0 | 1.0 | 1.0 / 0.833 | True | – | 13.2 | 129 | 0.171 | retrieved but answered wrong |
| Q05 | correct | 0.778 | 1.0 | 1.0 | 0.8 / 1.0 | True | – | 18.1 | 142 | 0.174 | – |
| Q06 | partial | 0.917 | 0.5 | 0.75 | 0.6 / 0.75 | True | – | 12.6 | 119 | 0.138 | ingested but not retrieved |
| Q07 | partial | 1.0 | 0.25 | 0.25 | 0.2 / 0.25 | True | – | 11.8 | 127 | 0.138 | ingested but not retrieved |
| Q08 | correct | 0.875 | 1.0 | 1.0 | 0.5 / 1.0 | True | – | 10.8 | 115 | 0.115 | – |
| Q09 | correct | 0.778 | 1.0 | 1.0 | 0.5 / 1.0 | True | – | 11.6 | 123 | 0.109 | – |
| Q10 | correct | 0.7 | 0.667 | 1.0 | 0.4 / 0.667 | True | – | 20.0 | 140 | 0.241 | answered right but cited wrong |
| Q11 | correct | 0.833 | 1.0 | 1.0 | 1.0 / 1.0 | True | True | 4.5 | 85 | 0.048 | – |
| Q12 | correct | 0.8 | 1.0 | 0.25 | 1.0 / 0.25 | True | – | 4.5 | 75 | 0.047 | answered right but cited wrong |
| Q13 | correct | 1.0 | 1.0 | 1.0 | 0.6 / 1.0 | True | – | 11.5 | 127 | 0.106 | – |
| Q14 | correct | 0.857 | 0.333 | 0.333 | 1.0 / 0.333 | True | True | 10.9 | 110 | 0.077 | answered right but cited wrong |
| Q15 | partial | 0.778 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 10.4 | 107 | 0.107 | retrieved but answered wrong |
| Q16 | correct | 0.889 | 1.0 | 1.0 | 0.5 / 1.0 | True | True | 12.1 | 90 | 0.120 | – |
| Q17 | correct | 1.0 | 1.0 | 1.0 | 0.5 / 1.0 | True | – | 19.8 | 88 | 0.149 | – |
| Q18 | correct | 0.889 | 1.0 | 1.0 | 1.0 / 1.0 | True | True | 10.6 | 104 | 0.109 | – |
| Q19 | correct | 1.0 | 1.0 | 1.0 | 1.0 / 0.667 | True | – | 11.6 | 99 | 0.108 | answered right but cited wrong |
| Q20 | correct | n/a | – | – | – / – | True | – | 9.9 | 76 | 0.068 | – |

## Lowest-scoring questions

Ranked by accuracy, then groundedness, citation recall and retrieval recall.

- **Q15** (step therapy): partial [retrieved but answered wrong], groundedness 0.778, citation recall 1.0, retrieval 1.0
  - Judge: Correctly says IR tramadol must be tried first and that tramadol ER is non-preferred/ST, but omits ConZip and the PA requirement for patients under 12.
  - Missing terms: ConZip
  - Not fully supported: Tramadol ER is non-preferred with step therapy (ST) on the NYRx PDL, under Opioids – Long-Acting, in the PDL revised 9/14/2026. (partial: The page lists tramadol ER ST as non-preferred, but the legend says this status applies as of 10/22/2026. That is after today (10/17/2026), and the answer presents it as current without noting the effective date.) \| The ST exemption applies to cancer, sickle cell disease, or hospice/palliative care. (partial: The source attaches the exemption to the Clinical Criteria (CC*), not to the step therapy requirement.)
- **Q01** (conflict across versions; synthesis): partial [retrieved but answered wrong], groundedness 0.889, citation recall 0.4, retrieval 1.0
  - Judge: Correct conclusion: start the SGLT2 regardless of A1c, citing 2025 PBM and 2023 CPG. It omits that the older 2020 guide used a metformin-first sequence.
  - Missing terms: older guide metformin-first
  - Not fully supported: Confirm eGFR ≥20 first. (unsupported: No cited source mentions an eGFR threshold for starting SGLT2 inhibitors.)
- **Q06** (multi-document; structured formulary): partial [ingested but not retrieved], groundedness 0.917, citation recall 0.75, retrieval 0.75
  - Judge: PA requirement and commercial-first billing are correct, but the reply omits the VA guidance to avoid the combination and the recommendation for a pharmacist medication review.
  - Not fully supported: Without a TPL claim, NYRx rejects with NCPDP 717 'Client Has Other Insurance'. (unsupported: No cited page mentions NCPDP reject code 717 or this rejection message.)
- **Q04** (conflict across dates; screening vs restriction): partial [retrieved but answered wrong], groundedness 0.917, citation recall 0.833, retrieval 1.0
  - Judge: Covers mandatory DMPs, buprenorphine counting, the MME exclusion, non-FAD status and unblocked MAT, but misdates the memo as 2018 instead of 2019.
  - Not fully supported: The MAT exclusion still applies. (partial: The FAD exclusion for MAT buprenorphine is stated only for plan year 2019, and that memo refers to later Call Letters for changes in 2020 and beyond. The 2022 sheet says only that MAT access should not be impacted; it does not restate the FAD exclusion.)
- **Q07** (synthesis): partial [ingested but not retrieved], groundedness 1.0, citation recall 0.25, retrieval 0.25
  - Judge: Long-term use, BID/TID splitting, and core monitoring are covered, but it omits not stopping on return to non-prescribed use and collaborative discontinuation. COWS, CBC and infectious testing are missing.

## Random sample the judge marked correct

To check the judge isn't too lenient (sample seed 1439).

- **Q13** (prior auth process): correct, groundedness 1.0, citation recall 1.0, retrieval 1.0
  - Judge: Matches reference: prescriber-only requests, call center number, PAXpress, CoverMyMeds, fax form URL, and 72-hour emergency supply. Extra fax-number note doesn't contradict.
- **Q19** (silence vs absence): correct [answered right but cited wrong], groundedness 1.0, citation recall 0.667, retrieval 1.0
  - Judge: States no tiers, Trulicity preferred brand, $1.00 copay, plus exemptions; omits OTC/generic amounts and refusal rule but core facts match.
- **Q05** (multi-document; override and payer coordination): correct, groundedness 0.778, citation recall 1.0, retrieval 1.0
  - Judge: Matches reference: don't bill NYRx, Part D override for new-plan missing history, 7-day/coverage determination option, CMS notice. Extra details don't contradict.
  - Not fully supported: Billing around Part D is treated as fraudulent. (partial: The manual labels bypassing a TPL's payment responsibility as fraudulent billing and calls Medicare 'analogous to TPL'. For Medicare it says only that providers may not circumvent Medicare billing; it doesn't explicitly call that fraud.) \| Keep documentation. (partial: Documenting is described for the 90 MME care coordination edit, not the 7-day edit. The NY manual requires keeping payment information, not documentation of override actions.)

## Caveats

- **The judge is also a Claude model**, so it may share the agent's blind spots. Human spot checks of its grades (the two lists above) are the safeguard.
- **Each question ran once.** The agent isn't deterministic, so a one-question difference between setups may be noise.
- **VA formulary gold** (6 spreadsheet rows, from cells such as A1697:G1697) counts in the all-gold scores; a setup without the formulary lookup can't reach it, so compare setups on the PDF-pages-only scores too. Recall@k covers PDF pages only.
- **Failure classes are assigned by rule** (earliest stage that explains the miss), with ambiguous cases set by hand in `evals/failure_overrides.yaml`.
- **Citation precision is a lower bound**: a correct citation to a page outside the gold set counts against it. Read it together with groundedness.
- **Cold latency has n=1**: in one process only the first question loads the index, so the cold p95 is not a real percentile.
