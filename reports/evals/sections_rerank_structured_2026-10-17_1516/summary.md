# Eval: sections_rerank_structured, 2026-10-17 15:16

- Agent: `claude-sonnet-5-5` (effort medium), index setup `sections_rerank_structured`, max 6 lookups, 25 s deadline
- Judge: `claude-opus-5-5` (effort medium, 1 pass)
- Golden set: `evals/golden.jsonl`, 20 questions, each run once
- Code: commit `5ea6601`
- Run date: 2026-10-17 15:16; per-question results in `results.csv`

## Results

| Metric | Result |
|---|---|
| Accuracy (judge) | 4 correct, 4 partial, 12 incorrect (score 0.3, partial = 0.5) |
| Judge passes unanimous on the grade | 20/20 |
| must_include terms present (judge, paraphrase counts) | 19/54 |
| must_include terms present (literal substring) | 10/54 |
| Recall@5 / @10 (direct hybrid search on the question, PDF gold) | 0.675 / 0.882 |
| Retrieval recall: all gold / PDF pages only (mean, any tool) | 0.892 / 0.925 |
| Gold sources returned by any tool (all questions) | 51/59 |
| Citation precision / recall: all gold (mean) | 0.905 / 0.289 |
| Citation recall: PDF pages only (mean) | 0.289 |
| Citations failing the in-code check | 0 |
| Groundedness (supported claims / claims, mean) | 0.876 |
| Answered without citations | 0 |
| **Safe**: no unsupported content shown (judge found 0 unsupported claims, or abstained) | 20/20 |
| **Useful**: answerable questions that received a non-abstaining answer | 7/19 |
| Over-abstention (abstained or unverified on an answerable question; graded incorrect) | 12 |
| Abstention correct | 8/20 |
| Opens with the assumption (unspecified program) | 0/4 |
| Startup warmup before timing (not in any latency) | 9.552 s (drug_tables 0.027 s, drug_vocabulary 0.007 s, index 9.243 s) |
| Latency, all | p50 12.55 s, p95 20.12 s (n=20) |
| Latency, cold (index not yet loaded) | none |
| Latency, warm | p50 12.55 s, p95 20.12 s (n=20) |
| Over 30 s | 0 |
| Rendered length incl. citations, words (mean / median / max) | 61.45 / 28.5 / 161 |
| Displayed content, words excl. labels and citations (mean; in 60-120) | 54.9; 5/20 |
| Outcome: answered / answered with claims omitted / abstained (needs review = the last two) | 0 / 7 / 13 |
| Direct claim check label: verified / values_checked / unchecked | 0 / 7 / 0 |
| Offline audit of shown claims: unsupported / partially supported / audited | 0 / 4 / 20 (audit cost $0.35) |
| Flags | none |
| Failures by class | ingested but not retrieved 5, retrieved but answered wrong 11, answered right but cited wrong 1 |
| Cost | agent $1.63 ($0.081/question), judge $0.36, total $1.99 |

## Per question

| ID | Accuracy | Grounded | R@10 | Retrieval | Cite P / R | Abst. | Assum. | Time s | Words | Cost $ | Failure class |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Q01 | incorrect | n/a | 1.0 | 1.0 | – / 0.0 | False | – | 15.4 | 26 | 0.079 | retrieved but answered wrong |
| Q02 | correct | 1.0 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 11.7 | 127 | 0.118 | – |
| Q03 | incorrect | n/a | 1.0 | 0.857 | – / 0.0 | False | – | 22.3 | 29 | 0.140 | ingested but not retrieved |
| Q04 | incorrect | n/a | 1.0 | 1.0 | – / 0.0 | False | – | 13.3 | 28 | 0.127 | retrieved but answered wrong |
| Q05 | incorrect | n/a | 1.0 | 1.0 | – / 0.0 | False | – | 19.4 | 31 | 0.131 | retrieved but answered wrong |
| Q06 | incorrect | n/a | 0.5 | 0.75 | – / 0.0 | False | – | 13.2 | 25 | 0.083 | ingested but not retrieved |
| Q07 | incorrect | n/a | 0.25 | 0.75 | – / 0.0 | False | – | 13.4 | 25 | 0.099 | ingested but not retrieved |
| Q08 | partial | 1.0 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 12.0 | 75 | 0.092 | retrieved but answered wrong |
| Q09 | incorrect | n/a | 1.0 | 1.0 | – / 0.0 | False | – | 12.4 | 28 | 0.076 | retrieved but answered wrong |
| Q10 | partial | 0.833 | 0.667 | 1.0 | 0.333 / 0.333 | True | – | 20.0 | 120 | 0.208 | retrieved but answered wrong |
| Q11 | incorrect | n/a | 1.0 | 1.0 | – / 0.0 | False | False | 5.6 | 25 | 0.032 | retrieved but answered wrong |
| Q12 | incorrect | n/a | 1.0 | 0.25 | – / 0.0 | False | – | 5.2 | 29 | 0.028 | ingested but not retrieved |
| Q13 | partial | 1.0 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 12.7 | 158 | 0.110 | retrieved but answered wrong |
| Q14 | incorrect | n/a | 0.333 | 0.333 | – / 0.0 | False | False | 11.8 | 25 | 0.079 | ingested but not retrieved |
| Q15 | partial | 0.5 | 1.0 | 1.0 | 1.0 / 0.5 | True | – | 11.0 | 161 | 0.102 | retrieved but answered wrong |
| Q16 | incorrect | n/a | 1.0 | 1.0 | – / 0.0 | False | False | 13.1 | 25 | 0.077 | retrieved but answered wrong |
| Q17 | correct | 1.0 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 16.7 | 132 | 0.155 | – |
| Q18 | incorrect | n/a | 1.0 | 1.0 | – / 0.0 | False | False | 12.1 | 25 | 0.096 | retrieved but answered wrong |
| Q19 | correct | 0.8 | 1.0 | 1.0 | 1.0 / 0.667 | True | – | 10.1 | 110 | 0.100 | answered right but cited wrong |
| Q20 | correct | n/a | – | – | – / – | True | – | 8.8 | 25 | 0.053 | – |

## Lowest-scoring questions

Ranked by accuracy, then groundedness, citation recall and retrieval recall.

- **Q12** (different programs (not a conflict)): incorrect [ingested but not retrieved], groundedness n/a, citation recall 0.0, retrieval 0.25
  - Judge: Declines an answerable question; omits that Ozempic pen is preferred on NYRx PDL and that VA formulary doesn't apply to Medicaid patients.
  - Missing terms: Ozempic pen preferred; VA formulary doesn't apply
- **Q14** (quantity limit): incorrect [ingested but not retrieved], groundedness n/a, citation recall 0.0, retrieval 0.333
  - Judge: Declines an answerable question; fails to assume NY Medicaid or state that no F/Q/D quantity limit is listed for Ozempic pens.
  - Missing terms: Assuming NY Medicaid; no QL listed
- **Q06** (multi-document; structured formulary): incorrect [ingested but not retrieved], groundedness n/a, citation recall 0.0, retrieval 0.75
  - Judge: Declines an answerable question; omits PA requirement for concurrent GLP-1 + DPP-4 use and billing commercial insurer first (Medicaid payer of last resort).
  - Missing terms: PA for concurrent GLP-1 and DPP-4; commercial insurer first
- **Q07** (synthesis): incorrect [ingested but not retrieved], groundedness n/a, citation recall 0.0, retrieval 0.75
  - Judge: Declines an answerable question; omits indefinite continuation, BID/TID divided dosing, and monitoring requirements stated in the reference.
  - Missing terms: continue indefinitely; divided dosing; monitoring
- **Q03** (apparent conflict; dose vs coverage limit; multi-document): incorrect [ingested but not retrieved], groundedness n/a, citation recall 0.0, retrieval 0.857
  - Judge: Declines an answerable question; omits that 32 mg fits NYRx limits, VA 24 mg is a usual max, and Butrans patch isn't an OUD substitute.
  - Missing terms: 32 mg; usual maximum; not interchangeable

## Random sample the judge marked correct

To check the judge isn't too lenient (sample seed 9488).

- **Q02** (conflict across versions): correct, groundedness 1.0, citation recall 1.0, retrieval 1.0
  - Judge: Flags for pharmacist, cites 2025 guide discontinuing DPP-4 with prandial insulin over 2020 continue advice; page citation differences are immaterial.
- **Q19** (silence vs absence): correct [answered right but cited wrong], groundedness 0.8, citation recall 0.667, retrieval 1.0
  - Judge: States flat copay instead of tiers, $1.00 for preferred brand, Trulicity preferred; mentions exemptions. Omits other copay amounts and refusal rule, which are minor here.
  - Not fully supported: NY Medicaid uses a flat copay rather than tiers. (partial: The page lists fixed copay amounts by drug category ($3.00 non-preferred brand, $1.00 generic/preferred brand, etc.). It does not describe the structure as 'flat rather than tiers', and the amounts vary by category.)
- **Q20** (absence): correct, groundedness n/a, citation recall –, retrieval –
  - Judge: Declines to answer, stating it could not verify from the provided documents, which matches the reference's 'outside these documents' conclusion; no dosing given.

## Caveats

- **The judge is also a Claude model**, so it may share the agent's blind spots. Human spot checks of its grades (the two lists above) are the safeguard.
- **Each question ran once.** The agent isn't deterministic, so a one-question difference between setups may be noise.
- **VA formulary gold** (6 spreadsheet rows, from cells such as A1697:G1697) counts in the all-gold scores; a setup without the formulary lookup can't reach it, so compare setups on the PDF-pages-only scores too. Recall@k covers PDF pages only.
- **Failure classes are assigned by rule** (earliest stage that explains the miss), with ambiguous cases set by hand in `evals/failure_overrides.yaml`.
- **Citation precision is a lower bound**: a correct citation to a page outside the gold set counts against it. Read it together with groundedness.
- **Cold latency has n=0**: in one process only the first question loads the index, so the cold p95 is not a real percentile.
