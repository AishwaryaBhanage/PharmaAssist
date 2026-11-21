"""Deterministic claim checks, labels and assembly (agent/verify.py). Evidence strings are taken from
the corpus pages and lookup rows come from the real lookups on the local tables; nothing here calls
an API."""

import json
from datetime import date
from types import SimpleNamespace as NS

import pytest

from pharmassist.agent import verify as V
from pharmassist.tables import ny_pdl, va_formulary

TODAY = date(2026, 10, 16)
SGLT2_P5 = ("va_pbm_t2dm_pharmacotherapy_2025 (VA, advisory, 2025-04)\nSGLT2 inhibitors are first-line in T2DM "
            "with established ASCVD, HF or CKD, to be used regardless of HbA1c. Add metformin only if more "
            "glycemic control is needed.")
SGLT2_P4 = ("va_pbm_t2dm_pharmacotherapy_2025 (VA, advisory, 2025-04)\nInitiate an SGLT2 inhibitor for "
            "cardiorenal benefit when eGFR ≥ 20 mL/min/1.73 m2. Page 20 of the summary lists the agents.")
CONTACTS_P2 = ("ny_medicaid_pharmacy_policy (NY Medicaid, binding, 2026-07)\nPrior Authorization Clinical Call "
               "Center: (877) 309-9493. NYRx Education & Outreach (E&O): Website: "
               "https://newyork.fhsc.com/providers/education-outreach.asp Phone: 1-833-967-7310 Email: NYRxEO@primetherapeutics.com")
TPL_P18 = ("ny_medicaid_pharmacy_policy (NY Medicaid, binding, 2026-07)\nSubmitting a claim to Medicaid that "
           "bypasses the TPL's responsibility of payment is considered fraudulent billing and is subject to audit.")
COPAY_P42 = ("ny_medicaid_pharmacy_policy (NY Medicaid, binding, 2026-07)\nCo-payments are as follows: $3.00 for "
             "non-preferred Brand Name Drugs. $1.00 for Generic Drugs, preferred Brand Name Drugs.")
BUP_P76 = ("ny_medicaid_pdl (NY Medicaid, binding, 2026-09)\nbuprenorphine sublingual (SL): Eight tablets "
           "dispensed as a 2-day supply; not to exceed 32 mg per day. Ozempic is preferred effective 10/22/2026.")
EARLY_P30 = ("ny_medicaid_pharmacy_policy (NY Medicaid, binding, 2026-07)\nEarly refills: a pharmacy may submit "
             "an override for an early refill when the prescriber documents a dose increase.")
LTC_P10 = ("ny_medicaid_pharmacy_policy (NY Medicaid, binding, 2026-07)\nFor a new LTC admission, submit Submission "
           "Clarification Code (420-DK) of 18 (LTC Patient Admit/Readmit). SCC 18 overrides the refill-too-soon edit.")
GUIDE_2020_P17 = ("va_pbm_t2dm_clinicians_guide (VA, advisory, 2020-05)\nWhen prandial insulin is added to basal insulin, "
                  "continue metformin, DPP-4, SGLT-2, or GLP-1.")
PHARM_2025_P9 = ("va_pbm_t2dm_pharmacotherapy_2025 (VA, advisory, 2025-04)\nWhen starting prandial insulin in addition "
                 "to basal insulin, discontinue sulfonylurea, meglitinides, and DPP-4 inhibitors.")
PART_D_P2 = ("cms_partd_opioid_pharmacists_2022 (Medicare Part D, binding, 2022-01)\nWhen starting prandial insulin, "
             "plans may continue DPP-4 coverage.")

TEXT = {"va_pbm_t2dm_pharmacotherapy_2025:p5": SGLT2_P5, "va_pbm_t2dm_pharmacotherapy_2025:p4": SGLT2_P4,
        "ny_medicaid_pharmacy_policy:p2": CONTACTS_P2, "ny_medicaid_pharmacy_policy:p18": TPL_P18,
        "ny_medicaid_pharmacy_policy:p42": COPAY_P42, "ny_medicaid_pdl:p76": BUP_P76,
        "ny_medicaid_pharmacy_policy:p30": EARLY_P30, "ny_medicaid_pharmacy_policy:p10": LTC_P10,
        "va_pbm_t2dm_clinicians_guide:p17": GUIDE_2020_P17, "va_pbm_t2dm_pharmacotherapy_2025:p9": PHARM_2025_P9,
        "cms_partd_opioid_pharmacists_2022:p2": PART_D_P2}


def with_lookups(*results):
    """Evidence and per-result parts, with real lookup results recorded the way the ToolBox records
    them: each result's JSON as evidence for every page or row it returned."""
    parts = {loc: [text] for loc, text in TEXT.items()}
    for res in results:
        raw = json.dumps(res, ensure_ascii=False)   # as the ToolBox records lookup results
        locs = [va_formulary.locator(r["row"]) for r in res.get("rows", [])]
        locs += [f"ny_medicaid_pdl:p{r['cite']['page']}" for c in res.get("classes", []) for r in c["rows"]]
        for loc in locs:
            parts.setdefault(loc, []).append(raw)
    return {l: "\n\n".join(t) for l, t in parts.items()}, parts


def ctx(*lookups, question="q", queries=()):
    evidence, parts = with_lookups(*lookups)
    return V.Context(evidence, parts, question, TODAY, list(queries))


def claim(text, cites, type_="other", direct=False):
    return {"text": text, "type": type_, "direct_answer": direct,
            "citations": [{"doc_id": d, "page": p} if not str(p).startswith("r") else
                          {"doc_id": d, "page": None, "row": int(str(p)[1:])} for d, p in cites]}


def check(text, cites, type_="other", c=None, **kw):
    return V.check_claim(claim(text, cites, type_, **kw), c or ctx())


def causes(r):
    return sorted({p.cause for p in r["problems"]})


def kinds(r):
    return sorted({p.kind for p in r["problems"]})


# ---- structure ----

@pytest.mark.parametrize("text", [
    "It requires PA under NY Medicaid.", "This is permitted under NY Medicaid.", "Therefore no PA is needed under NY Medicaid.",
    "However, NY Medicaid requires PA for Mounjaro.", "The former applies to Medicare Part D.",
    "Supersedes the 2020 VA guidance.", "These limits apply to NY Medicaid films."])
def test_claims_opening_with_a_dependent_word_are_rejected(text):
    r = check(text, [("ny_medicaid_pdl", 76)])
    assert not r["passed"] and "dependent_start" in kinds(r) and "schema_rejection" in causes(r)


def test_this_mid_sentence_is_fine_and_every_claim_must_name_its_program():
    assert check("Under NY Medicaid, Ozempic is preferred as of 10/22/2026 per this PDL page.",
                 [("ny_medicaid_pdl", 76)])["passed"]
    r = check("Ozempic is preferred as of 10/22/2026.", [("ny_medicaid_pdl", 76)])
    assert kinds(r) == ["no_program"] and causes(r) == ["schema_rejection"]


def test_a_claim_that_one_source_governs_another_is_rejected():
    r = check("The 2025 VA PBM summary supersedes the 2020 VA guide.", [("va_pbm_t2dm_pharmacotherapy_2025", 9)])
    assert "source_precedence" in kinds(r)


@pytest.mark.parametrize("n_direct, ok", [(0, False), (1, True), (2, False)])
def test_exactly_one_direct_claim(n_direct, ok):
    claims = [claim(f"Under NY Medicaid, claim {i}.", [("ny_medicaid_pdl", 76)], direct=i < n_direct) for i in range(3)]
    problems = V.validate({"status": "answered", "claims": claims})
    assert (problems == []) is ok
    if not ok:
        assert problems[0].kind == "direct_count" and problems[0].cause == "schema_rejection"
    assert V.validate({"status": "out_of_scope", "claims": []}) == []


# ---- absence statements ----

ABSENT = "I did not find copay-tier information in the retrieved NY Medicaid evidence."


def test_a_qualified_absence_claim_passes_unchecked_with_its_searches_recorded():
    c = ctx(queries=["copay tier Trulicity", "What's the copay tier for Trulicity?"])
    r = V.check_claim(claim(ABSENT, [("ny_medicaid_pharmacy_policy", 42)], "corpus_absence"), c)
    assert r["passed"] and r["label"] == "unchecked"
    assert r["absence"]["queries"] == ["copay tier Trulicity", "What's the copay tier for Trulicity?"]
    assert "ny_medicaid_pharmacy_policy:p42" in r["absence"]["evidence_units"]


@pytest.mark.parametrize("question, ok", [
    ("What's the copay tier for Trulicity under NY Medicaid?", False),
    ("Is Trulicity covered by NY Medicaid?", False),
    ("Do the NY Medicaid documents mention copay tiers?", True),
    ("Does the pharmacy manual say anything about copay tiers?", True),
    ("Is there anything in the NY Medicaid documents about copay tiers?", True)])
def test_a_retrieval_miss_is_never_a_confirmed_negative(question, ok):
    """An absence claim is always unchecked, and is the direct answer only to a question about what
    the documents contain; otherwise the answer abstains as a schema rejection."""
    r = V.check_claim(claim(ABSENT, [("ny_medicaid_pharmacy_policy", 42)], "corpus_absence", True), ctx(question=question))
    assert r["label"] == "unchecked" and r["passed"] is ok
    if not ok:
        assert kinds(r) == ["absence_as_direct"] and causes(r) == ["schema_rejection"]
        text, abstained = V.assemble(HEADER, [r], [], [], labels=LABELS)
        assert abstained and ABSENT not in text and "(verified)" not in text


@pytest.mark.parametrize("text", ["NY Medicaid has no tiers.", "The NY Medicaid documents contain no tiers.",
                                  "No NY Medicaid tier information exists.",
                                  "I did not find tiers because NY Medicaid has no tiers in the retrieved evidence."])
def test_global_absence_wording_is_rejected(text):
    r = check(text, [("ny_medicaid_pharmacy_policy", 42)], "corpus_absence")
    assert not r["passed"] and "absence_wording" in kinds(r)


# ---- values, codes, drugs: own cited pages only ----

def test_an_unsupported_egfr_threshold_fails_as_evidence():
    r = check("VA guidance says to confirm eGFR ≥30 before starting an SGLT2 inhibitor.",
              [("va_pbm_t2dm_pharmacotherapy_2025", 5)], "threshold")
    assert not r["passed"] and causes(r) == ["evidence_failure"] and r["term_hints"] == ["eGFR"]


def test_a_value_on_an_uncited_returned_page_is_citation_only_and_never_re_cited():
    c = claim("VA guidance says to confirm eGFR ≥20 before starting an SGLT2 inhibitor.",
              [("va_pbm_t2dm_pharmacotherapy_2025", 5)], "threshold")
    r = V.check_claim(c, ctx())
    p = next(p for p in r["problems"] if p.kind == "uncited_support")
    assert not r["passed"] and p.cause == "citation_only" and p.locators == ["va_pbm_t2dm_pharmacotherapy_2025:p4"]
    assert c["citations"] == [{"doc_id": "va_pbm_t2dm_pharmacotherapy_2025", "page": 5}]


def test_values_found_are_values_checked_never_verified():
    r = check("Under NY Medicaid, buprenorphine SL is limited to 32 mg/day.", [("ny_medicaid_pdl", 76)], "dose")
    assert r["passed"] and r["label"] == "values_checked"
    r = check("Under NY Medicaid, the copay is $1 for generic drugs.", [("ny_medicaid_pharmacy_policy", 42)])
    assert r["passed"] and r["label"] == "values_checked"


def test_a_claim_with_nothing_checkable_is_unchecked():
    r = check("VA guidance says medication decisions are shared with the patient.", [("va_pbm_t2dm_pharmacotherapy_2025", 5)])
    assert r["passed"] and r["label"] == "unchecked"


def test_values_from_the_question_are_allowed():
    c = ctx(question="Patient takes 16 mg buprenorphine SL daily. Can we fill 24 mg?")
    r = V.check_claim(claim("Under NY Medicaid, a 16 mg daily buprenorphine SL dose is within the 32 mg/day limit.",
                            [("ny_medicaid_pdl", 76)], "dose"), c)
    assert r["passed"]
    r = V.check_claim(claim("Under NY Medicaid, a 40 mg/day buprenorphine SL dose is allowed.",
                            [("ny_medicaid_pdl", 76)], "dose"), c)
    assert not r["passed"]


def test_a_phone_number_for_the_wrong_purpose_fails():
    assert not check("Under NY Medicaid, call 1-833-967-7310 to request prior authorization.",
                     [("ny_medicaid_pharmacy_policy", 2)], "phone_number")["passed"]
    r = check("Under NY Medicaid, call the PA clinical call center at 1-877-309-9493.",
              [("ny_medicaid_pharmacy_policy", 2)], "phone_number")
    assert r["passed"] and r["label"] == "values_checked"


def test_overbroad_fraud_wording_fails():
    cite = [("ny_medicaid_pharmacy_policy", 18)]
    assert not check("Under NY Medicaid, any billing error is fraudulent billing.", cite)["passed"]
    assert check("Under NY Medicaid, submitting a claim to Medicaid that bypasses the TPL's responsibility of "
                 "payment is considered fraudulent billing.", cite, "legal_characterization")["passed"]


def test_billing_codes_must_be_on_the_cited_page():
    ok = check("Under NY Medicaid, a new LTC admission uses SCC 18 in field 420-DK.", [("ny_medicaid_pharmacy_policy", 10)],
               "billing_instruction")
    assert ok["passed"] and {e["value"] for e in ok["elements"] if e["kind"] == "code"} == {"SCC 18", "420-DK"}
    wrong_page = check("Under NY Medicaid, a new LTC admission uses SCC 18 in field 420-DK.",
                       [("ny_medicaid_pharmacy_policy", 42)], "billing_instruction")
    assert not wrong_page["passed"] and causes(wrong_page) == ["citation_only"]
    absent = check("Under NY Medicaid, use DAW 9 for this override.", [("ny_medicaid_pharmacy_policy", 10)],
                   "billing_instruction")
    assert not absent["passed"] and "unsupported_code" in kinds(absent)


def test_drug_names_must_be_on_the_cited_page():
    r = check("Under NY Medicaid, Rybelsus is limited to 32 mg/day.", [("ny_medicaid_pdl", 76)], "dose")
    assert not r["passed"] and "unsupported_drug" in kinds(r)


# ---- status against structured rows, field to field ----

def test_pdl_preferred_status_is_verified_against_the_row():
    c = ctx(ny_pdl.lookup("Trulicity"))
    r = V.check_claim(claim("Under NY Medicaid, Trulicity is preferred on the PDL.", [("ny_medicaid_pdl", 34)],
                            "coverage_rule", True), c)
    assert r["passed"] and r["label"] == "verified"
    wrong = V.check_claim(claim("Under NY Medicaid, Trulicity is non-preferred on the PDL.", [("ny_medicaid_pdl", 34)],
                                "coverage_rule", True), c)
    assert not wrong["passed"] and kinds(wrong) == ["status_mismatch"] and causes(wrong) == ["evidence_failure"]
    m = V.check_claim(claim("Under NY Medicaid, Mounjaro is non-preferred on the PDL.", [("ny_medicaid_pdl", 34)]),
                      ctx(ny_pdl.lookup("Mounjaro")))
    assert m["passed"] and m["label"] == "verified"


def test_pdl_pa_claims_are_at_most_values_checked_because_the_rows_have_no_pa_field():
    r = V.check_claim(claim("Under NY Medicaid, Mounjaro requires PA.", [("ny_medicaid_pdl", 34)]),
                      ctx(ny_pdl.lookup("Mounjaro")))
    assert r["passed"] and r["label"] == "values_checked"
    assert any("PA field" in (e.get("note") or "") for e in r["elements"])


def test_va_pa_status_is_verified_against_the_restriction_field_with_polarity():
    c = ctx(va_formulary.lookup("Ozempic"), va_formulary.lookup("empagliflozin"))
    yes = V.check_claim(claim("On the VA formulary, Ozempic requires PA (PA-F).", [(va_formulary.DOC_ID, "r1697")]), c)
    assert yes["passed"] and yes["label"] == "verified"
    no = V.check_claim(claim("On the VA formulary, Ozempic does not require PA.", [(va_formulary.DOC_ID, "r1697")]), c)
    assert not no["passed"] and kinds(no) == ["status_mismatch"]
    blank = V.check_claim(claim("On the VA formulary, empagliflozin does not require PA.", [(va_formulary.DOC_ID, "r717")]), c)
    assert blank["passed"] and blank["label"] == "verified"


def test_status_from_a_pdf_page_only_or_with_a_condition_is_at_most_values_checked():
    r = check("Under NY Medicaid, Ozempic is preferred as of 10/22/2026.", [("ny_medicaid_pdl", 76)])
    assert r["passed"] and r["label"] == "values_checked"
    c = ctx(va_formulary.lookup("Ozempic"))
    cond = V.check_claim(claim("On the VA formulary, Ozempic requires PA only when used for weight loss.",
                               [(va_formulary.DOC_ID, "r1697")]), c)
    assert cond["passed"] and cond["label"] == "values_checked"


# ---- assembly ----

HEADER = "NY Medicaid (stated in the question)"
LABELS = {"verified": "(verified)", "values_checked": "(values checked)", "unchecked": "(unchecked)"}


def checked(*claims_, c=None):
    c = c or ctx(ny_pdl.lookup("Trulicity"))
    return [V.check_claim(x, c) for x in claims_]


DIRECT = claim("Under NY Medicaid, Trulicity is preferred on the PDL.", [("ny_medicaid_pdl", 34)], "coverage_rule", True)
SIDE = claim("Under NY Medicaid, the copay for preferred brand-name drugs is $1.00.", [("ny_medicaid_pharmacy_policy", 42)],
             "billing_instruction")
CONDITIONAL = claim("Under NY Medicaid, an early refill override is permitted only when the plan rejects the claim as "
                    "refill too soon for 3 days.", [("ny_medicaid_pharmacy_policy", 30)], "billing_instruction")
EGFR = claim("VA guidance says to confirm eGFR ≥30 before starting an SGLT2 inhibitor.",
             [("va_pbm_t2dm_pharmacotherapy_2025", 5)], "threshold")


def test_the_response_is_assembled_in_order_with_fixed_lines_only():
    cs = checked(DIRECT, CONDITIONAL, SIDE, EGFR)
    text, abstained = V.assemble(HEADER, cs, [], [], labels=LABELS)
    assert not abstained
    assert text == (f"{HEADER}\n\n- {DIRECT['text']} [ny_medicaid_pdl p34] (verified)\n- {SIDE['text']} "
                    f"[ny_medicaid_pharmacy_policy p42] (values checked)\n\nI could not verify a billing instruction from the provided "
                    f"documents. I could not verify a threshold from the provided documents.")
    # the failed conditional and the failed threshold left nothing behind
    assert "early refill" not in text and "permitted" not in text and "30" not in text and "eGFR" not in text


def test_a_failed_direct_claim_abstains_and_hides_passing_supporting_claims():
    bad_direct = claim("Under NY Medicaid, Trulicity is non-preferred on the PDL.", [("ny_medicaid_pdl", 34)],
                       "coverage_rule", True)
    text, abstained = V.assemble(HEADER, checked(bad_direct, SIDE), [], [])
    assert abstained and text == f"{HEADER}\n\n{V.ABSTAIN}" and "$1.00" not in text


def test_a_structure_problem_abstains():
    two_direct = [DIRECT, {**SIDE, "direct_answer": True}]
    final = {"status": "answered", "claims": two_direct}
    text, abstained = V.assemble(HEADER, checked(*two_direct), V.validate(final), [])
    assert abstained


def test_out_of_scope_gets_the_fixed_line():
    assert V.assemble(V.NO_PROGRAM, [], [], [], status="out_of_scope") == (f"{V.NO_PROGRAM}\n\n{V.OUT_OF_SCOPE}", False)


# ---- source-precedence policy ----

POLICY = {"id": "recency_within_program_v1",
          "text": "Tool policy: the newer program-specific source is used: [{newer}] over [{older}]."}
NEW = claim("VA PBM 2025 guidance says to discontinue DPP-4 inhibitors when starting prandial insulin.",
            [("va_pbm_t2dm_pharmacotherapy_2025", 9)], "other", True)
OLD = claim("The VA 2020 clinician's guide says to continue DPP-4 when prandial insulin is added.",
            [("va_pbm_t2dm_clinicians_guide", 17)])


def policy(claims_, conflicts):
    cs = checked(*claims_, c=ctx())
    return V.policy_lines({"claims": claims_, "conflicts": conflicts}, cs, ctx().evidence, POLICY)


def test_a_flagged_qualifying_conflict_gets_the_policy_line():
    lines = policy([NEW, OLD], [{"first": 1, "second": 2}])
    # documents are named by short names derived from their catalog titles, with their dates
    assert lines == [{"policy_id": "recency_within_program_v1", "claims": [1, 2],
                      "docs": ["va_pbm_t2dm_pharmacotherapy_2025", "va_pbm_t2dm_clinicians_guide"],
                      "text": "Tool policy: the newer program-specific source is used: "
                              "[Pharmacotherapy for Type 2 Diabetes Mellitus 2025, 2025-04] over "
                              "[VA Clinician's Guide to Diabetes Management, 2020-05]."}]


def test_no_policy_line_without_a_qualifying_flagged_conflict():
    assert policy([NEW, OLD], []) == []                                         # not flagged
    part_d = claim("Medicare Part D plans may continue DPP-4 coverage when prandial insulin starts.",
                   [("cms_partd_opioid_pharmacists_2022", 2)])
    assert policy([NEW, part_d], [{"first": 1, "second": 2}]) == []              # different programs
    same_doc = claim("VA PBM 2025 guidance lists DPP-4 inhibitors among agents to discontinue.",
                     [("va_pbm_t2dm_pharmacotherapy_2025", 9)])
    assert policy([NEW, same_doc], [{"first": 1, "second": 2}]) == []            # same document
    failing = claim("The VA 2020 clinician's guide says to continue DPP-4 at 5 mg.", [("va_pbm_t2dm_clinicians_guide", 17)])
    assert policy([NEW, failing], [{"first": 1, "second": 2}]) == []             # one claim failed
    assert V.policy_lines({"conflicts": [{"first": 1, "second": 2}]}, checked(NEW, OLD, c=ctx()), ctx().evidence,
                          None) == []                                            # no configured policy


# ---- the offline audit ----

class FakeAuditClient:
    def __init__(self, verdicts):
        self.verdicts, self.requests = verdicts, []
        self.beta = NS(messages=NS(create=self.create))

    def create(self, **kw):
        self.requests.append(kw)
        return NS(content=[NS(type="text", text=json.dumps({"verdicts": self.verdicts}))], stop_reason="end_turn",
                  model=kw["model"], usage=NS(input_tokens=900, output_tokens=120, cache_read_input_tokens=0,
                                              cache_creation_input_tokens=0))


def test_the_audit_sees_only_cited_pages_and_returns_its_verdicts():
    client = FakeAuditClient([{"claim": 1, "verdict": "supported", "unsupported_words": "", "self_contained": True,
                               "reason": "stated"}])
    out = V.audit_claims(client, {"model": "claude-sonnet-5-5", "effort": "low"}, [SIDE], ctx().evidence, "copay?")
    sent = client.requests[0]["messages"][0]["content"]
    assert "$1.00 for Generic Drugs" in sent and "fraudulent" not in sent
    assert out["verdicts"][0]["verdict"] == "supported" and out["usage"]["input"] == 900


# ---- the header ----

@pytest.mark.parametrize("question, header", [
    ("This Veteran has T2DM and ASCVD.", "VA (stated in the question)"),
    ("NYRx copay for Trulicity?", "NY Medicaid (stated in the question)"),
    ("New York State Medicaid PA form?", "NY Medicaid (stated in the question)"),
    ("Patient has Medicare and NY Medicaid; which pays?", "Medicare Part D and NY Medicaid (stated in the question)"),
    ("QL on Ozempic pens?", "Coverage program not specified"),
    ("Is a VALID override available via the portal?", "Coverage program not specified"),
])
def test_the_header_comes_from_the_question(question, header):
    assert V.resolve_program(question)[0] == header


def test_a_trusted_program_filter_is_used_only_when_the_question_names_none():
    assert V.resolve_program("QL on Ozempic pens?", "NY Medicaid")[0] == "Assuming NY Medicaid"
    assert V.resolve_program("Does Part D cover it?", "NY Medicaid")[0] == "Medicare Part D (stated in the question)"


# ---- answer shape: numbered steps, coverage table, labels ----

def step(text, n, cites=(("ny_medicaid_pharmacy_policy", 2),), type_="other"):
    return {**claim(text, list(cites), type_), "step": n}


def test_numbered_steps_render_in_step_order_verbatim_with_gaps_kept():
    s1 = step("Under NY Medicaid, call the Prior Authorization Clinical Call Center at (877) 309-9493.", 1, type_="phone_number")
    s2 = step("Under NY Medicaid, send the request by fax to 555-0100.", 2)                        # fails: no such number
    s3 = step("Under NY Medicaid, keep the PA number with the claim.", 3)
    other = claim("Under NY Medicaid, the copay for preferred brand-name drugs is $1.00.",
                  [("ny_medicaid_pharmacy_policy", 42)], "billing_instruction")
    cs = checked(DIRECT, s3, other, s1, s2)
    text, abstained = V.assemble(HEADER, cs, [], [], labels=LABELS)
    blocks = text.split("\n\n")
    assert not abstained and blocks[0] == HEADER and blocks[1].startswith(f"- {DIRECT['text']} [")
    # step order, the model's numbers (the failed step 2 leaves a visible gap), text verbatim
    assert blocks[2] == (f"1. {s1['text']} [ny_medicaid_pharmacy_policy p2] (values checked)\n"
                         f"3. {s3['text']} [ny_medicaid_pharmacy_policy p2] {LABELS[cs[1]['label']]}")
    assert blocks[3] == f"- {other['text']} [ny_medicaid_pharmacy_policy p42] (values checked)"
    assert blocks[4] == "I could not verify a statement from the provided documents." and "555" not in text


def test_the_coverage_table_comes_only_from_returned_lookup_rows():
    c = ctx(ny_pdl.lookup("Trulicity"), va_formulary.lookup("Ozempic"))
    trul = V.check_claim(DIRECT, c)
    va = V.check_claim(claim("On the VA formulary, Ozempic requires PA (PA-F).", [(va_formulary.DOC_ID, "r1697")]), c)
    # Ozempic is on PDL p34 too, but no lookup returned its row: no table row for it
    oz = V.check_claim(claim("Under NY Medicaid, Ozempic is listed on PDL page 34.", [("ny_medicaid_pdl", 34)]), c)
    table, used = V.coverage_table([trul, va, oz], c.rows)
    assert [r["row_id"] for r in used] == ["ny_medicaid_pdl#p34#row-8", "va_national_formulary_2026_09#Formulary#row-1697"]
    assert table.splitlines() == [
        "| Drug | Program | Status (as stored) | Row |", "|---|---|---|---|",
        "| Trulicity® | NY Medicaid | listed_as: preferred | ny_medicaid_pdl#p34#row-8 |",
        "| SEMAGLUTIDE (EQV-OZEMPIC) INJ,SOLN | VA | Restriction: PA-F; Restriction meaning: PA-F: prior "
        "authorization required (see row 9) | va_national_formulary_2026_09#Formulary#row-1697 |"]
    # every cell is a stored field of a returned row (or the catalog program of its document)
    returned = json.dumps([ny_pdl.lookup("Trulicity"), va_formulary.lookup("Ozempic")], ensure_ascii=False)
    for line in table.splitlines()[2:]:
        drug, program, status, row = [x.strip() for x in line.strip("|").split("|")]
        assert row in returned and all(part in returned for part in drug.split(" ") if part)
        assert program in ("NY Medicaid", "VA")
        assert all(v.split(": ", 1)[1] in returned or v.endswith("(blank)") for v in status.split("; "))
    # no rows on the shown claims' citations: no table; nothing a claim says becomes a cell
    assert V.coverage_table([oz], c.rows) == ("", [])
    assert V.coverage_table([V.check_claim(SIDE, c)], c.rows) == ("", [])


def test_labels_are_displayed_and_values_checked_or_unchecked_never_show_as_verified():
    c = ctx(ny_pdl.lookup("Trulicity"))
    plain = claim("Under NY Medicaid, staff should read the PDL notes.", [("ny_medicaid_pdl", 34)])
    cs = [V.check_claim(x, c) for x in (DIRECT, SIDE, plain)]
    assert [x["label"] for x in cs] == ["verified", "values_checked", "unchecked"]
    text, _ = V.assemble(HEADER, cs, [], [], labels=LABELS)
    lines = text.split("\n\n")[1].splitlines()
    assert lines[0].endswith("(verified)") and lines[1].endswith("(values checked)") and lines[2].endswith("(unchecked)")
    assert text.count("(verified)") == 1


# ---- document identifiers: only a complete catalog identifier's span is exempt ----

def test_catalog_identifiers_come_from_the_catalog_titles():
    from pharmassist.agent.tools import catalog
    titles = " ".join(e["title"] for e in catalog().values())
    assert V.catalog_identifiers() and all(i in titles or i.replace(" ", "") in titles for i in V.catalog_identifiers())


def test_a_catalog_document_identifier_is_not_read_as_a_value():
    r = check("VA guidance (IB 10-1775) says to discontinue DPP-4 inhibitors when starting prandial insulin.",
              [("va_pbm_t2dm_pharmacotherapy_2025", 9)])
    assert r["passed"] and not any(e["kind"] in ("number", "year") for e in r["elements"])


def test_an_unknown_identifier_is_still_checked():
    r = check("VA guidance (IB 99-0000) says to discontinue DPP-4 inhibitors when starting prandial insulin.",
              [("va_pbm_t2dm_pharmacotherapy_2025", 9)])
    assert not r["passed"] and kinds(r) == ["unsupported_value"] and "99" in r["problems"][0].text


def test_a_dose_beside_a_known_identifier_is_still_checked():
    r = check("VA guidance (IB 10-1775) says to stop DPP-4 inhibitors at 10 mg when starting prandial insulin.",
              [("va_pbm_t2dm_pharmacotherapy_2025", 9)])
    assert not r["passed"] and [p.text for p in r["problems"]] == ["10 mg"]


def test_only_the_exact_identifier_span_is_excluded():
    text = "IB 10-1775 lists (877) 309-9493, 10/22/2026, SCC 18 and 20 mg; IB 10-17756 and IB 99-0000 are unknown."
    masked = V.mask_document_identifiers(text)
    assert len(masked) == len(text) and masked.startswith(" " * len("IB 10-1775") + " lists")
    raws = {v.raw for v in V.extract_values(masked)}
    assert {"(877) 309-9493", "10/22/2026", "18", "20 mg", "99"} <= raws
    assert "IB 10-17756" in masked and "IB 99-0000" in masked                 # not the complete identifier


# ---- status: only an unambiguous status predicated of a named drug or dosage form ----

@pytest.mark.parametrize("text, expected", [
    ("Under NY Medicaid, Trulicity is preferred.", [("preferred", "preferred")]),
    ("Under NY Medicaid, Butrans is non-preferred.", [("preferred", "non-preferred")]),
    ("On the VA formulary, the tablet formulation is non-formulary.", [("formulary", "non-formulary")]),
    ("Under NY Medicaid, Mounjaro requires prior authorization.", [("pa", "required")]),
    ("Under NY Medicaid, the PDL gives Trulicity's preferred/non-preferred status.", []),
    ("Under NY Medicaid, the PDL gives Trulicity a preferred or non-preferred status.", []),
    ("The VA row gives the formulary status of Ozempic.", []),
    ("The VA row gives the PA status of Ozempic.", []),
    ("NY Medicaid uses preferred and non-preferred status for brand drugs.", []),
])
def test_status_assertions_need_a_status_predicated_of_a_drug_or_dosage_form(text, expected):
    assert V.status_assertions(text) == expected


def test_status_checks_against_rows_positive_negative_dosage_form_and_mismatch():
    c = ctx(ny_pdl.lookup("Trulicity"), ny_pdl.lookup("Butrans"), va_formulary.lookup("semaglutide", "tablet"))
    pos = V.check_claim(claim("Under NY Medicaid, Trulicity is preferred.", [("ny_medicaid_pdl", 34)]), c)
    neg = V.check_claim(claim("Under NY Medicaid, Butrans is non-preferred.", [("ny_medicaid_pdl", 5)]), c)
    form = V.check_claim(claim("On the VA formulary, the semaglutide tablet is non-formulary.",
                               [(va_formulary.DOC_ID, "r1697")]), c)
    assert [x["label"] for x in (pos, neg, form)] == ["verified"] * 3 and all(x["passed"] for x in (pos, neg, form))
    # a field description beside a drug asserts nothing, so it can't mismatch
    desc = V.check_claim(claim("Under NY Medicaid, the PDL's preferred/non-preferred status column lists Trulicity "
                               "as preferred.", [("ny_medicaid_pdl", 34)]), c)
    assert desc["passed"] and desc["label"] == "verified"
    wrong = V.check_claim(claim("Under NY Medicaid, Butrans is preferred.", [("ny_medicaid_pdl", 5)]), c)
    assert not wrong["passed"] and kinds(wrong) == ["status_mismatch"]


# ---- atomicity and length ----

@pytest.mark.parametrize("text, kind", [
    ("Under NY Medicaid, Trulicity is preferred and has a $1 copay.", "compound_assertion"),
    ("Under NY Medicaid, Trulicity is preferred, but the documents do not provide a tier.", "compound_assertion"),
    ("Under NY Medicaid, Trulicity is preferred, whereas Mounjaro is non-preferred.", "compound_assertion"),
    ("Under NY Medicaid, Trulicity is preferred. Its copay is $1.", "multiple_sentences"),
    ("VA guidance says SGLT2 inhibitors are first-line, and metformin is added later.", "compound_assertion"),
    ("VA guidance says OUD is chronic, and discontinuation should rest on collaborative discussion.", "compound_assertion"),
])
def test_non_atomic_claims_are_rejected(text, kind):
    assert kind in {p.kind for p in V.atomicity_problems(text)}
    r = check(text, [("ny_medicaid_pdl", 34)])
    assert not r["passed"] and "schema_rejection" in causes(r)


@pytest.mark.parametrize("text", [
    "Trulicity is preferred under NY Medicaid.",
    "The cited NY Medicaid policy lists a $1 copay for preferred brand-name drugs.",
    "NY Medicaid coverage and billing policy applies to Trulicity.",
    "NY Medicaid requires PA for Mounjaro and Ozempic tablets.",
    "VA guidance lists monitoring of withdrawal (e.g. COWS), CBC, and renal and hepatic function.",
    "VA guidance lists CBC; renal function; hepatic function.",
    "Medicare Part D plans in the U.S. may apply a 7-day supply limit.",
    # a noun phrase joined by "and" after a reporting verb, and a verb inside a subordinate clause
    "VA guidance says adults with T2DM and ASCVD should take an SGLT2 inhibitor.",
    "VA guidance says an SGLT2 inhibitor can start in Veterans with T2DM and ASCVD even when A1c is at goal.",
    "NY Medicaid requires PA for patients using a GLP-1 and a DPP-4 inhibitor if both are dispensed.",
])
def test_one_assertion_with_conjoined_nouns_or_lists_is_atomic(text):
    assert V.atomicity_problems(text) == []


def test_length_is_a_warning_never_a_failure():
    base = "Under NY Medicaid, Trulicity is preferred"
    ok = base + " " + " ".join(["here"] * (35 - len(base.split()))) + "."
    long_ = ok[:-1] + " here."
    c = ctx(ny_pdl.lookup("Trulicity"))
    r35 = V.check_claim(claim(ok, [("ny_medicaid_pdl", 34)], direct=True), c)
    r36 = V.check_claim(claim(long_, [("ny_medicaid_pdl", 34)], direct=True), c)
    assert r35["warnings"] == [] and r35["passed"]
    assert [w["kind"] for w in r36["warnings"]] == ["length_violation"]
    assert r36["passed"] and r36["label"] == r35["label"] == "verified" and r36["problems"] == []   # verdict unchanged
    text, abstained = V.assemble(HEADER, [r36], [], [])
    assert not abstained and long_ in text


def test_unsupported_content_in_a_long_claim_still_fails_its_evidence_check():
    long_ = ("Under NY Medicaid, Trulicity is preferred on the PDL at a usual starting dose of 30 mg weekly "
             "for adults " + " ".join(["here"] * 20) + ".")
    assert len(long_.split()) > 35
    r = V.check_claim(claim(long_, [("ny_medicaid_pdl", 34)], direct=True), ctx(ny_pdl.lookup("Trulicity")))
    assert "length_violation" in [w["kind"] for w in r["warnings"]]
    assert not r["passed"] and "evidence_failure" in causes(r)


def test_more_than_four_supporting_claims_warns_but_omits_nothing():
    c = ctx(ny_pdl.lookup("Trulicity"))
    support = [claim(f"Under NY Medicaid, supporting note {w} applies.", [("ny_medicaid_pdl", 34)])
               for w in ("one", "two", "three", "four", "five", "six")]
    cs = [V.check_claim(x, c) for x in [support[0], DIRECT] + support[1:]]
    assert all(x["passed"] for x in cs)
    assert V.submission_warnings(cs, 4) == [{"kind": "supporting_claim_count_violation",
                                             "detail": "6 supporting claims; target at most 4"}]
    assert V.submission_warnings(cs[:5], 4) == []
    text, abstained = V.assemble(HEADER, cs, [], [])
    assert not abstained and all(f"note {w} applies" in text for w in ("one", "five", "six"))


def test_a_semicolon_rejects_a_supporting_claim_but_only_warns_on_the_direct_claim():
    c = ctx(ny_pdl.lookup("Trulicity"))
    text = "Under NY Medicaid, Trulicity is preferred; the PDL lists it on page 34."
    support = V.check_claim(claim(text, [("ny_medicaid_pdl", 34)]), c)
    assert not support["passed"] and kinds(support) == ["semicolon"] and causes(support) == ["schema_rejection"]
    direct = V.check_claim(claim(text, [("ny_medicaid_pdl", 34)], direct=True), c)
    assert direct["passed"] and direct["problems"] == []
    assert [w["kind"] for w in direct["warnings"]] == ["atomicity_warning"]
    shown, abstained = V.assemble(HEADER, [direct, support], [], [])
    assert not abstained and text in shown.split("\n\n")[1].splitlines()[0]
    assert shown.count(text) == 1 and "could not verify a statement" in shown


def test_both_sides_of_a_warned_direct_claims_semicolon_are_still_checked():
    c = ctx(ny_pdl.lookup("Trulicity"), ny_pdl.lookup("Butrans"))
    for text in ("Under NY Medicaid, Trulicity is preferred; the copay is $7.00.",          # value after it
                 "Under NY Medicaid, Butrans is preferred; Trulicity is preferred."):        # status before it
        r = V.check_claim(claim(text, [("ny_medicaid_pdl", 34), ("ny_medicaid_pdl", 5)], direct=True), c)
        assert "atomicity_warning" in [w["kind"] for w in r["warnings"]]
        assert not r["passed"] and "evidence_failure" in causes(r)
        assert V.assemble(HEADER, [r], [], [])[1] is True


# ---- drug names: whole tokens, punctuation as a boundary ----

@pytest.mark.parametrize("evidence", ["Use SGLT2 inhibitor (empagliflozin) in T2DM.", "Agents: empagliflozin, canagliflozin.",
                                      "The agent is empagliflozin.", "empagliflozin/SGLT2 class", "EMPAGLIFLOZIN is listed"])
def test_drug_names_match_across_punctuation_and_case(evidence):
    from pharmassist.tables import match
    assert V.has_name("empagliflozin", match.norm(evidence))
    assert "empagliflozin" in V.drug_names(evidence)
    c = V.Context({"va_pbm_t2dm_pharmacotherapy_2025:p4": evidence}, {}, "q", TODAY)
    r = V.check_claim(claim("VA guidance names empagliflozin for T2DM.", [("va_pbm_t2dm_pharmacotherapy_2025", 4)]), c)
    assert "unsupported_drug" not in kinds(r) and {"kind": "drug", "value": "empagliflozin", "checked": "presence"} in r["elements"]


def test_a_drug_name_never_matches_inside_a_longer_token():
    from pharmassist.tables import match
    for text in ("xempagliflozin", "empagliflozinx", "empagliflozin2", "preempagliflozinated"):
        assert not V.has_name("empagliflozin", match.norm(text))
        assert "empagliflozin" not in V.drug_names(text)
    c = V.Context({"va_pbm_t2dm_pharmacotherapy_2025:p4": "Use preempagliflozinated agents."}, {}, "q", TODAY)
    r = V.check_claim(claim("VA guidance names empagliflozin for T2DM.", [("va_pbm_t2dm_pharmacotherapy_2025", 4)]), c)
    assert kinds(r) == ["unsupported_drug"]


# ---- policy-line short names ----

@pytest.mark.parametrize("title, short", [
    ("VA/DoD Clinical Practice Guideline for the Management of Type 2 Diabetes Mellitus (Version 6.0)",
     "VA/DoD Clinical Practice Guideline"),
    ("A VA Clinician's Guide to Diabetes Management in Primary Care (IB 10-1402)", "VA Clinician's Guide to Diabetes Management"),
    ("Medicare Part D Opioid Policies: Information for Pharmacists", "Medicare Part D Opioid Policies"),
    ("Buprenorphine for Chronic Pain (IB 10-1497)", "Buprenorphine for Chronic Pain"),
    ("Pharmacotherapy for Type 2 Diabetes Mellitus (T2DM) 2025: A VA Clinician's Summary (IB 10-1775)",
     "Pharmacotherapy for Type 2 Diabetes Mellitus 2025"),
    (None, None), ("", None),
])
def test_short_names_come_from_titles(title, short):
    assert V.short_title(title) == short


def test_policy_line_uses_short_names_with_dates_and_falls_back_to_the_id(monkeypatch):
    from pharmassist.agent import tools
    lines = policy([NEW, OLD], [{"first": 1, "second": 2}])
    assert "[Pharmacotherapy for Type 2 Diabetes Mellitus 2025, 2025-04]" in lines[0]["text"]
    assert "[VA Clinician's Guide to Diabetes Management, 2020-05]" in lines[0]["text"]
    assert "va_pbm" not in lines[0]["text"]
    no_title = {k: {**v, "title": ""} if k == "va_pbm_t2dm_clinicians_guide" else v for k, v in tools.catalog().items()}
    monkeypatch.setattr(tools, "catalog", lambda: no_title)
    assert "[va_pbm_t2dm_clinicians_guide, 2020-05]" in policy([NEW, OLD], [{"first": 1, "second": 2}])[0]["text"]


def test_displayed_text_drops_citations_labels_and_row_ids_only():
    answer = ("NY Medicaid (stated in the question)\n\n- Under NY Medicaid, Trulicity is preferred. "
              "[ny_medicaid_pdl p34] (verified)\n\n| Drug | Program | Status (as stored) | Row |\n|---|---|---|---|\n"
              "| Trulicity® | NY Medicaid | listed_as: preferred | ny_medicaid_pdl#p34#row-8 |")
    shown = V.displayed_text(answer, LABELS)
    assert "[ny_medicaid_pdl p34]" not in shown and "(verified)" not in shown and "row-8" not in shown
    assert "Under NY Medicaid, Trulicity is preferred." in shown and "listed_as: preferred" in shown
