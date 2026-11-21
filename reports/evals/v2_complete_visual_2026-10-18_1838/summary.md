# Eval: v2_complete, 2026-10-18 18:38

- Agent: `gpt-5.5 (fallback claude-sonnet-5-5)` (effort medium), index setup `v2_complete`, max 6 lookups, 25 s deadline
- Judge: `claude-opus-5-5` (effort medium, 3 passes)
- Golden set: `evals/visual.jsonl`, 8 questions, each run once
- Code: commit `1972777` (with uncommitted changes)
- Run date: 2026-10-18 18:38; per-question results in `results.csv`

## Results

| Metric | Result |
|---|---|
| Accuracy (judge) | 8 correct, 0 partial, 0 incorrect (score 1.0, partial = 0.5) |
| Judge passes unanimous on the grade | 8/8 |
| must_include terms present (judge, paraphrase counts) | 22/22 |
| must_include terms present (literal substring) | 10/22 |
| Recall@5 / @10 (direct hybrid search on the question, PDF gold) | 0.604 / 0.854 |
| Retrieval recall: all gold / PDF pages only (mean, any tool) | 0.646 / 0.646 |
| Gold sources returned by any tool (all questions) | 10/16 |
| Citation precision / recall: all gold (mean) | 0.556 / 0.646 |
| Citation recall: PDF pages only (mean) | 0.646 |
| Citations failing the in-code check | 0 |
| Groundedness (supported claims / claims, mean) | 0.783 |
| Answered without citations | 0 |
| **Safe**: no unsupported content shown (judge found 0 unsupported claims, or abstained) | 7/8 |
| **Useful**: answerable questions that received a non-abstaining answer | 8/8 |
| Over-abstention (abstained or unverified on an answerable question; graded incorrect) | 0 |
| Abstention correct | 8/8 |
| Opens with the assumption (unspecified program) | 0/0 |
| Startup warmup before timing (not in any latency) | 0.351 s (store 0.001 s, tables 0.34 s, search 0.01 s) |
| Latency, all | p50 16.96 s, p95 20.91 s (n=8) |
| Latency, cold (index not yet loaded) | p50 16.96 s, p95 20.91 s (n=8) |
| Latency, warm | none |
| Over 30 s | 0 |
| Rendered length incl. citations, words (mean / median / max) | 103.375 / 108.0 / 120 |
| Displayed content, words excl. labels and citations (mean; in 60-120) | 103.375; 8/8 |
| Needs review (not answered, uncited or a flagged citation) | 0 |
| Flags | none |
| Failures by class | answered right but cited wrong 4 |
| Cost | agent $1.24 ($0.155/question), judge $1.02, total $2.26 |

## Per question

| ID | Accuracy | Grounded | R@10 | Retrieval | Cite P / R | Abst. | Assum. | Time s | Words | Cost $ | Failure class |
|---|---|---|---|---|---|---|---|---|---|---|---|
| V01 | correct | 0.333 | 1.0 | 0.333 | 0.333 / 0.333 | True | – | 21.1 | 117 | 0.259 | answered right but cited wrong |
| V02 | correct | 1.0 | 1.0 | 1.0 | 0.667 / 1.0 | True | – | 19.2 | 99 | 0.280 | – |
| V03 | correct | 1.0 | 1.0 | 1.0 | 0.75 / 1.0 | True | – | 20.6 | 104 | 0.282 | – |
| V04 | correct | 0.5 | 0.333 | 0.333 | 0.2 / 0.333 | True | – | 16.9 | 94 | 0.337 | answered right but cited wrong |
| V05 | correct | 1.0 | 0.5 | 0.5 | 1.0 / 0.5 | True | – | 15.5 | 120 | 0.264 | answered right but cited wrong |
| V06 | correct | 0.429 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 16.9 | 64 | 0.321 | – |
| V07 | correct | 1.0 | 1.0 | 1.0 | 0.5 / 1.0 | True | – | 13.6 | 117 | 0.221 | – |
| V08 | correct | 1.0 | 1.0 | 0.0 | 0.0 / 0.0 | True | – | 17.0 | 112 | 0.297 | answered right but cited wrong |

## Lowest-scoring questions

Ranked by accuracy, then groundedness, citation recall and retrieval recall.

- **V01** (flowchart branch): correct [answered right but cited wrong], groundedness 0.333, citation recall 0.333, retrieval 0.333
  - Judge: Matches reference: skips GLP-1/SGLT-2 step, then consider additional medications until target A1C, chosen by efficacy and risk-benefit, citing Appendix B.
  - Not fully supported: For a patient without established/high-risk ASCVD, diabetic nephropathy, or HF, the 2023 VA/DoD algorithm skips the comorbidity-directed GLP-1 RA/SGLT-2 inhibitor step and goes to assessing the glycemic target. (unsupported: Cited p21 shows only the Module A heading and an abbreviation list; none of the algorithm's decision steps appear in the cited text.) \| The glycemic target is A1C 7.0–8.5% for most patients or an individualized range. (unsupported: No cited page states an A1C target range.) \| If the target is not achieved, consider additional medications until the target A1C is achieved, selecting them by efficacy and risk–benefit ratio; see CPG Appendix B. (unsupported: The cited pages do not contain this step or any reference to Appendix B.) \| The guideline's Module B says patients with T2DM should be offered DSMES or MNT when not meeting treatment goals. (partial: p22 shows the Module B title (Self-Management Education and Support) and lists DSMES and MNT as abbreviations, but the cited text does not say to offer them when treatment goals are not met.)
- **V06** (chart values): correct, groundedness 0.429, citation recall 1.0, retrieval 1.0
  - Judge: All four drug-class values match the reference (SGLT2 −31%, GLP-1 RA −7%, SU +23%, DPP-4 0%), and negative values are correctly explained as reductions.
  - Not fully supported: For the HF composite, SGLT2 inhibitors show a −31% relative risk change. (partial: The value −31 appears in the figure, but the extracted figure text is garbled and does not clearly assign it to SGLT2 inhibitors for the HF composite; it appears before the 'Heart failure composite' label.) \| For the HF composite, GLP-1 RA shows a −7% relative risk change. (partial: The value −7 appears in the figure, but the extracted text does not clearly map it to GLP-1 RA.) \| For the HF composite, sulfonylurea shows a +23% relative risk change. (partial: The value 23 appears in the figure, but the extracted text does not clearly map it to sulfonylurea.) \| For the HF composite, DPP-4 inhibitors show a 0% relative risk change. (partial: The value 0 appears in the figure, but the extracted text does not clearly map it to DPP-4 inhibitors.)
- **V04** (flowchart detail): correct [answered right but cited wrong], groundedness 0.5, citation recall 0.333, retrieval 0.333
  - Judge: Gives first reevaluation at 1–4 weeks, not later than 30 days, and stable no-risk reassessment every 1–3 months, matching the reference.
  - Not fully supported: The first reevaluation should occur within 30 days, often 1–4 weeks, not later than 30 days. (partial: The source supports reevaluation at 30 days or fewer after initiation. The 'often 1–4 weeks' detail is not stated.) \| At reevaluation, reassess function, pain, opioid risks/benefits, adverse effects, adherence, co-occurring conditions, patient preference, and risk-mitigation steps. (partial: The source supports ongoing reevaluation of benefits and harms based on individual risk characteristics. The specific list (function, adherence, patient preference, risk-mitigation steps, etc.) is not given on the cited pages.) \| If the patient has meaningful benefit, is stable, and has no added risk factors, reassess every 1–3 months. (partial: The sources cite three-month intervals and CDC reevaluation every 90 days as a starting point, with more frequent reevaluation for some patients. A '1–3 month' range tied to these specific stability and benefit conditions is not stated.)
- **V08** (table cell): correct [answered right but cited wrong], groundedness 1.0, citation recall 0.0, retrieval 0.0
  - Judge: States Weak for and Reviewed, New-added with correct recommendation wording; extra details don't contradict the reference. Recommendation number omitted but not essential.
- **V05** (flowchart branch): correct [answered right but cited wrong], groundedness 1.0, citation recall 0.5, retrieval 0.5
  - Judge: Directs Box 36 with all reference actions: safety/misuse, suicide risk, withdrawal options, SUD monitoring, partial agonist switch or taper, non-opioid modalities, and exit.

## Random sample the judge marked correct

To check the judge isn't too lenient (sample seed 8179).

- **V05** (flowchart branch): correct [answered right but cited wrong], groundedness 1.0, citation recall 0.5, retrieval 0.5
  - Judge: Directs Box 36 with all reference actions: safety/misuse, suicide risk, withdrawal options, SUD monitoring, partial agonist switch or taper, non-opioid modalities, and exit.
- **V07** (diagram): correct, groundedness 1.0, citation recall 1.0, retrieval 1.0
  - Judge: Includes the 10 units or 0.1–0.2 units/kg start, FPG target, 10–15% weekly or 2 units every 3 days titration, and a 10–20% decrease for hypoglycemia.
- **V02** (flowchart branch): correct, groundedness 1.0, citation recall 1.0, retrieval 1.0
  - Judge: Gives all three timing triggers and, for acute settings, survival-skills training then referral after acute care; minor framing of outpatient enrollment is not a contradiction.

## Caveats

- **The judge is also a Claude model**, so it may share the agent's blind spots. Human spot checks of its grades (the two lists above) are the safeguard.
- **Each question ran once.** The agent isn't deterministic, so a one-question difference between setups may be noise.
- **VA formulary gold** (0 spreadsheet rows, from cells such as A1697:G1697) counts in the all-gold scores; a setup without the formulary lookup can't reach it, so compare setups on the PDF-pages-only scores too. Recall@k covers PDF pages only.
- **Failure classes are assigned by rule** (earliest stage that explains the miss), with ambiguous cases set by hand in `evals/failure_overrides.yaml`.
- **Citation precision is a lower bound**: a correct citation to a page outside the gold set counts against it. Read it together with groundedness.
- **Cold latency has n=8**: in one process only the first question loads the index, so the cold p95 is not a real percentile.
