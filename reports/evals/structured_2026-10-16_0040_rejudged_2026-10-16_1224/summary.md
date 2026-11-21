# Eval: structured, 2026-10-16 04:41 UTC, re-judged 2026-10-16 12:24

- Agent: `claude-sonnet-5-5` (effort medium), index setup `structured`, max 6 lookups, 25 s deadline
- Judge: `claude-opus-5-5` (effort medium)
- Golden set: `evals/golden.jsonl`, 20 questions, each run once
- Code: commit `36bddaa` (with uncommitted changes)
- Run date: 2026-10-16 04:41 UTC, re-judged 2026-10-16 12:24; per-question results in `results.csv`
- Re-judged from `reports/evals/structured_2026-10-16_0040` with the current judges; the agent wasn't rerun

## Results

| Metric | Result |
|---|---|
| Accuracy (judge) | 11 correct, 8 partial, 1 incorrect (score 0.75, partial = 0.5) |
| Judge passes unanimous on the grade | 18/20 |
| must_include terms present (judge, paraphrase counts) | 48/54 |
| must_include terms present (literal substring) | 20/54 |
| Recall@5 / @10 (direct hybrid search on the question, PDF gold) | 0.552 / 0.646 |
| Retrieval recall: all gold / PDF pages only (mean, any tool) | 0.703 / 0.745 |
| Gold sources returned by any tool (all questions) | 37/59 |
| Citation precision / recall: all gold (mean) | 0.773 / 0.696 |
| Citation recall: PDF pages only (mean) | 0.745 |
| Citations failing the in-code check | 0 |
| Groundedness (supported claims / claims, mean) | 0.876 |
| Answered without citations | 0 |
| Abstention correct | 20/20 |
| Opens with the assumption (unspecified program) | 4/4 |
| Latency, all | p50 7.49 s, p95 13.78 s (n=20) |
| Latency, cold (index not yet loaded) | p50 13.39 s, p95 13.39 s (n=1) |
| Latency, warm | p50 7.37 s, p95 12.29 s (n=19) |
| Over 30 s | 0 |
| Words (mean; within 60–120) | 110.65; 14/20 |
| Flags | budget_spent:tool_cap 1 |
| Failures by class | ingested but not retrieved 7, retrieved but answered wrong 2, answered right but cited wrong 4 |
| Cost | agent $0.62 ($0.031/question), judge $2.88, total $3.51 |

## Per question

| ID | Accuracy | Grounded | R@10 | Retrieval | Cite P / R | Abst. | Assum. | Time s | Words | Cost $ | Failure class |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Q01 | partial | 0.75 | 0.6 | 0.4 | 0.667 / 0.4 | True | – | 13.4 | 142 | 0.211 | ingested but not retrieved |
| Q02 | correct | 1.0 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 21.1 | 95 | 0.114 | – |
| Q03 | partial | 0.727 | 0.5 | 0.714 | 1.0 / 0.571 | True | – | 8.0 | 141 | 0.230 | ingested but not retrieved |
| Q04 | partial | 1.0 | 0.667 | 0.667 | 1.0 / 0.667 | True | – | 7.6 | 112 | 0.213 | ingested but not retrieved |
| Q05 | correct | 1.0 | 0.5 | 0.25 | 0.5 / 0.25 | True | – | 6.8 | 140 | 0.158 | answered right but cited wrong |
| Q06 | partial | 1.0 | 0.75 | 0.75 | 0.6 / 0.75 | True | – | 8.6 | 122 | 0.240 | ingested but not retrieved |
| Q07 | partial | 1.0 | 0.25 | 0.5 | 0.4 / 0.5 | True | – | 9.2 | 133 | 0.313 | ingested but not retrieved |
| Q08 | correct | 0.714 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 8.3 | 111 | 0.144 | – |
| Q09 | correct | 0.75 | 1.0 | 1.0 | 0.5 / 1.0 | True | – | 6.3 | 98 | 0.160 | – |
| Q10 | partial | 1.0 | 0.0 | 0.333 | 0.25 / 0.333 | True | – | 7.4 | 110 | 0.252 | ingested but not retrieved |
| Q11 | correct | 0.833 | 1.0 | 1.0 | 1.0 / 1.0 | True | True | 4.6 | 85 | 0.112 | – |
| Q12 | correct | 0.8 | 1.0 | 0.25 | 1.0 / 0.25 | True | – | 4.6 | 87 | 0.119 | answered right but cited wrong |
| Q13 | correct | 1.0 | 1.0 | 1.0 | 0.6 / 1.0 | True | – | 7.2 | 119 | 0.190 | – |
| Q14 | correct | 0.875 | 0.667 | 0.667 | 1.0 / 0.667 | True | True | 7.9 | 113 | 0.169 | answered right but cited wrong |
| Q15 | correct | 0.778 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 6.8 | 119 | 0.186 | – |
| Q16 | correct | 1.0 | 0.5 | 0.5 | 0.5 / 0.5 | True | True | 8.8 | 103 | 0.152 | answered right but cited wrong |
| Q17 | partial | 0.667 | 0.5 | 1.0 | 1.0 / 1.0 | True | – | 11.3 | 107 | 0.188 | retrieved but answered wrong |
| Q18 | partial | 0.9 | 0.0 | 1.0 | 0.667 / 1.0 | True | True | 6.9 | 122 | 0.185 | retrieved but answered wrong |
| Q19 | incorrect | 0.857 | 0.333 | 0.333 | 1.0 / 0.333 | True | – | 5.5 | 94 | 0.131 | ingested but not retrieved |
| Q20 | correct | n/a | – | – | – / – | True | – | 4.1 | 60 | 0.041 | – |

## Lowest-scoring questions

Ranked by accuracy, then groundedness, citation recall and retrieval recall.

- **Q19** (silence vs absence): incorrect [ingested but not retrieved], groundedness 0.857, citation recall 0.333, retrieval 0.333
  - Judge: Correctly says no tiers and Trulicity is preferred, but wrongly claims no copay amount appears; omits the $1.00 copay, which the reference says is answerable.
  - Missing terms: $1.00
  - Not fully supported: Medicare Part D tier placement is plan-specific and isn't in these documents. (partial: The cited page has no Part D tier information. Nothing in the cited source says that Part D tier placement is plan-specific.)
- **Q17** (effective dates): partial [retrieved but answered wrong], groundedness 0.667, citation recall 1.0, retrieval 1.0
  - Judge: Correctly identifies insulin aspart becoming non-preferred, but misses the four products becoming preferred: glucagon kit, Gvoke, Humalog, and Humalog Jr.
  - Missing terms: Gvoke; Humalog
  - Not fully supported: Insulin aspart (gen Novolog) cartridge, vial, pen is the one diabetes product with a 10/22/2026 marker (unsupported: The same page marks Humalog 100 U/mL vial, pen, cartridge and Humalog Jr. Kwikpen with '1 = Preferred as of 10/22/2026'. Page 34 also marks glucagon emergency kit and Gvoke with '1'. Insulin aspart is not the only marked product.) \| Insulin aspart is preferred until 10/22/2026 and non-preferred (PA required) from that date (partial: The page gives non-preferred status as of 10/22/2026. It does not say the product is currently preferred or that PA is required for non-preferred drugs.)
- **Q03** (apparent conflict; dose vs coverage limit; multi-document): partial [ingested but not retrieved], groundedness 0.727, citation recall 0.571, retrieval 0.714
  - Judge: Correct conclusions on 32 mg fitting NYRx limits and the patch not substituting, but omits monitoring/documented rationale above 24 mg and MAT no-PA condition.
  - Not fully supported: The buprenorphine patch is a transdermal system for pain, not an OUD product. (partial: The VA OUD guide's list of FDA-approved OUD formulations does not include a patch, which implies it is not an OUD product. No cited source says the patch is for pain.) \| Substituting the patch would need a new prescriber order. (unsupported: No cited source addresses substitution or prescriber order requirements.) \| The PDL had no row for 'Suboxone film' by name. (unsupported: Contradicted: the PDL page explicitly lists 'Suboxone® (film)' under Opioid Dependence Agents – Oral/Transmucosal.)
- **Q01** (conflict across versions; synthesis): partial [ingested but not retrieved], groundedness 0.75, citation recall 0.4, retrieval 0.4
  - Judge: Correct conclusion with SGLT2 first-line regardless of A1c and empagliflozin/canagliflozin, but omits the older 2020 guide's conflicting metformin-first sequence.
  - Missing terms: older guide metformin-first
  - Not fully supported: Empagliflozin is the preferred agent in the guide's algorithm. (unsupported: The cited pages don't designate empagliflozin as preferred. They only mention combination empagliflozin/metformin tablets and bolded formulary agents, and the bolding isn't visible in the text.) \| Check that eGFR is ≥20 before starting. (unsupported: No cited page gives an eGFR threshold for starting an SGLT2 inhibitor.)
- **Q18** (no program stated): partial [retrieved but answered wrong], groundedness 0.9, citation recall 1.0, retrieval 1.0
  - Judge: Correctly assumes NY Medicaid, says MAT products need no PA, and states the patch is preferred with LA opioid criteria; omits that Butrans/Belbuca are non-preferred (PA).
  - Missing terms: Butrans/Belbuca non-preferred
  - Not fully supported: Buprenorphine patch is preferred on the PDL, so it needs no PDP PA. (partial: The PDL lists the buprenorphine patch as preferred, but the page defines this as 'Preferred as of 10/22/2026', which is after today's date (2026-10-16). The answer omits that this status is not yet in effect.)

## Random sample the judge marked correct

To check the judge isn't too lenient (sample seed 5382).

- **Q12** (different programs (not a conflict)): correct [answered right but cited wrong], groundedness 0.8, citation recall 0.25, retrieval 0.25
  - Judge: Matches reference: Ozempic pen preferred with clinical criteria, DPP-4 PA, tablets non-preferred, VA formulary not applicable to NY Medicaid.
  - Not fully supported: Ozempic tablets are non-preferred and require PA. (partial: The page lists Ozempic tablets as non-preferred but does not state that non-preferred status means PA is required.)
- **Q05** (multi-document; override and payer coordination): correct [answered right but cited wrong], groundedness 1.0, citation recall 0.25, retrieval 0.25
  - Judge: Says don't bill NYRx, request Part D override citing current opioid use, dispense up to 7 days or coverage determination, give CMS rights notice. Matches reference.
- **Q15** (step therapy): correct, groundedness 0.778, citation recall 1.0, retrieval 1.0
  - Judge: States IR tramadol first via step therapy before tramadol ER/ConZip, notes non-preferred status, PA for opioid-naïve long-acting start, 4-Rx limit, and under-12 PA.
  - Not fully supported: Patients with cancer, sickle cell disease, or hospice/palliative care are exempt from the step therapy requirement. (partial: The exemption is attached by asterisk to the Clinical Criteria (CC), not to the Step Therapy requirement. The PDL does not state that it exempts patients from the tramadol ER step.) \| The 10/22/2026 preferred/non-preferred markers don't change this row. (unsupported: The pages give statuses as of 10/22/2026, which is still in the future as of today (2026-10-16). They do not show the current or prior status of tramadol, so the cited pages cannot confirm whether its status changes on that date.)

## Caveats

- **The judge is also a Claude model**, so it may share the agent's blind spots. Human spot checks of its grades (the two lists above) are the safeguard.
- **Each question ran once.** The agent isn't deterministic, so a one-question difference between setups may be noise.
- **VA formulary gold** (6 spreadsheet rows, from cells such as A1697:G1697) counts in the all-gold scores; a setup without the formulary lookup can't reach it, so compare setups on the PDF-pages-only scores too. Recall@k covers PDF pages only.
- **Failure classes are assigned by rule** (earliest stage that explains the miss), with ambiguous cases set by hand in `evals/failure_overrides.yaml`.
- **Citation precision is a lower bound**: a correct citation to a page outside the gold set counts against it. Read it together with groundedness.
- **Cold latency has n=1**: in one process only the first question loads the index, so the cold p95 is not a real percentile.
