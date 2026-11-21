# Eval: docling_norerank_structured, 2026-10-18 01:52

- Agent: `claude-sonnet-5-5` (effort medium), index setup `docling_norerank_structured`, max 6 lookups, 25 s deadline
- Judge: `claude-opus-5-5` (effort medium, 3 passes)
- Golden set: `evals/golden.jsonl`, 20 questions, each run once
- Code: commit `005e08c` (with uncommitted changes)
- Run date: 2026-10-18 01:52; per-question results in `results.csv`

## Results

| Metric | Result |
|---|---|
| Accuracy (judge) | 15 correct, 4 partial, 1 incorrect (score 0.85, partial = 0.5) |
| Judge passes unanimous on the grade | 20/20 |
| must_include terms present (judge, paraphrase counts) | 52/54 |
| must_include terms present (literal substring) | 19/54 |
| Recall@5 / @10 (direct hybrid search on the question, PDF gold) | 0.744 / 0.82 |
| Retrieval recall: all gold / PDF pages only (mean, any tool) | 0.852 / 0.899 |
| Gold sources returned by any tool (all questions) | 48/59 |
| Citation precision / recall: all gold (mean) | 0.702 / 0.762 |
| Citation recall: PDF pages only (mean) | 0.817 |
| Citations failing the in-code check | 0 |
| Groundedness (supported claims / claims, mean) | 0.878 |
| Answered without citations | 0 |
| **Safe**: no unsupported content shown (judge found 0 unsupported claims, or abstained) | 15/20 |
| **Useful**: answerable questions that received a non-abstaining answer | 18/19 |
| Over-abstention (abstained or unverified on an answerable question; graded incorrect) | 1 |
| Abstention correct | 19/20 |
| Opens with the assumption (unspecified program) | 4/4 |
| Startup warmup before timing (not in any latency) | 0.977 s (drug_tables 0.028 s, drug_vocabulary 0.006 s, index 0.65 s) |
| Latency, all | p50 7.15 s, p95 11.95 s (n=20) |
| Latency, cold (index not yet loaded) | none |
| Latency, warm | p50 7.15 s, p95 11.95 s (n=20) |
| Over 30 s | 0 |
| Rendered length incl. citations, words (mean / median / max) | 114.2 / 117.5 / 152 |
| Displayed content, words excl. labels and citations (mean; in 60-120) | 114.2; 11/20 |
| Needs review (not answered, uncited or a flagged citation) | 2 |
| Flags | none |
| Failures by class | ingested but not retrieved 3, retrieved but answered wrong 2, answered right but cited wrong 7 |
| Cost | agent $1.35 ($0.067/question), judge $3.07, total $4.42 |

## Per question

| ID | Accuracy | Grounded | R@10 | Retrieval | Cite P / R | Abst. | Assum. | Time s | Words | Cost $ | Failure class |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Q01 | correct | 0.846 | 1.0 | 1.0 | 0.6 / 0.6 | True | – | 9.8 | 134 | 0.279 | answered right but cited wrong |
| Q02 | correct | 1.0 | 1.0 | 1.0 | 0.667 / 1.0 | True | – | 7.0 | 113 | 0.185 | – |
| Q03 | correct | 1.0 | 1.0 | 0.857 | 1.0 / 0.714 | True | – | 8.0 | 140 | 0.229 | answered right but cited wrong |
| Q04 | correct | 0.875 | 0.5 | 0.833 | 1.0 / 0.833 | True | – | 8.1 | 107 | 0.286 | answered right but cited wrong |
| Q05 | correct | 0.875 | 1.0 | 1.0 | 0.75 / 0.75 | True | – | 9.4 | 142 | 0.275 | answered right but cited wrong |
| Q06 | partial | 0.909 | 0.5 | 0.75 | 0.6 / 0.75 | True | – | 13.4 | 125 | 0.268 | ingested but not retrieved |
| Q07 | partial | 0.929 | 0.25 | 0.5 | 0.167 / 0.25 | True | – | 8.1 | 152 | 0.345 | ingested but not retrieved |
| Q08 | correct | 0.778 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 5.7 | 118 | 0.186 | – |
| Q09 | correct | 1.0 | 1.0 | 1.0 | 0.5 / 1.0 | True | – | 7.3 | 128 | 0.173 | – |
| Q10 | correct | 0.9 | 0.333 | 0.667 | 0.333 / 0.667 | True | – | 9.2 | 126 | 0.401 | answered right but cited wrong |
| Q11 | correct | 0.8 | 1.0 | 1.0 | 1.0 / 1.0 | True | True | 4.7 | 78 | 0.111 | – |
| Q12 | correct | 0.8 | 1.0 | 0.25 | 1.0 / 0.25 | True | – | 4.6 | 82 | 0.110 | answered right but cited wrong |
| Q13 | partial | 0.7 | 1.0 | 1.0 | 0.75 / 1.0 | True | – | 6.7 | 126 | 0.219 | retrieved but answered wrong |
| Q14 | correct | 0.889 | 0.667 | 1.0 | 0.5 / 0.333 | True | True | 6.2 | 98 | 0.218 | answered right but cited wrong |
| Q15 | partial | 0.833 | 1.0 | 1.0 | 1.0 / 1.0 | True | – | 6.8 | 138 | 0.221 | retrieved but answered wrong |
| Q16 | correct | 0.889 | 1.0 | 1.0 | 0.667 / 1.0 | True | True | 8.5 | 96 | 0.205 | – |
| Q17 | correct | 0.9 | 1.0 | 1.0 | 0.4 / 1.0 | True | – | 11.9 | 97 | 0.261 | – |
| Q18 | correct | 0.889 | 1.0 | 1.0 | 0.4 / 1.0 | True | True | 6.5 | 117 | 0.252 | – |
| Q19 | incorrect | n/a | 0.333 | 0.333 | 1.0 / 0.333 | False | – | 6.6 | 99 | 0.103 | ingested but not retrieved |
| Q20 | correct | n/a | – | – | – / – | True | – | 6.7 | 68 | 0.090 | – |

## Lowest-scoring questions

Ranked by accuracy, then groundedness, citation recall and retrieval recall.

- **Q19** (silence vs absence): incorrect [ingested but not retrieved], groundedness n/a, citation recall 0.333, retrieval 0.333
  - Judge: Says no tiers and preferred brand, but marks not_in_documents and omits the flat $1.00 copay. The reference says the copay question is answerable from the documents.
  - Missing terms: $1.00
- **Q13** (prior auth process): partial [retrieved but answered wrong], groundedness 0.7, citation recall 1.0, retrieval 1.0
  - Judge: Prescriber-only rule, call center number, ePA routes and 72-hour supply match, but it omits the Standard PA fax form and gives a different URL than the reference's PDF.
  - Not fully supported: Be ready to answer questions that identify the prescriber, the patient, and the reason for the drug. (unsupported: No cited page describes what information the call center will ask for.) \| Some classes have their own worksheet. (unsupported: No cited page mentions class-specific worksheets.) \| Fax clinical documentation only if requested. (unsupported: No cited page addresses when to fax clinical documentation.)
- **Q15** (step therapy): partial [retrieved but answered wrong], groundedness 0.833, citation recall 1.0, retrieval 1.0
  - Judge: Correctly says IR tramadol first and covers opioid-naïve PA, 4-Rx limit and under-12 PA, but never mentions ConZip as non-preferred and ST-flagged.
  - Missing terms: ConZip
  - Not fully supported: PA is required if the patient is on a benzodiazepine. (partial: The PDL requires PA for initiation of opioid therapy in patients currently on benzodiazepine therapy. The answer drops the 'initiation' condition.) \| The ST and these edits are exempt for cancer, sickle cell disease, hospice or palliative care. (partial: The asterisked exemption is attached to the clinical criteria (CC). The source does not state that it applies to the step therapy requirement.)
- **Q06** (multi-document; structured formulary): partial [ingested but not retrieved], groundedness 0.909, citation recall 0.75, retrieval 0.75
  - Judge: PA requirement and commercial-first billing are correct, but it omits the VA guidance to avoid the combination and the recommended pharmacist medication review.
  - Not fully supported: Prescriber PA requests go through the Clinical Call Center at 1-877-309-9493. (partial: The source gives this number for questions on F/Q/D limits, not as the channel for submitting PA requests.)
- **Q07** (synthesis): partial [ingested but not retrieved], groundedness 0.929, citation recall 0.25, retrieval 0.5
  - Judge: Core conclusions match, but monitoring omits COWS/cravings, CBC and infectious disease testing, and it doesn't mention insufficient evidence to favor any MOUD for co-occurring pain.
  - Not fully supported: Reassess benefit vs harm at follow-up visits. (unsupported: None of the cited pages mention reassessing benefit vs harm at follow-up visits.)

## Random sample the judge marked correct

To check the judge isn't too lenient (sample seed 8323).

- **Q20** (absence): correct, groundedness n/a, citation recall –, retrieval –
  - Judge: Correctly states the documents don't cover pediatric amoxicillin dosing for otitis, declines to answer from general knowledge, and refers to an appropriate pediatric reference.
- **Q16** (reject code): correct, groundedness 0.889, citation recall 1.0, retrieval 1.0
  - Judge: Assumes NY Medicaid, identifies reject 22 as invalid DAW, advises DAW 9 and DAW 1 only with BMN; notes BLTG generic copay. Omits brand/U&C rate detail, minor.
  - Not fully supported: Generic liraglutide is non-preferred and needs PA. (partial: The page lists liraglutide (gen Victoza) as non-preferred but does not state that it requires PA.)
- **Q11** (coverage): correct, groundedness 0.8, citation recall 1.0, retrieval 1.0
  - Judge: Correctly states NY Medicaid assumption, Ozempic pen preferred, CC including indication and DPP-4 concurrent PA; omits other preferred agents but that's not key.
  - Not fully supported: Ozempic tablets are listed as non-preferred, so they need PA. (partial: The page lists Ozempic tablets as non-preferred, but it does not state that non-preferred drugs require PA.)

## Caveats

- **The judge is also a Claude model**, so it may share the agent's blind spots. Human spot checks of its grades (the two lists above) are the safeguard.
- **Each question ran once.** The agent isn't deterministic, so a one-question difference between setups may be noise.
- **VA formulary gold** (6 spreadsheet rows, from cells such as A1697:G1697) counts in the all-gold scores; a setup without the formulary lookup can't reach it, so compare setups on the PDF-pages-only scores too. Recall@k covers PDF pages only.
- **Failure classes are assigned by rule** (earliest stage that explains the miss), with ambiguous cases set by hand in `evals/failure_overrides.yaml`.
- **Citation precision is a lower bound**: a correct citation to a page outside the gold set counts against it. Read it together with groundedness.
- **Cold latency has n=0**: in one process only the first question loads the index, so the cold p95 is not a real percentile.
