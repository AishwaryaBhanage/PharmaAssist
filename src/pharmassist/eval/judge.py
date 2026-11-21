"""The LLM judge: a stronger Claude model than the agent's, in two independent calls.

- accuracy: the answer against the reference answer (and its must_include terms)
- groundedness: the answer against the text of the pages it cites, without the reference, so a
  claim passes because a cited page supports it, not because it happens to be true

Both use structured outputs (this model rejects forced tool_choice), so each reply is one JSON object.
"""

import json

from pharmassist.agent.loop import _usage, cost_usd
from pharmassist.agent.tools import _pdf, catalog, parse_locator

JUDGE_TIMEOUT_S = 180  # a dropped connection otherwise hangs for the SDK's 10-minute default

ACCURACY_SYSTEM = """\
You grade answers from a pharmacy assistant against a reference answer written by a pharmacist. \
Grade against the reference and its notes only. Use no outside knowledge: don't mark a statement \
wrong, outdated or risky because of something you know that the reference and notes don't say. If \
your knowledge and the reference differ, follow the reference.

Grades:
- correct: reaches the reference's conclusion and includes its key facts (drugs, codes, limits, \
dates, conditions), and nothing in it contradicts the reference.
- partial: the core conclusion is right, but it misses a key fact or condition from the reference, \
or has a minor error that wouldn't change what the pharmacist does.
- incorrect: the core conclusion is wrong or missing; or a contradiction would change what the \
pharmacist does; or it declines an answerable question, or answers one the reference says the \
documents don't cover.

Don't penalize extra correct detail, wording, format or length. The reference notes explain the \
reasoning behind the reference; use them to interpret it.

For each must_include term, mark it present if the answer conveys that idea; paraphrase counts.

`reason`: one line, at most 30 words, naming what's missing or wrong, or why it's correct."""

GROUNDEDNESS_SYSTEM = """\
You check whether a pharmacy assistant's answer is supported by the sources it cites. You see the \
answer, and for each cited source its catalog details (title, program, document type, authority, \
date) and its text: a PDF page, or a spreadsheet row with its column names. Judge only against \
these sources and their catalog details. Use no outside knowledge: a true statement that no cited \
source supports is unsupported.

Catalog details count as support. A document's date, title, program or authority stated in the \
answer is supported when the catalog details give it.

The assistant must resolve conflicts between documents with these precedence rules, applied in order:
1. Match the program the question is about.
2. State over federal when both apply (dual-eligible patients follow Part D for drugs).
3. For coverage questions, binding policy over advisory guidance; for clinical questions, the \
clinical guidelines.
4. More recent over older.
A statement that applies these rules to the cited sources (e.g. "the 2025 guide is more recent, so \
it governs") is supported when the sources' catalog details and text bear it out; check the facts \
it relies on, not the rule itself.

Today's date is given: the assistant received it with the question. A statement comparing a \
source's date with today (e.g. "not in effect until 10/22/2026") is supported when the source gives \
the date and the comparison is right.

Split the answer into its factual claims (coverage status, PA/QL/step rules, codes, doses, limits, \
dates, process steps, what a document says or doesn't say). Skip the stated program assumption, \
generic advice (e.g. "ask the prescriber") and statements of what the assistant couldn't verify.

For each claim:
- supported: a cited page states it or directly implies it.
- partial: a cited page supports part of it, or a detail (number, date, condition) differs or is missing.
- unsupported: no cited page supports it.
A claim that the documents don't specify something is supported when the cited pages cover that \
topic and don't specify it.

`page`: the label of the source that best supports the claim (e.g. ny_medicaid_pdl:p34), or null. `note`: for partial or unsupported \
claims, what's missing; otherwise empty."""

ACCURACY_SCHEMA = {
    "type": "object",
    "properties": {
        "grade": {"type": "string", "enum": ["correct", "partial", "incorrect"]},
        "reason": {"type": "string"},
        "must_include": {"type": "array", "items": {
            "type": "object",
            "properties": {"term": {"type": "string"}, "present": {"type": "boolean"}},
            "required": ["term", "present"], "additionalProperties": False}},
    },
    "required": ["grade", "reason", "must_include"],
    "additionalProperties": False,
}

GROUNDEDNESS_SCHEMA = {
    "type": "object",
    "properties": {"claims": {"type": "array", "items": {
        "type": "object",
        "properties": {"claim": {"type": "string"},
                       "verdict": {"type": "string", "enum": ["supported", "partial", "unsupported"]},
                       "page": {"type": ["string", "null"]}, "note": {"type": "string"}},
        "required": ["claim", "verdict", "page", "note"], "additionalProperties": False}}},
    "required": ["claims"],
    "additionalProperties": False,
}


def _call(client, ecfg: dict, system: str, user: str, schema: dict) -> tuple[dict, float]:
    """One judge request; returns (the parsed JSON, cost in USD)."""
    resp = client.beta.messages.create(
        model=ecfg["judge_model"], max_tokens=ecfg["judge_max_tokens"], system=system,
        messages=[{"role": "user", "content": user}], timeout=JUDGE_TIMEOUT_S,
        output_config={"effort": ecfg["judge_effort"], "format": {"type": "json_schema", "schema": schema}})
    if resp.stop_reason != "end_turn":
        raise RuntimeError(f"judge stopped with {resp.stop_reason}")
    text = "".join(b.text for b in resp.content if b.type == "text")
    return json.loads(text), cost_usd(_usage(resp), ecfg["prices_per_mtok"])


def _answer_block(result: dict) -> str:
    return (f"Status: {result['status']}\nAssumption: {result['assumption']}\n\n"
            f"Answer:\n{result['answer']}")


def judge_accuracy(client, ecfg: dict, q: dict, result: dict, today: str) -> tuple[dict, float]:
    terms = "\n".join(f"- {t}" for t in q["must_include"])
    user = (f"Today's date: {today}\n\nQuestion: {q['question']}\n\n"
            f"Reference answer: {q['expected_answer']}\n\nReference notes: {q.get('notes') or 'none'}\n\n"
            f"Answerable from the documents: {'yes' if q['answerable'] else 'no'}\n\n"
            f"must_include terms:\n{terms}\n\n--- The assistant's reply ---\n{_answer_block(result)}")
    return _call(client, ecfg, ACCURACY_SYSTEM, user, ACCURACY_SCHEMA)


def page_text(doc_id: str, page: int, chars: int) -> str:
    text = _pdf(doc_id)[page - 1].get_text()
    return text[:chars] + "\n[page truncated]" if len(text) > chars else text


def catalog_details(doc_id: str) -> str:
    e = catalog()[doc_id]
    return (f"{e['title']} | program: {e['program']} | type: {e['doc_type']} | "
            f"authority: {e['authority']} | date: {e['date']}")


def source_text(locator: str, chars: int) -> str:
    """The text the judge checks a claim against: a PDF page, or a formulary row with its columns."""
    doc_id, kind, n = parse_locator(locator)
    if kind == "p":
        return page_text(doc_id, n, chars)
    from pharmassist.tables.va_formulary import row_text  # only formulary rows are cited by row
    return row_text(n)


def judge_groundedness(client, ecfg: dict, result: dict, locators: list[str],
                       today: str) -> tuple[dict, float]:
    """`locators`: the cited sources that exist ('doc:p34', 'doc:r1697'); unknown ones are left out."""
    sources = "\n\n".join(f"=== {loc} ===\nCatalog: {catalog_details(parse_locator(loc)[0])}\n\n"
                          f"{source_text(loc, ecfg['page_chars'])}" for loc in locators)
    user = (f"Today's date: {today}\n\n--- Cited sources ---\n{sources}\n\n"
            f"--- The assistant's reply ---\n{_answer_block(result)}")
    return _call(client, ecfg, GROUNDEDNESS_SYSTEM, user, GROUNDEDNESS_SCHEMA)
