# Eval: docling_rerank_structured, 2026-10-17 23:42

- Agent: `claude-sonnet-5-5` (effort medium), index setup `docling_rerank_structured`, max 6 lookups, 25 s deadline
- Judge: `claude-opus-5-5` (effort medium, 3 passes)
- Golden set: `evals/visual.jsonl`, 8 questions, each run once
- Code: commit `005e08c` (with uncommitted changes)
- Run date: 2026-10-17 23:42; per-question results in `results.csv`

## Results

| Metric | Result |
|---|---|
| Accuracy (judge) | 8 correct, 0 partial, 0 incorrect (score 1.0, partial = 0.5) |
| Judge passes unanimous on the grade | 8/8 |
| must_include terms present (judge, paraphrase counts) | 22/22 |
| must_include terms present (literal substring) | 11/22 |
| Recall@5 / @10 (direct hybrid search on the question, PDF gold) | 0.708 / 1.0 |
| Retrieval recall: all gold / PDF pages only (mean, any tool) | 1.0 / 1.0 |
| Gold sources returned by any tool (all questions) | 16/16 |
| Citation precision / recall: all gold (mean) | 0.74 / 0.833 |
| Citation recall: PDF pages only (mean) | 0.833 |
| Citations failing the in-code check | 0 |
| Groundedness (supported claims / claims, mean) | 0.703 |
| Answered without citations | 0 |
| **Safe**: no unsupported content shown (judge found 0 unsupported claims, or abstained) | 5/8 |
| **Useful**: answerable questions that received a non-abstaining answer | 8/8 |
| Over-abstention (abstained or unverified on an answerable question; graded incorrect) | 0 |
| Abstention correct | 8/8 |
| Opens with the assumption (unspecified program) | 0/0 |
| Startup warmup before timing (not in any latency) | 15.612 s (drug_tables 0.029 s, drug_vocabulary 0.007 s, index 15.298 s) |
| Latency, all | p50 12.74 s, p95 26.49 s (n=8) |
| Latency, cold (index not yet loaded) | none |
| Latency, warm | p50 12.74 s, p95 26.49 s (n=8) |
| Over 30 s | 1 |
| Rendered length incl. citations, words (mean / median / max) | 96.375 / 97.5 / 123 |
| Displayed content, words excl. labels and citations (mean; in 60-120) | 96.375; 7/8 |
| Needs review (not answered, uncited or a flagged citation) | 0 |
| Flags | none |
| Failures by class | answered right but cited wrong 3 |
| Cost | agent $0.52 ($0.065/question), judge $1.01, total $1.53 |

## Per question

| ID | Accuracy | Grounded | R@10 | Retrieval | Cite P / R | Abst. | Assum. | Time s | Words | Cost $ | Failure class |
|---|---|---|---|---|---|---|---|---|---|---|---|
| V01 | correct | 0.833 | 1.0 | 1.0 | 0.667 / 0.667 | True | – | 30.0 | 102 | 0.202 | answered right but cited wrong |
| V02 | correct | 1.0 | 1.0 | 1.0 | 0.667 / 1.0 | True | – | 19.9 | 100 | 0.162 | – |
| V03 | correct | 0.667 | 1.0 | 1.0 | 1.0 / 0.667 | True | – | 12.1 | 123 | 0.164 | answered right but cited wrong |
| V04 | correct | 0.375 | 1.0 | 1.0 | 0.25 / 0.333 | True | – | 13.3 | 91 | 0.229 | answered right but cited wrong |
| V05 | correct | 1.0 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 9.7 | 110 | 0.186 | – |
| V06 | correct | 0.286 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 13.8 | 78 | 0.223 | – |
| V07 | correct | 0.75 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 8.7 | 95 | 0.177 | – |
| V08 | correct | 0.714 | 1.0 | 1.0 | 0.333 / 1.0 | True | – | 8.8 | 72 | 0.185 | – |

## Lowest-scoring questions

Ranked by accuracy, then groundedness, citation recall and retrieval recall.

- **V06** (chart values): correct, groundedness 0.286, citation recall 1.0, retrieval 1.0
  - Judge: All four values match the reference (SGLT2 −31%, GLP-1 RA −7%, sulfonylurea +23%, DPP-4 0%), and negative values are explained as risk reductions.
  - Not fully supported: SGLT2 inhibitors: −31% for the HF composite. (partial: −31 appears in the extracted figure values, but the text extraction does not clearly assign it to SGLT2 inhibitors or to the HF composite. It is listed before the 'Heart failure composite' label.) \| GLP-1 RA: −7% for the HF composite. (partial: −7 appears under the HF composite label in the extraction, but the page text does not determine which class it belongs to.) \| Sulfonylurea: +23% (increased risk) for the HF composite. (partial: 23 appears under the HF composite label, but the extraction does not clearly map it to sulfonylurea.) \| DPP-4 inhibitors: 0% for the HF composite. (partial: 0 appears under the HF composite label, but the extraction does not clearly map it to DPP-4 inhibitors.) \| The document's text says SGLT2 inhibitors reduce HF risk, GLP-1 RAs are neutral for HF, and sulfonylureas show no benefit. (partial: The text recommends SGLT2 inhibitors (empagliflozin, dapagliflozin, sotagliflozin) for HF. It does not state that GLP-1 RAs are neutral for HF or that sulfonylureas show no benefit.)
- **V04** (flowchart detail): correct [answered right but cited wrong], groundedness 0.375, citation recall 0.333, retrieval 1.0
  - Judge: Gives 1–4 weeks, not later than 30 days, and 1–3 months for stable patients without risk factors, matching the reference; the extra details don't contradict it.
  - Not fully supported: First reevaluation should occur within 30 days after initiating opioids (Strong for). (partial: The page calls follow-up within 30 days of initiation a reasonable standard of care, but gives no 'Strong for' rating. The related Recommendation 17 is rated Weak for.) \| The algorithm suggests reevaluation at 1–4 weeks, adjusted for risk factors, and not later than 30 days. (unsupported: No cited page gives the algorithm's 1–4 week timeframe. The cited algorithm page (p26) contains no such content.) \| The initial prescription is short, e.g., 1 week. (unsupported: No cited page discusses initial prescription duration.) \| A stable patient with no added risk factors should be reassessed every 1–3 months. (partial: The page cites three-month intervals for continued opioid prescription as a reasonable standard. A 1–3 month range is not stated.) \| Higher-risk patients need a shorter prescribing interval and more intensive risk mitigation. (partial: The page says some high-risk populations may require more frequent follow-up. It does not mention shorter prescribing intervals or more intensive risk mitigation.)
- **V03** (flowchart branch): correct [answered right but cited wrong], groundedness 0.667, citation recall 0.667, retrieval 1.0
  - Judge: States no opioids; Box 10 No leads to Box 17, exit algorithm and manage with non-opioid modalities, matching the reference.
  - Not fully supported: Patient not on opioids (Box 3 No), so optimize non-opioid care (Box 5). (unsupported: The cited pages don't describe Boxes 3 or 5; p153 starts at Box 7 and p25 only gives the Module A title and its note that non-opioid treatments are preferred.) \| If treatment is still ineffective (Box 6 No), do the opioid risk assessment and refer for interdisciplinary and specialty consults (Box 7). (unsupported: The cited pages don't describe Box 6 or what Box 7 contains; p153 only says that Box 7 connects to Box 8.)
- **V08** (table cell): correct, groundedness 0.714, citation recall 1.0, retrieval 1.0
  - Judge: Correctly identifies Recommendation 11 as Weak for, category Reviewed, New-added, with matching population and purpose; extra details don't contradict the reference.
  - Not fully supported: Recommendation 11 appears in Table 5 of the guideline. (unsupported: The cited pages do not identify the recommendation table as Table 5.) \| The Evidence Table (Appendix E) lists it as #11 with the same strength and category values. (partial: Page 111 lists #11 as Weak for and Reviewed, New-added, but nothing on the page identifies it as Appendix E.)
- **V07** (diagram): correct, groundedness 0.75, citation recall 1.0, retrieval 1.0
  - Judge: Matches Figure 5: 10 units or 0.1–0.2 units/kg daily, FPG target, titrate 10–15% weekly or 2 units every 3 days, decrease 10–20% for hypoglycemia.
  - Not fully supported: Glargine 100 units/mL is preferred over NPH because NPH causes more hypoglycemia. (partial: The source says glargine is the preferred initial basal insulin because NPH causes more hypoglycemia, but it does not name the 100 units/mL strength as the preferred product.) \| Both glargine U300 and degludec are criteria-for-use products. (partial: The source only says 'See criteria for use' with a link after the U300/degludec sentences. It does not explicitly state that both products have criteria for use.)

## Random sample the judge marked correct

To check the judge isn't too lenient (sample seed 8103).

- **V08** (table cell): correct, groundedness 0.714, citation recall 1.0, retrieval 1.0
  - Judge: Correctly identifies Recommendation 11 as Weak for, category Reviewed, New-added, with matching population and purpose; extra details don't contradict the reference.
  - Not fully supported: Recommendation 11 appears in Table 5 of the guideline. (unsupported: The cited pages do not identify the recommendation table as Table 5.) \| The Evidence Table (Appendix E) lists it as #11 with the same strength and category values. (partial: Page 111 lists #11 as Weak for and Reviewed, New-added, but nothing on the page identifies it as Appendix E.)
- **V04** (flowchart detail): correct [answered right but cited wrong], groundedness 0.375, citation recall 0.333, retrieval 1.0
  - Judge: Gives 1–4 weeks, not later than 30 days, and 1–3 months for stable patients without risk factors, matching the reference; the extra details don't contradict it.
  - Not fully supported: First reevaluation should occur within 30 days after initiating opioids (Strong for). (partial: The page calls follow-up within 30 days of initiation a reasonable standard of care, but gives no 'Strong for' rating. The related Recommendation 17 is rated Weak for.) \| The algorithm suggests reevaluation at 1–4 weeks, adjusted for risk factors, and not later than 30 days. (unsupported: No cited page gives the algorithm's 1–4 week timeframe. The cited algorithm page (p26) contains no such content.) \| The initial prescription is short, e.g., 1 week. (unsupported: No cited page discusses initial prescription duration.) \| A stable patient with no added risk factors should be reassessed every 1–3 months. (partial: The page cites three-month intervals for continued opioid prescription as a reasonable standard. A 1–3 month range is not stated.) \| Higher-risk patients need a shorter prescribing interval and more intensive risk mitigation. (partial: The page says some high-risk populations may require more frequent follow-up. It does not mention shorter prescribing intervals or more intensive risk mitigation.)
- **V05** (flowchart branch): correct, groundedness 1.0, citation recall 1.0, retrieval 1.0
  - Judge: Matches Box 36 actions fully: safety/misuse, suicide risk, withdrawal with expedited taper options, SUD monitoring, partial agonist/taper, non-opioid modalities, exit.

## Caveats

- **The judge is also a Claude model**, so it may share the agent's blind spots. Human spot checks of its grades (the two lists above) are the safeguard.
- **Each question ran once.** The agent isn't deterministic, so a one-question difference between setups may be noise.
- **VA formulary gold** (0 spreadsheet rows, from cells such as A1697:G1697) counts in the all-gold scores; a setup without the formulary lookup can't reach it, so compare setups on the PDF-pages-only scores too. Recall@k covers PDF pages only.
- **Failure classes are assigned by rule** (earliest stage that explains the miss), with ambiguous cases set by hand in `evals/failure_overrides.yaml`.
- **Citation precision is a lower bound**: a correct citation to a page outside the gold set counts against it. Read it together with groundedness.
- **Cold latency has n=0**: in one process only the first question loads the index, so the cold p95 is not a real percentile.
