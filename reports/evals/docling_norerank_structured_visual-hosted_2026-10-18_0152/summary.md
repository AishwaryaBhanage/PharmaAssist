# Eval: docling_norerank_structured, 2026-10-18 01:52

- Agent: `claude-sonnet-5-5` (effort medium), index setup `docling_norerank_structured`, max 6 lookups, 25 s deadline
- Judge: `claude-opus-5-5` (effort medium, 3 passes)
- Golden set: `evals/visual.jsonl`, 8 questions, each run once
- Code: commit `005e08c` (with uncommitted changes)
- Run date: 2026-10-18 01:52; per-question results in `results.csv`

## Results

| Metric | Result |
|---|---|
| Accuracy (judge) | 8 correct, 0 partial, 0 incorrect (score 1.0, partial = 0.5) |
| Judge passes unanimous on the grade | 8/8 |
| must_include terms present (judge, paraphrase counts) | 22/22 |
| must_include terms present (literal substring) | 10/22 |
| Recall@5 / @10 (direct hybrid search on the question, PDF gold) | 0.875 / 0.958 |
| Retrieval recall: all gold / PDF pages only (mean, any tool) | 0.917 / 0.917 |
| Gold sources returned by any tool (all questions) | 14/16 |
| Citation precision / recall: all gold (mean) | 0.594 / 0.771 |
| Citation recall: PDF pages only (mean) | 0.771 |
| Citations failing the in-code check | 0 |
| Groundedness (supported claims / claims, mean) | 0.667 |
| Answered without citations | 0 |
| **Safe**: no unsupported content shown (judge found 0 unsupported claims, or abstained) | 4/8 |
| **Useful**: answerable questions that received a non-abstaining answer | 8/8 |
| Over-abstention (abstained or unverified on an answerable question; graded incorrect) | 0 |
| Abstention correct | 8/8 |
| Opens with the assumption (unspecified program) | 0/0 |
| Startup warmup before timing (not in any latency) | 0.977 s (drug_tables 0.027 s, drug_vocabulary 0.006 s, index 0.65 s) |
| Latency, all | p50 6.0 s, p95 6.94 s (n=8) |
| Latency, cold (index not yet loaded) | none |
| Latency, warm | p50 6.0 s, p95 6.94 s (n=8) |
| Over 30 s | 0 |
| Rendered length incl. citations, words (mean / median / max) | 95.625 / 97.0 / 116 |
| Displayed content, words excl. labels and citations (mean; in 60-120) | 95.625; 8/8 |
| Needs review (not answered, uncited or a flagged citation) | 0 |
| Flags | none |
| Failures by class | answered right but cited wrong 4 |
| Cost | agent $0.47 ($0.059/question), judge $1.05, total $1.53 |

## Per question

| ID | Accuracy | Grounded | R@10 | Retrieval | Cite P / R | Abst. | Assum. | Time s | Words | Cost $ | Failure class |
|---|---|---|---|---|---|---|---|---|---|---|---|
| V01 | correct | 0.714 | 1.0 | 1.0 | 1.0 / 0.667 | True | – | 7.1 | 89 | 0.164 | answered right but cited wrong |
| V02 | correct | 0.333 | 1.0 | 1.0 | 0.333 / 0.5 | True | – | 6.5 | 116 | 0.215 | answered right but cited wrong |
| V03 | correct | 0.571 | 1.0 | 1.0 | 0.667 / 0.667 | True | – | 6.0 | 116 | 0.164 | answered right but cited wrong |
| V04 | correct | 0.625 | 0.667 | 0.333 | 0.25 / 0.333 | True | – | 6.7 | 108 | 0.245 | answered right but cited wrong |
| V05 | correct | 1.0 | 1.0 | 1.0 | 0.667 / 1.0 | True | – | 6.0 | 105 | 0.182 | – |
| V06 | correct | 0.429 | 1.0 | 1.0 | 0.5 / 1.0 | True | – | 6.0 | 72 | 0.230 | – |
| V07 | correct | 1.0 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 5.6 | 88 | 0.143 | – |
| V08 | correct | 0.667 | 1.0 | 1.0 | 0.333 / 1.0 | True | – | 5.2 | 71 | 0.185 | – |

## Lowest-scoring questions

Ranked by accuracy, then groundedness, citation recall and retrieval recall.

- **V02** (flowchart branch): correct [answered right but cited wrong], groundedness 0.333, citation recall 0.5, retrieval 1.0
  - Judge: Matches all three timing triggers and acute-setting sequence: survival skills first, refer after acute care, then outpatient VA/DoD DSMES/MNT enrollment.
  - Not fully supported: Offer DSMES or MNT at initial diagnosis, when not meeting treatment goals, and with a change in health status or barriers to self-management. (partial: The cited pages don't show the CPG algorithm timing. The PBM summary covers diagnosis, not meeting goals, and complicating factors/transitions, but not MNT and not 'barriers to self-management'.) \| In an acute setting, first train in survival skills (Sidebar 5). (partial: Sidebar 5 gives basic education and survival skills 'as needed', but no cited page links it to an acute setting or says it comes first.) \| After acute care, refer for DSMES or MNT. (unsupported: No cited page describes referral after acute care.) \| Then follow the non-acute path: consult or enroll the patient in an outpatient VA/DoD DSMES/MNT program, then do the assessment and comprehensive education. (partial: Sidebar 6 covers assessment and comprehensive DSMES education. No cited page mentions consulting or enrolling in an outpatient DSMES/MNT program or the sequence of steps.)
- **V06** (chart values): correct, groundedness 0.429, citation recall 1.0, retrieval 1.0
  - Judge: All four class values match the reference exactly (SGLT2 −31%, GLP-1 RA −7%, sulfonylurea +23%, DPP-4 0%), with the correct sign convention and nothing contradicting it.
  - Not fully supported: SGLT2 inhibitors show a −31% change in the HF composite. (partial: The extracted chart text has −31, but it appears before the 'Heart failure composite' label. The −45 and −24 values also appear near that label, so the text doesn't show which class or composite −31 belongs to.) \| GLP-1 RAs show a −7% change in the HF composite. (partial: −7 appears after the HF composite label, but the extracted text doesn't show which class it belongs to.) \| Sulfonylureas show a +23% change (increased risk) in the HF composite. (partial: 23 appears after the HF composite label, but the extracted text doesn't show which class it belongs to.) \| DPP-4 inhibitors show a 0% change in the HF composite. (partial: 0 appears after the HF composite label, but the extracted text doesn't show which class it belongs to.)
- **V03** (flowchart branch): correct [answered right but cited wrong], groundedness 0.571, citation recall 0.667, retrieval 1.0
  - Judge: States no opioids; Box 10 'No' leads to Box 17, exit algorithm and manage with non-opioid modalities, matching the reference.
  - Not fully supported: Box 6 = No: non-opioid treatment is optimized but ineffective. (unsupported: None of the cited pages describe Box 6; page 153 starts at Box 7.) \| Box 7: complete the opioid risk assessment and refer for interdisciplinary and specialty consults. (unsupported: Page 153 only says Box 7 connects to Box 8. It does not give Box 7's content.) \| Module B starts from a candidate 'in conjunction with a comprehensive pain care plan'. (unsupported: Page 26 gives only the Module B title and abbreviations; the quoted entry point does not appear in any cited source.)
- **V04** (flowchart detail): correct [answered right but cited wrong], groundedness 0.625, citation recall 0.333, retrieval 0.333
  - Judge: Includes 1-4 weeks, no later than 30 days, and 1-3 months for stable patients without risk factors (Box 28), more often per risk; extra detail doesn't contradict.
  - Not fully supported: The algorithm says first reevaluation at 1–4 weeks, no later than 30 days, if opioids are to continue. (unsupported: The cited algorithm page (p26) shows only a header and footnotes. The 1–4 week figure on p50 is from the 2016 CDC guideline, not the VA/DoD algorithm.) \| The guidance suggests a short initial prescription, e.g., 1 week. (partial: Rec 9 recommends the shortest duration as indicated, but no cited page gives a 1-week example.) \| Stable patients with no added risk factors should be reassessed in 1–3 months (Module B, box 28), or sooner based on risk. (unsupported: The cited Module B page (p26) contains no algorithm content, and no cited page gives a 1–3 month interval or box 28.)
- **V08** (table cell): correct, groundedness 0.667, citation recall 1.0, retrieval 1.0
  - Judge: Correctly gives Rec 11 as Weak for, category Reviewed, New-added, with matching population and goals; no contradictions.
  - Not fully supported: Rec #11 appears in Table 5 of the guideline. (unsupported: The cited page shows the recommendations table but does not label it Table 5.) \| The Appendix E evidence table lists the same strength (Weak for) and category (Reviewed, New-added). (partial: The page shows an evidence table with 2023 strength Weak for and category Reviewed, New-added, but it does not identify the table as Appendix E.)

## Random sample the judge marked correct

To check the judge isn't too lenient (sample seed 3929).

- **V05** (flowchart branch): correct, groundedness 1.0, citation recall 1.0, retrieval 1.0
  - Judge: Matches Box 36 fully: safety/misuse, suicide risk, withdrawal with expedited taper options, SUD monitoring, partial agonist or taper, non-opioid management, exit.
- **V03** (flowchart branch): correct [answered right but cited wrong], groundedness 0.571, citation recall 0.667, retrieval 1.0
  - Judge: States no opioids; Box 10 'No' leads to Box 17, exit algorithm and manage with non-opioid modalities, matching the reference.
  - Not fully supported: Box 6 = No: non-opioid treatment is optimized but ineffective. (unsupported: None of the cited pages describe Box 6; page 153 starts at Box 7.) \| Box 7: complete the opioid risk assessment and refer for interdisciplinary and specialty consults. (unsupported: Page 153 only says Box 7 connects to Box 8. It does not give Box 7's content.) \| Module B starts from a candidate 'in conjunction with a comprehensive pain care plan'. (unsupported: Page 26 gives only the Module B title and abbreviations; the quoted entry point does not appear in any cited source.)
- **V02** (flowchart branch): correct [answered right but cited wrong], groundedness 0.333, citation recall 0.5, retrieval 1.0
  - Judge: Matches all three timing triggers and acute-setting sequence: survival skills first, refer after acute care, then outpatient VA/DoD DSMES/MNT enrollment.
  - Not fully supported: Offer DSMES or MNT at initial diagnosis, when not meeting treatment goals, and with a change in health status or barriers to self-management. (partial: The cited pages don't show the CPG algorithm timing. The PBM summary covers diagnosis, not meeting goals, and complicating factors/transitions, but not MNT and not 'barriers to self-management'.) \| In an acute setting, first train in survival skills (Sidebar 5). (partial: Sidebar 5 gives basic education and survival skills 'as needed', but no cited page links it to an acute setting or says it comes first.) \| After acute care, refer for DSMES or MNT. (unsupported: No cited page describes referral after acute care.) \| Then follow the non-acute path: consult or enroll the patient in an outpatient VA/DoD DSMES/MNT program, then do the assessment and comprehensive education. (partial: Sidebar 6 covers assessment and comprehensive DSMES education. No cited page mentions consulting or enrolling in an outpatient DSMES/MNT program or the sequence of steps.)

## Caveats

- **The judge is also a Claude model**, so it may share the agent's blind spots. Human spot checks of its grades (the two lists above) are the safeguard.
- **Each question ran once.** The agent isn't deterministic, so a one-question difference between setups may be noise.
- **VA formulary gold** (0 spreadsheet rows, from cells such as A1697:G1697) counts in the all-gold scores; a setup without the formulary lookup can't reach it, so compare setups on the PDF-pages-only scores too. Recall@k covers PDF pages only.
- **Failure classes are assigned by rule** (earliest stage that explains the miss), with ambiguous cases set by hand in `evals/failure_overrides.yaml`.
- **Citation precision is a lower bound**: a correct citation to a page outside the gold set counts against it. Read it together with groundedness.
- **Cold latency has n=0**: in one process only the first question loads the index, so the cold p95 is not a real percentile.
