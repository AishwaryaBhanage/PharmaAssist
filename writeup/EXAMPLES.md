# Example questions and answers

> Code paths in this document are relative to the [repository root](../); the write-ups live in `writeup/`.

**In 20 seconds.** Eight question/answer pairs from the production configuration, copied verbatim from the
evaluation results with the judge's grade and reason; nothing was re-run or edited. They cover every question
shape the assistant is designed for: multi-document (Q03), synthesis and conflicts (Q02, Q03, Q07), structured
data (Q08, Q17), silence vs absence (Q09, Q20), visual flowchart (V01). Three answers are weak and each says
where it fails, why, and how it would be fixed (Q13, V01, Q07). Run-level numbers: accuracy 0.85 with 0 incorrect
on 20 golden questions, 1.00 on 8 figure questions (`reports/evals/v2_2026-10-18_0903/summary.md`,
`reports/evals/v2_visual_2026-10-18_0916/summary.md`).

Sources: `reports/evals/v2_2026-10-18_0903/results.csv` (golden set) and `reports/evals/v2_visual_2026-10-18_0916/results.csv`
(figure questions). Agent `gpt-5.5` with `claude-sonnet-5-5` fallback, judged by `claude-opus-5-5` (3 passes).
Citations are `document:page` or `document:row` locators; the UI renders them as titles with page links. All 20
golden questions with references and answers side by side: the `answer`, `accuracy` and `judge_reason` columns
of the golden `results.csv`. Method and every run: [EVALUATION.md](EVALUATION.md).

### Q02 — conflict across versions (correct)

**Question.** The prescriber added mealtime insulin to this Veteran's basal insulin, but the DPP-4 is still on the refill list. Our older VA handout says continue it. Should I flag that for the pharmacist?

**Answer** (14.8 s, $0.170, groundedness 1.0):

> Assuming VA: **yes—flag it for pharmacist review.** The current VA PBM 2025 clinician summary’s prandial-insulin flowchart says that when starting prandial insulin in addition to basal insulin, **discontinue sulfonylurea, meglitinides, and DPP-4 inhibitor**. The older 2020 VA clinician guide did say to **continue DPP-4** when prandial insulin is added. Because these are VA clinical guidance documents answering the same question, use the **more recent 2025** guidance. Don’t independently stop the refill—queue it for RPh/prescriber cleanup.

**Citations.** `va_pbm_t2dm_clinicians_guide:p17; va_pbm_t2dm_pharmacotherapy_2025:p9`

**Judge: correct.** "Flags for pharmacist, cites 2025 guide's discontinue DPP-4 with prandial insulin, notes 2020 conflict, prefers newer guidance, advises against independent discontinuation."

Why it is here: both documents are retrieved, the precedence rule ("more recent over older") is applied and
named, and the other document gets its one line, as `REQUIREMENTS.md` asks.

### Q03 — multi-document, apparent conflict, dose vs coverage limit (correct)

**Question.** We received Suboxone 8/2 mg films, four daily, quantity 120 for 30 days, for OUD. The VA guide says the usual maximum is 24 mg, but NYRx lists up to 32 mg. Is this automatically excessive—and could we substitute the buprenorphine patch on the VA formulary?

**Answer** (21.6 s, $0.176, groundedness 1.0):

> Assuming NY Medicaid/NYRx: **not automatically excessive.** Four Suboxone 8/2 mg films daily = **32/8 mg/day**, qty **120/30 days**. NYRx MAT F/Q/D allows **four 8/2 mg films/day, max 120/30 days, not to exceed 32/8 mg/day**; this is in effect on 10/18/2026. VA’s OUD guide gives a **usual max 24 mg/day**, but also says higher doses may be used in some cases with careful monitoring and documented rationale.
>
> Do **not** substitute a buprenorphine patch for OUD: the VA patch is formulary, but VA guidance describes patches for **chronic pain**, not as an OUD equivalent to Suboxone film.

**Citations.** `ny_medicaid_pdl:p76; va_national_formulary_2026_09:r304; va_pbm_bup_chronic_pain:p2; va_pbm_bup_oud:p1; va_pbm_bup_oud:p2`

**Judge: correct.** "Correctly states 32/8 mg/day fits the NYRx limit, the VA 24 mg usual max permits higher doses with monitoring, and the patch is a chronic-pain product, not an OUD substitute."

Why it is here: four documents and a formulary spreadsheet row (`r304`, from `lookup_va_formulary`) in one
answer, with the coverage limit kept apart from the clinical "usual maximum". The slowest golden answer at
21.6 s, inside the 30 s limit.

### Q08 — structured data: claim code and conditional policy (correct)

**Question.** A new LTC resident arrived without meds, and their first fill rejects with 01642. Which override applies?

**Answer** (7.2 s, $0.054, groundedness 0.833):

> Assuming NY Medicaid: use the **New Patient Processing (NP)** override for Early Fill Overuse reject **01642** if this is an LTC servicing pharmacy and the resident was newly admitted without meds.
>
> Bill:
> 1. **439-E4 Reason for Service Code = NP**
> 2. **420-DK Submission Clarification Code = 18** (LTC Patient Admit/Readmit Indicator)
>
> This applies only when the claim is the **first dispensing after recent LTC admission** for the same drug/strength/directions and the eligibility response shows the applicable LTC facility indicator. Day supply is limited to **30 days** unless short-cycle billing applies.

**Citations.** `ny_medicaid_pharmacy_policy:p9`

**Judge: correct.** "Gives NP in 439-E4 plus SCC 18, states LTC pharmacy, recent admission with LTC eligibility indicator, first dispensing conditions, and the 30-day limit."

Why it is here: NCPDP fields and values read out of a billing table, with the conditions that gate them, as
numbered steps.

### Q09 — silence vs absence (correct)

**Question.** After prescriber approval, what code clears a Part D 90-MME alert? Do our documents specify one?

**Answer** (12.8 s, $0.225, groundedness 1.0):

> For **Medicare Part D**, our documents **do not specify a universal code** to clear the 90-MME opioid care-coordination alert after prescriber approval. CMS says to consult/confirm intent with the prescriber, document the discussion, and “submit the appropriate override code,” with POS override mechanisms available through the plan. So use the plan/PBM’s reject messaging or help desk instructions for the actual SCC/override values.
>
> Also, **569** appears in the DMP guidance as a reject/notice-related code, not as the documented code to clear the 90-MME alert.

**Citations.** `cms_partd_dmp_guidance_2019:p37; cms_partd_opioid_pharmacists_2022:p1`

**Judge: correct.** "States no code specified, describes consult/document/submit override process, directs to plan instructions; 569 clarification doesn't contradict reference."

Why it is here: the corpus covers the topic but not the detail. The assistant says so, gives what the documents
do say, and does not invent a code.

### Q17 — structured data: effective dates, table output (correct)

**Question.** Which diabetes products change preferred status on NY Medicaid on 10/22/2026?

**Answer** (21.4 s, $0.147, groundedness 1.0):

> NYRx PDP status changes effective **10/22/2026** are **not in effect yet** as of today, **10/18/2026**.
>
> | Product | Class | Status on 10/22/2026 |
> |---|---|---|
> | glucagon HCl emergency kit | Glucagon agents | **Preferred** |
> | Gvoke® pen/syringe/vial | Glucagon agents | **Preferred** |
> | Humalog® 100 U/mL vial/pen/cartridge | Rapid-acting insulin | **Preferred** |
> | Humalog® Jr. 100 U/mL KwikPen | Rapid-acting insulin | **Preferred** |
> | insulin aspart cartridge/vial/pen (gen Novolog®) | Rapid-acting insulin | **Non-preferred** |
>
> Non-preferred products generally require PA unless otherwise indicated.

**Citations.** `ny_medicaid_pdl:p1; ny_medicaid_pdl:p34; ny_medicaid_pdl:p37`

**Judge: correct.** "Lists all five products with correct status changes and effective date; omitting the note that no GLP-1/DPP-4/SGLT2 change is minor, not contradictory."

Why it is here: a table because the question is a list of statuses, and the effective-date markers (6.96 pt
digits in the PDL) were extracted into the rows (`src/pharmassist/tables/ny_pdl.py`).

### Q20 — absence: off-corpus question (correct)

**Question.** What's the best amoxicillin dosing for pediatric ear infections?

**Answer** (10.2 s, $0.106):

> No answer found in knowledge base

**Citations.** none (`status: no_answer`)

**Judge: correct.** "Correctly declines; states no answer found in knowledge base, matching reference that the topic is outside the documents."

Why it is here: the exact sentence `REQUIREMENTS.md` asks for, after two searches found nothing relevant.
No-answer results are never cached.

### Q13 — prior auth process (partial: a weak answer)

**Question.** How do I start a PA for a non-preferred drug for an NY Medicaid pt: who do I contact and what form?

**Answer** (9.1 s, $0.052, groundedness 1.0):

> Assuming NY Medicaid/NYRx: for a non-preferred PDL drug, the PA must be submitted by the **prescriber or the prescriber’s authorized agent**—a dispensing pharmacist is not an authorized agent unless employed by the prescriber’s office.
>
> 1. **Phone PA:** call the NYRx Clinical Call Center: **1-877-309-9493**.
> 2. **ePA:** use **CoverMyMeds**; the pharmacy may start the case, but it routes to the prescriber to complete/submit.
> 3. **Fax form:** download the NYRx PA fax form at **https://newyork.fhsc.com/providers/PA_forms.asp**.
> 4. If urgent and prescriber can’t be reached, pharmacist may request up to a **72-hour emergency supply** PA.

**Citations.** `ny_medicaid_pdl:p1; ny_medicaid_pharmacy_policy:p15; ny_medicaid_pharmacy_policy:p16`

**Judge: partial.** "Gives prescriber-only rule, call center number, CoverMyMeds, and 72-hour supply, but omits PAXpress and gives a different fax-form URL instead of the Standardized PDF."

Why it fails: failure class "retrieved but answered wrong" (`results.csv`, Q13). The pages naming PAXpress and
the standardized fax form were returned by the search and every claim in the answer is supported (groundedness
1.0), but the model stopped after one lookup of the six allowed and summarized the PA channels incompletely.
This is the core use case ("what's the prior auth process?"), so it is the miss that
matters most.

How it would be fixed: two mechanisms were built and measured on 2026-10-18 as config flags
(`agent.min_lookups`, `agent.completeness_pass`): refusing an answered submit after a single lookup once, and one
extra model turn that adds omitted channels, limits and dates from the evidence already in context. They raised
groundedness (0.937 → 0.942), halved unsupported claims (2.5% → 1.2%) and fixed Q18, but left Q13 partial and
added 8 s of median latency, so they are off in production (`reports/evals/v2_complete_2026-10-18_1819`;
EVALUATION.md §4.5). The remaining lever is a prompt rule for "who do I contact / what form" questions:
enumerate every channel the page lists before submitting.

### V01 — flowchart branch (correct answer, wrong page cited: a weak answer)

**Question.** Per the VA/DoD diabetes guideline's T2DM management algorithm, a patient has no ASCVD, nephropathy or heart failure and is not at their glycemic target. What is the next step?

**Answer** (6.6 s, $0.040, groundedness 0.0):

> Per the **VA/DoD T2DM management algorithm**: if the patient has **no established ASCVD/high ASCVD risk, no diabetic nephropathy, and no HF**, skip the GLP-1 RA/SGLT-2 comorbidity-driven step and assess glycemic target. If the patient is **not at target**, the next step is to **consider additional glucose-lowering medications until the target A1C range is achieved**, selecting the agent based on **efficacy and overall risk–benefit ratio**; the algorithm points to **CPG Appendix B** for medication selection support.

**Citations.** `va_dod_cpg_diabetes_2023:p21`

**Judge: correct.** "Matches reference: skips GLP-1/SGLT-2 step, then add medications until target A1C based on efficacy and risk-benefit, citing Appendix B."

Why it is weak: the groundedness judge scored it 0.0 because, in its words, "The cited page has only the
guideline title, the 'Module A: T2DM Management' heading and an abbreviation list. It contains none of the
algorithm's decision steps." The flowchart is a raster image on page 21; the vision pass read it into a figure
record (`va_dod_cpg_diabetes_2023:p21:f0`) and the citation points at that page, but the judge is given the
page's extracted *text*, which for an image page is just the heading. The golden set's gold pages are the
appendix (p145–146) where the same algorithm is printed as text; the agent never retrieved those. All five
"answered right but cited wrong" cases in the visual run are this pattern (`v2_visual_2026-10-18_0916/summary.md`).

How it would be fixed: (1) in measurement, give the groundedness judge the figure interpretation for any cited
page that carries a figure (`scripts/run_eval.py`, `src/pharmassist/eval/judge.py`), which would move the visual
groundedness (0.614) without changing any answer; (2) in the product, cite the figure explicitly (crop link
plus "figure on p21"; the UI's `FigureNote` already does the first part) and add the appendix page as a second
citation.

### Further weak answer: Q07 — synthesis (partial)

Question: "For OUD with chronic pain, can buprenorphine continue long term, can doses be split, and what
monitoring is needed?" Judge: partial, "Covers continuation, BID/TID splitting and monitoring, but claims BUP/NX
may be preferred for pain, contradicting the reference's insufficient-evidence point; also omits monitoring
frequency." Failure class "ingested but not retrieved": four searches, 63,935 input tokens, $0.38, and the page
with the insufficient-evidence statement was not among the results. Full text in
`reports/evals/v2_2026-10-18_0903/results.csv`.

How it would be fixed: a retrieval miss, so answer-side changes cannot help (the completeness pass left it
partial). The measured levers are the cross-encoder reranker at depth 50 (Recall@10 0.958 → 1.000,
`reports/retrieval/2026-10-18_0043/results.md`), which needs hardware the current servers lack (EVALUATION.md
§4.2), and one search per sub-question ("continue long term", "split doses", "monitoring") instead of one
combined query.

### Run-level numbers for context

| Run | Accuracy | Correct / partial / incorrect | Groundedness | Safe | p50 / p95 | Agent $/question |
|---|---|---|---|---|---|---|
| Golden, 20 questions (`v2_2026-10-18_0903`) | 0.85 | 14 / 6 / 0 | 0.937 | 17/20 | 10.8 s / 21.4 s | 0.110 |
| Visual, 8 questions (`v2_visual_2026-10-18_0916`) | 1.00 | 8 / 0 / 0 | 0.614 | 5/8 | 6.5 s / 6.9 s | 0.052 |

Judge grades are estimates from a Claude model and each question ran once; see "Caveats" in each `summary.md`.

### The six partial answers in the production run, by mechanism

| Question | Shape | What the reference has that the answer lacks | Mechanism |
|---|---|---|---|
| Q01 | conflict across versions; synthesis | the 2020 metformin-first sequence conflict; "clinical recommendation does not guarantee coverage" | evidence retrieved (recall@10 1.0); model left it out |
| Q06 | multi-document; structured formulary | the VA "avoid the combination" advice; the medication-review recommendation | gold page never retrieved (recall@10 0.5) |
| Q07 | synthesis | monitoring frequency; the insufficient-evidence point on BUP/NX for pain | gold pages never retrieved (recall@10 0.25) |
| Q10 | apparent conflict; document purpose | PBM's preference for non-opioid care | gold page never retrieved (recall@10 0.33) |
| Q13 | prior auth process | PAXpress; the standardized fax form | evidence retrieved; 1 lookup; model left it out |
| Q18 | coverage, no program stated | the other no-PA MAT products (films, Zubsolv, Sublocade, Brixadi) | evidence retrieved; model left it out |

Three are retrieval misses and three are omissions with the evidence in hand (`results.csv`, `failure_class`
column); the question shape alone does not predict them: five other multi-document and conflict questions were
graded correct. No answer in the run was graded incorrect.
