# Eval: v2_checklist, 2026-10-18 19:39

- Agent: `gpt-5.5 (fallback claude-sonnet-5-5)` (effort medium), index setup `v2_checklist`, max 6 lookups, 25 s deadline
- Judge: `claude-opus-5-5` (effort medium, 3 passes)
- Golden set: `evals/visual.jsonl`, 8 questions, each run once
- Code: commit `0aaa897` (with uncommitted changes)
- Run date: 2026-10-18 19:39; per-question results in `results.csv`

## Results

| Metric | Result |
|---|---|
| Accuracy (judge) | 8 correct, 0 partial, 0 incorrect (score 1.0, partial = 0.5) |
| Judge passes unanimous on the grade | 8/8 |
| must_include terms present (judge, paraphrase counts) | 22/22 |
| must_include terms present (literal substring) | 9/22 |
| Recall@5 / @10 (direct hybrid search on the question, PDF gold) | 0.604 / 0.854 |
| Retrieval recall: all gold / PDF pages only (mean, any tool) | 0.708 / 0.708 |
| Gold sources returned by any tool (all questions) | 11/16 |
| Citation precision / recall: all gold (mean) | 0.733 / 0.667 |
| Citation recall: PDF pages only (mean) | 0.667 |
| Citations failing the in-code check | 0 |
| Groundedness (supported claims / claims, mean) | 0.619 |
| Answered without citations | 0 |
| **Safe**: no unsupported content shown (judge found 0 unsupported claims, or abstained) | 6/8 |
| **Useful**: answerable questions that received a non-abstaining answer | 8/8 |
| Over-abstention (abstained or unverified on an answerable question; graded incorrect) | 0 |
| Abstention correct | 8/8 |
| Opens with the assumption (unspecified program) | 0/0 |
| Startup warmup before timing (not in any latency) | 0.401 s (store 0.002 s, tables 0.39 s, search 0.009 s) |
| Latency, all | p50 7.05 s, p95 10.65 s (n=8) |
| Latency, cold (index not yet loaded) | p50 7.05 s, p95 10.65 s (n=8) |
| Latency, warm | none |
| Over 30 s | 0 |
| Rendered length incl. citations, words (mean / median / max) | 81.875 / 87.5 / 99 |
| Displayed content, words excl. labels and citations (mean; in 60-120) | 81.875; 7/8 |
| Needs review (not answered, uncited or a flagged citation) | 0 |
| Flags | none |
| Failures by class | answered right but cited wrong 4 |
| Cost | agent $0.65 ($0.081/question), judge $0.92, total $1.57 |

## Per question

| ID | Accuracy | Grounded | R@10 | Retrieval | Cite P / R | Abst. | Assum. | Time s | Words | Cost $ | Failure class |
|---|---|---|---|---|---|---|---|---|---|---|---|
| V01 | correct | 0.333 | 1.0 | 0.333 | 1.0 / 0.333 | True | – | 6.1 | 82 | 0.133 | answered right but cited wrong |
| V02 | correct | 1.0 | 1.0 | 1.0 | 0.667 / 1.0 | True | – | 10.9 | 97 | 0.210 | – |
| V03 | correct | 0.25 | 1.0 | 1.0 | 1.0 / 0.667 | True | – | 6.9 | 99 | 0.173 | answered right but cited wrong |
| V04 | correct | 0.4 | 0.333 | 0.333 | 0.2 / 0.333 | True | – | 10.2 | 89 | 0.331 | answered right but cited wrong |
| V05 | correct | 0.889 | 0.5 | 1.0 | 1.0 / 1.0 | True | – | 6.6 | 86 | 0.177 | – |
| V06 | correct | 0.333 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 5.5 | 60 | 0.199 | – |
| V07 | correct | 1.0 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 7.2 | 89 | 0.142 | – |
| V08 | correct | 0.75 | 1.0 | 0.0 | 0.0 / 0.0 | True | – | 9.9 | 53 | 0.203 | answered right but cited wrong |

## Lowest-scoring questions

Ranked by accuracy, then groundedness, citation recall and retrieval recall.

- **V03** (flowchart branch): correct [answered right but cited wrong], groundedness 0.25, citation recall 0.667, retrieval 1.0
  - Judge: Correctly says no opioids; the 'No' at the comprehensive care plan decision leads to exiting the algorithm and managing with non-opioid modalities. Omitting box numbers is minor.
  - Not fully supported: If potential benefits outweigh risks, the algorithm asks whether the patient is able and willing to engage in a comprehensive pain care plan. (unsupported: The cited page ends at Box 7 (opioid risk assessment/consultation); no benefit-risk or 'able and willing' decision point appears in the cited text.) \| A 'No' at the 'able and willing to engage' decision point leads to 'Exit algorithm; manage with non-opioid modalities.' (partial: The cited page has Box 17 'Exit algorithm; manage with non-opioid modalities,' but only as the 'Yes' path from Box 6 (non-opioid treatment effective). It does not show it as the result of a 'No' at an 'able and willing' decision.) \| Do not start opioids in this scenario; opioids should not be initiated unless part of a documented comprehensive pain care plan the patient can/will engage in. (unsupported: The cited pages only say non-pharmacologic and non-opioid treatments are preferred (p25). Neither page mentions a requirement for a comprehensive pain care plan before starting opioids.)
- **V01** (flowchart branch): correct [answered right but cited wrong], groundedness 0.333, citation recall 0.333, retrieval 0.333
  - Judge: Matches reference: skips GLP-1/SGLT-2 step, then consider additional medications until target A1C based on efficacy and risk-benefit, Appendix B.
  - Not fully supported: In Module A, after metformin/non-pharmacologic review, a patient without established/high-risk ASCVD, diabetic nephropathy, or HF skips the GLP-1 RA/SGLT-2 comorbidity step. (unsupported: The cited page has only the module title and abbreviations (ASCVD, GLP-1 RA, SGLT-2, MNT). It does not show this algorithm flow or decision logic.) \| The algorithm then asks whether the glycemic target is achieved. (unsupported: No algorithm steps appear in the cited page text.) \| If the patient is not at target, the next step is to consider additional medications until the target A1C range is achieved. (unsupported: The cited page does not contain this step.) \| The additional agent is selected based on efficacy and risk–benefit ratio, referring to CPG Appendix B. (unsupported: The cited page does not mention selection criteria or Appendix B.)
- **V06** (chart values): correct, groundedness 0.333, citation recall 1.0, retrieval 1.0
  - Judge: All four values match the reference exactly, with correct sign interpretation; the extra composite definition does not contradict the reference.
  - Not fully supported: SGLT2 inhibitors show a -31% relative risk change for the HF composite. (partial: The value -31 appears in the figure, but the extracted text is scrambled. It cannot confirm that -31 belongs to SGLT2 inhibitors in the HF composite; it sits next to the MACE label.) \| GLP-1 RA shows a -7% relative risk change for the HF composite. (partial: The value -7 appears after the HF label, but the extracted text does not clearly assign it to GLP-1 RA.) \| Sulfonylurea shows a +23% relative risk change for the HF composite. (partial: The value 23 appears after the HF label, but the extracted text does not clearly assign it to sulfonylureas.) \| DPP-4 inhibitors show a 0% relative risk change for the HF composite. (partial: The value 0 appears after the HF label, but the extracted text does not clearly assign it to DPP-4 inhibitors.)
- **V04** (flowchart detail): correct [answered right but cited wrong], groundedness 0.4, citation recall 0.333, retrieval 0.333
  - Judge: Gives 1-4 weeks, not later than 30 days, and 1-3 months for stable patients without risk factors; extra detail doesn't contradict the reference.
  - Not fully supported: The algorithm frames the first reevaluation as 1–4 weeks after starting, not later than 30 days. (partial: The cited algorithm page (p26) contains no such content. The '1–4 weeks' figure appears only on p50, as the 2016 CDC guideline's recommendation, not as the VA/DoD algorithm's framing.) \| At that visit, reassess function/pain, opioid risks/benefits, AEs, adherence, co-occurring medical/behavioral/SUD issues, patient preference, and risk-mitigation steps. (partial: p50 covers reexamining the rationale for opioids, risk/benefit, co-occurring conditions, functional status and risk mitigation (UDT, PDMP, naloxone), and AEs appear on p49. Adherence and patient preference are not given as items to reassess.) \| If continuing opioids and the patient is stable without added risk factors, reassess about every 1–3 months. (partial: The cited pages mention three-month intervals as a reasonable standard (p61), and the CDC guidance cited on p50 says 'at least every three months.' A 1–3 month range tied to stable patients without risk factors is not stated.)
- **V08** (table cell): correct [answered right but cited wrong], groundedness 0.75, citation recall 0.0, retrieval 0.0
  - Judge: States Weak for and Reviewed, New-added for real-time CGM in insulin-treated adults not at goal; matches reference. Recommendation number omitted but not essential.
  - Not fully supported: The word "suggest" corresponds to a weak-for recommendation. (partial: The table consistently pairs "suggest" with Weak for and "suggest against" with Weak against, but the cited pages never state this wording convention outright.)

## Random sample the judge marked correct

To check the judge isn't too lenient (sample seed 7739).

- **V08** (table cell): correct [answered right but cited wrong], groundedness 0.75, citation recall 0.0, retrieval 0.0
  - Judge: States Weak for and Reviewed, New-added for real-time CGM in insulin-treated adults not at goal; matches reference. Recommendation number omitted but not essential.
  - Not fully supported: The word "suggest" corresponds to a weak-for recommendation. (partial: The table consistently pairs "suggest" with Weak for and "suggest against" with Weak against, but the cited pages never state this wording convention outright.)
- **V02** (flowchart branch): correct, groundedness 1.0, citation recall 1.0, retrieval 1.0
  - Judge: Matches reference: three timing triggers, survival skills first in acute setting, referral after acute care, then outpatient DSMES/MNT enrollment. Extra 2025 summary detail doesn't contradict.
- **V06** (chart values): correct, groundedness 0.333, citation recall 1.0, retrieval 1.0
  - Judge: All four values match the reference exactly, with correct sign interpretation; the extra composite definition does not contradict the reference.
  - Not fully supported: SGLT2 inhibitors show a -31% relative risk change for the HF composite. (partial: The value -31 appears in the figure, but the extracted text is scrambled. It cannot confirm that -31 belongs to SGLT2 inhibitors in the HF composite; it sits next to the MACE label.) \| GLP-1 RA shows a -7% relative risk change for the HF composite. (partial: The value -7 appears after the HF label, but the extracted text does not clearly assign it to GLP-1 RA.) \| Sulfonylurea shows a +23% relative risk change for the HF composite. (partial: The value 23 appears after the HF label, but the extracted text does not clearly assign it to sulfonylureas.) \| DPP-4 inhibitors show a 0% relative risk change for the HF composite. (partial: The value 0 appears after the HF label, but the extracted text does not clearly assign it to DPP-4 inhibitors.)

## Caveats

- **The judge is also a Claude model**, so it may share the agent's blind spots. Human spot checks of its grades (the two lists above) are the safeguard.
- **Each question ran once.** The agent isn't deterministic, so a one-question difference between setups may be noise.
- **VA formulary gold** (0 spreadsheet rows, from cells such as A1697:G1697) counts in the all-gold scores; a setup without the formulary lookup can't reach it, so compare setups on the PDF-pages-only scores too. Recall@k covers PDF pages only.
- **Failure classes are assigned by rule** (earliest stage that explains the miss), with ambiguous cases set by hand in `evals/failure_overrides.yaml`.
- **Citation precision is a lower bound**: a correct citation to a page outside the gold set counts against it. Read it together with groundedness.
- **Cold latency has n=8**: in one process only the first question loads the index, so the cold p95 is not a real percentile.
