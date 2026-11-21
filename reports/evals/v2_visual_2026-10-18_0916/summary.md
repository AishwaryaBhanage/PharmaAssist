# Eval: v2, 2026-10-18 09:16

- Agent: `gpt-5.5 (fallback claude-sonnet-5-5)` (effort medium), index setup `v2`, max 6 lookups, 25 s deadline
- Judge: `claude-opus-5-5` (effort medium, 3 passes)
- Golden set: `evals/visual.jsonl`, 8 questions, each run once
- Code: commit `a114ef9`
- Run date: 2026-10-18 09:16; per-question results in `results.csv`

## Results

| Metric | Result |
|---|---|
| Accuracy (judge) | 8 correct, 0 partial, 0 incorrect (score 1.0, partial = 0.5) |
| Judge passes unanimous on the grade | 8/8 |
| must_include terms present (judge, paraphrase counts) | 22/22 |
| must_include terms present (literal substring) | 9/22 |
| Recall@5 / @10 (direct hybrid search on the question, PDF gold) | 0.604 / 0.854 |
| Retrieval recall: all gold / PDF pages only (mean, any tool) | 0.646 / 0.646 |
| Gold sources returned by any tool (all questions) | 10/16 |
| Citation precision / recall: all gold (mean) | 0.792 / 0.604 |
| Citation recall: PDF pages only (mean) | 0.604 |
| Citations failing the in-code check | 0 |
| Groundedness (supported claims / claims, mean) | 0.614 |
| Answered without citations | 0 |
| **Safe**: no unsupported content shown (judge found 0 unsupported claims, or abstained) | 5/8 |
| **Useful**: answerable questions that received a non-abstaining answer | 8/8 |
| Over-abstention (abstained or unverified on an answerable question; graded incorrect) | 0 |
| Abstention correct | 8/8 |
| Opens with the assumption (unspecified program) | 0/0 |
| Startup warmup before timing (not in any latency) | 0.323 s (store 0.001 s, tables 0.313 s, search 0.009 s) |
| Latency, all | p50 6.54 s, p95 6.89 s (n=8) |
| Latency, cold (index not yet loaded) | p50 6.54 s, p95 6.89 s (n=8) |
| Latency, warm | none |
| Over 30 s | 0 |
| Rendered length incl. citations, words (mean / median / max) | 77.75 / 79.5 / 100 |
| Displayed content, words excl. labels and citations (mean; in 60-120) | 77.75; 7/8 |
| Needs review (not answered, uncited or a flagged citation) | 0 |
| Flags | none |
| Failures by class | answered right but cited wrong 5 |
| Cost | agent $0.41 ($0.052/question), judge $0.82, total $1.23 |

## Per question

| ID | Accuracy | Grounded | R@10 | Retrieval | Cite P / R | Abst. | Assum. | Time s | Words | Cost $ | Failure class |
|---|---|---|---|---|---|---|---|---|---|---|---|
| V01 | correct | 0.0 | 1.0 | 0.333 | 1.0 / 0.333 | True | – | 6.6 | 80 | 0.128 | answered right but cited wrong |
| V02 | correct | 1.0 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 6.4 | 78 | 0.127 | – |
| V03 | correct | 0.286 | 1.0 | 1.0 | 1.0 / 0.667 | True | – | 6.6 | 100 | 0.178 | answered right but cited wrong |
| V04 | correct | 0.25 | 0.333 | 0.333 | 0.333 / 0.333 | True | – | 6.7 | 79 | 0.183 | answered right but cited wrong |
| V05 | correct | 1.0 | 0.5 | 0.5 | 1.0 / 0.5 | True | – | 5.8 | 86 | 0.145 | answered right but cited wrong |
| V06 | correct | 0.375 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 7.0 | 62 | 0.212 | – |
| V07 | correct | 1.0 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 6.4 | 84 | 0.136 | – |
| V08 | correct | 1.0 | 1.0 | 0.0 | 0.0 / 0.0 | True | – | 5.4 | 53 | 0.122 | answered right but cited wrong |

## Lowest-scoring questions

Ranked by accuracy, then groundedness, citation recall and retrieval recall.

- **V01** (flowchart branch): correct [answered right but cited wrong], groundedness 0.0, citation recall 0.333, retrieval 0.333
  - Judge: Matches reference: skips GLP-1/SGLT-2 step, then add medications until target A1C based on efficacy and risk-benefit, citing Appendix B.
  - Not fully supported: In the VA/DoD T2DM management algorithm, if the patient has no established ASCVD/high ASCVD risk, no diabetic nephropathy, and no HF, the GLP-1 RA/SGLT-2 comorbidity-driven step is skipped and glycemic target is assessed. (unsupported: The cited page has only the guideline title, the 'Module A: T2DM Management' heading and an abbreviation list. It contains none of the algorithm's decision steps.) \| If the patient is not at glycemic target, the next step is to consider additional glucose-lowering medications until the target A1C range is achieved. (unsupported: The cited page has no algorithm text about the not-at-target step or adding glucose-lowering medications.) \| The added agent is selected based on efficacy and overall risk–benefit ratio. (unsupported: The cited page has no medication selection criteria.) \| The algorithm points to CPG Appendix B for medication selection support. (unsupported: The cited page does not mention Appendix B.)
- **V04** (flowchart detail): correct [answered right but cited wrong], groundedness 0.25, citation recall 0.333, retrieval 0.333
  - Judge: Gives 1-4 weeks after initiation, not later than 30 days, and reassessment every 1-3 months or more often per risk; matches the reference.
  - Not fully supported: The algorithm gives 1–4 weeks after initiation, not later than 30 days, for the first reevaluation. (partial: The 30-day limit is supported by Recommendation 10. The cited algorithm page (p26) contains no text about a 1–4 week window.) \| At the reevaluation visit, reassess function, pain, opioid risks/benefits, AEs, adherence, comorbid medical/BH/SUD issues, patient preference, and risk-mitigation steps. (unsupported: No cited page lists these reassessment components.) \| If the patient has meaningful benefit, is stable, and has no added opioid-risk factors, reassess every 1–3 months, or more often if patient-specific risk changes. (partial: p61 calls three-month intervals for continued prescribing a reasonable standard of care and supports reevaluation based on individual patient risk. It does not give a 1–3 month range or the stated conditions of benefit, stability and no added risk factors.)
- **V03** (flowchart branch): correct [answered right but cited wrong], groundedness 0.286, citation recall 0.667, retrieval 1.0
  - Judge: Correctly answers no, and states the endpoint: exit the algorithm and manage with non-opioid modalities. Box numbers are omitted but not essential.
  - Not fully supported: Per the VA/DoD algorithm, opioids should not be started in this scenario. (partial: The cited pages say non-opioid treatments are preferred, but they do not show the algorithm step that leads to a 'do not start opioids' conclusion for this scenario.) \| If benefits outweigh risks, the algorithm directs referral or consultation for interdisciplinary treatments. (unsupported: The cited pages stop at Box 7; no benefit-versus-risk step appears.) \| The algorithm then asks whether the patient is able and willing to engage in a comprehensive pain care plan. (unsupported: This question does not appear on the cited pages.) \| If the patient is not able and willing, the endpoint is 'Exit algorithm; manage with non-opioid modalities.' (partial: Box 17 has this wording, but on the cited page it is reached from a 'Yes' answer at Box 6 (treatment effective), not from a willingness question.) \| Opioids should not be initiated unless they can be part of comprehensive pain therapy with consent and risk mitigation. (unsupported: The cited pages do not mention comprehensive pain therapy, consent or risk mitigation as conditions for starting opioids.)
- **V06** (chart values): correct, groundedness 0.375, citation recall 1.0, retrieval 1.0
  - Judge: All four values match the reference (SGLT2 −31%, GLP-1 RA −7%, sulfonylurea +23%, DPP-4 0%), and the answer notes that negative values are reductions.
  - Not fully supported: SGLT2 inhibitors show a −31% relative risk change for the HF composite. (partial: The extracted figure text lists the values (-14, -13, 10, -2, -31, -7, 23, 0, -45, -24, 4, 4) without a clear mapping to drug classes or composites. In the extraction, -31 appears before the 'Heart failure composite' label, so assigning it to SGLT2/HF cannot be confirmed.) \| GLP-1 RA shows a −7% relative risk change for the HF composite. (partial: The value -7 appears on the page, but the extracted text does not tie it to GLP-1 RA for the HF composite.) \| Sulfonylurea shows a +23% relative risk change for the HF composite. (partial: The value 23 appears on the page, but the extracted text does not tie it to sulfonylurea for the HF composite.) \| DPP-4 inhibitors show a 0% relative risk change for the HF composite. (partial: The value 0 appears on the page, but the extracted text does not tie it to DPP-4 inhibitors for the HF composite.) \| The SGLT2 inhibitor bar shows the largest HF composite risk reduction. (partial: This rests on the uncertain value mapping. A larger negative value (-45) appears in the figure text, and the extraction does not show which class or composite it belongs to.)
- **V08** (table cell): correct [answered right but cited wrong], groundedness 1.0, citation recall 0.0, retrieval 0.0
  - Judge: Correctly identifies Recommendation 11 as Weak for, category Reviewed, New-added, with matching population and purpose; the extra 2017 strength detail does not contradict the reference.

## Random sample the judge marked correct

To check the judge isn't too lenient (sample seed 2407).

- **V07** (diagram): correct, groundedness 1.0, citation recall 1.0, retrieval 1.0
  - Judge: Includes starting dose, FPG target, titration (10–15% weekly or 2 units/3 days), and 10–20% decrease for hypoglycemia; extra details don't contradict the reference.
- **V04** (flowchart detail): correct [answered right but cited wrong], groundedness 0.25, citation recall 0.333, retrieval 0.333
  - Judge: Gives 1-4 weeks after initiation, not later than 30 days, and reassessment every 1-3 months or more often per risk; matches the reference.
  - Not fully supported: The algorithm gives 1–4 weeks after initiation, not later than 30 days, for the first reevaluation. (partial: The 30-day limit is supported by Recommendation 10. The cited algorithm page (p26) contains no text about a 1–4 week window.) \| At the reevaluation visit, reassess function, pain, opioid risks/benefits, AEs, adherence, comorbid medical/BH/SUD issues, patient preference, and risk-mitigation steps. (unsupported: No cited page lists these reassessment components.) \| If the patient has meaningful benefit, is stable, and has no added opioid-risk factors, reassess every 1–3 months, or more often if patient-specific risk changes. (partial: p61 calls three-month intervals for continued prescribing a reasonable standard of care and supports reevaluation based on individual patient risk. It does not give a 1–3 month range or the stated conditions of benefit, stability and no added risk factors.)
- **V03** (flowchart branch): correct [answered right but cited wrong], groundedness 0.286, citation recall 0.667, retrieval 1.0
  - Judge: Correctly answers no, and states the endpoint: exit the algorithm and manage with non-opioid modalities. Box numbers are omitted but not essential.
  - Not fully supported: Per the VA/DoD algorithm, opioids should not be started in this scenario. (partial: The cited pages say non-opioid treatments are preferred, but they do not show the algorithm step that leads to a 'do not start opioids' conclusion for this scenario.) \| If benefits outweigh risks, the algorithm directs referral or consultation for interdisciplinary treatments. (unsupported: The cited pages stop at Box 7; no benefit-versus-risk step appears.) \| The algorithm then asks whether the patient is able and willing to engage in a comprehensive pain care plan. (unsupported: This question does not appear on the cited pages.) \| If the patient is not able and willing, the endpoint is 'Exit algorithm; manage with non-opioid modalities.' (partial: Box 17 has this wording, but on the cited page it is reached from a 'Yes' answer at Box 6 (treatment effective), not from a willingness question.) \| Opioids should not be initiated unless they can be part of comprehensive pain therapy with consent and risk mitigation. (unsupported: The cited pages do not mention comprehensive pain therapy, consent or risk mitigation as conditions for starting opioids.)

## Caveats

- **The judge is also a Claude model**, so it may share the agent's blind spots. Human spot checks of its grades (the two lists above) are the safeguard.
- **Each question ran once.** The agent isn't deterministic, so a one-question difference between setups may be noise.
- **VA formulary gold** (0 spreadsheet rows, from cells such as A1697:G1697) counts in the all-gold scores; a setup without the formulary lookup can't reach it, so compare setups on the PDF-pages-only scores too. Recall@k covers PDF pages only.
- **Failure classes are assigned by rule** (earliest stage that explains the miss), with ambiguous cases set by hand in `evals/failure_overrides.yaml`.
- **Citation precision is a lower bound**: a correct citation to a page outside the gold set counts against it. Read it together with groundedness.
- **Cold latency has n=8**: in one process only the first question loads the index, so the cold p95 is not a real percentile.
