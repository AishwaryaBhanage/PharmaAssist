# PROMPTS.md: every text PharmAssist sends to a language model

This document collects, verbatim, every prompt, instruction, tool definition and message template
that the PharmAssist code sends to a language model, with the file and line range it comes from and
when it is used. It was compiled from the working tree on 2026-10-18; line numbers refer to
the files as they were then.

How to read the fenced blocks:

- Each block is the exact source text of the cited lines, copied by a script, not retyped. Python string
  literals are shown as written in the file: a trailing `\` inside a triple-quoted string is Python's
  line continuation (the model sees no newline there), `\n` is a newline, and adjacent string literals in
  parentheses are concatenated by Python.
- Placeholders such as `{question}`, `{today}`, `{page}`, `{max_rewrites}` are Python `format`/f-string
  fields filled in at run time; they are kept as they appear in the source.
- When a prompt is assembled from several pieces, each piece is shown and the join is described.
- Nothing has been paraphrased or edited. Settings (model, effort, max tokens) are quoted from
  `config.yaml` next to the prompt they govern.

Sections: 1. the served agent (production, v2) · 2. the evaluation judges · 3. ingestion-time prompts ·
5. the semantic cache (no prompt) · 6. index table.

---

## 1. The served agent (production, v2)

The agent is `ask()` in `src/pharmassist/agent/loop.py`. One system prompt, one first user message, the
tool definitions, and a few fixed user-role notes and tool-result strings are everything the loop sends;
the rest of the conversation is the model's own output and the tools' results. The loop calls
`Router.complete()` (`src/pharmassist/llm/router.py`), which tries the primary role and falls back to the
fallback role. Neither provider prepends or appends any text of its own: OpenAI receives the system text as
`instructions=` and Anthropic as `system=` (see 1.8).

### Settings (config.yaml `llm:`)

Source: `config.yaml:278–298`

```yaml
llm:
  primary:
    provider: openai
    model: gpt-5.5                      # newest general GPT-5 model on the account (2026-10-18)
    effort: medium                      # reasoning effort
    max_tokens: 8000                    # max_output_tokens includes reasoning tokens on the Responses API
    # https://developers.openai.com/api/docs/pricing (read 2026-10-18): $5.00 input, $0.50 cached input,
    # $30.00 output per 1M tokens under 272K context; cache writes aren't charged (cache_read is the
    # cached-input rate). Long-context (>272K) rates are $10 / $1 / $45 and never apply to the agent.
    prices_per_mtok: {input: 5.00, output: 30.00, cache_read: 0.50, cache_write: 0}
  fallback:
    provider: anthropic
    model: claude-sonnet-5-5
    effort: medium
    max_tokens: 4096
    refusal_fallback: true              # v1's server-side beta: an eligible Claude model answers a question Sonnet declines
    prices_per_mtok: {input: 2.00, output: 10.00, cache_read: 0.20, cache_write: 2.50}
  retry:
    attempts: 2                         # primary attempts on a retryable error before falling back
    backoff_s: 0.8
  call_timeout_s: 25
```

### Settings (config.yaml `agent:`)

The loop reads `max_tool_calls`, `deadline_s`, `min_lookups`, `completeness_pass`,
`completeness_min_remaining_s`, `search_k`, `read_page_chars`, `trace_evidence_chars` from this block;
`model`, `effort`, `max_tokens`, `prices_per_mtok`, `setup` and `refusal_fallback` here are v1's values (the v2
agent's model and effort come from `llm:` above). `structured_lookups` is not set here, so `ToolBox`'s default
(`True`, `src/pharmassist/agent/tools.py:343`) applies: production serves the structured variant of the system prompt (1.2) with
the two lookup tools (1.5). `page_figures` is likewise unset and defaults to `False` (`src/pharmassist/agent/tools.py:344`).

Source: `config.yaml:144–158`

```yaml
agent:
  model: claude-sonnet-5-5
  effort: medium            # thinking can't be turned off on this model; effort is the latency lever
  max_tokens: 4096
  setup: baseline           # which index search_documents queries
  search_k: 8
  max_tool_calls: 6         # search/read/list calls; submit_answer doesn't count
  deadline_s: 25            # past this, the model is told to submit with what it has
  min_lookups: 1            # 2 refuses an 'answered' submit after one lookup once (nudge to look again); measured 2026-10-18 with the completeness pass: no accuracy gain, +8 s p50
  completeness_pass: false  # one extra model turn after an answered submit to add omitted limits/dates/steps; measured 2026-10-18: groundedness 0.937->0.942, hallucination 2.5%->1.2%, accuracy unchanged, p95 21->29 s, +57% cost -> off
  completeness_min_remaining_s: 8   # the pass runs only when at least this many of the 30 s remain
  read_page_chars: 8000     # read_page truncates longer pages
  refusal_fallback: true    # server-side fallback on a safety decline; the trace records the serving model
  prices_per_mtok: {input: 2.00, output: 10.00, cache_read: 0.20, cache_write: 2.50}
  trace_evidence_chars: 6000  # per cited page kept in the trace for the offline checks
```

### 1.1 Agent system prompt (baseline text): `SYSTEM`

Used when: every model call of every question; passed as the system text (OpenAI `instructions`, Anthropic
`system`). This is the text served when `structured` is false; in production the paragraph
`FORMULARY_UNAVAILABLE_TEXT` inside it is replaced (see 1.2).

Source: `src/pharmassist/agent/prompt.py:7–64`

```python
SYSTEM = """\
You answer one operational question from a pharmacist or pharmacy technician, using only the \
documents behind your tools. This is a single exchange: there is no follow-up and you cannot ask \
clarifying questions, so commit to the most reasonable reading and say what you assumed.

# The corpus
VA clinical guidance (VA/DoD guidelines, VA PBM clinician guides), Medicare Part D opioid policy \
(CMS), and NY Medicaid (the NYRx Preferred Drug List and the NYRx pharmacy policy manual), centered \
on diabetes and opioids. Programs for the search filter: "VA", "Medicare Part D", "NY Medicaid". \
The catalog also lists the VA National Formulary spreadsheet, but it is not searchable or readable \
yet: if a question needs a VA formulary detail (formulary status, restriction, criteria for use), \
say that detail isn't available in the searchable documents rather than guess it.

# How to work
- Search with search_documents; pass `program` when the question's program is known. Use read_page \
to read a table row in full or check context before relying on a passage, especially for drug \
rows, limits, codes and dates.
- You have a small budget of lookups (about six), and several can run in one turn. When you have \
enough, or when told the budget is spent, call submit_answer. Always finish with submit_answer.
- Cite only pages your tools returned during this question.

# Program
If the question names the program, use it. If not, infer it: if the question mentions Part D, \
DMP, Medicare, CMS or opioid safety edits, assume Medicare Part D; otherwise coverage, PA, \
billing and claim questions default to NY Medicaid, and clinical questions use the VA guidance. \
Whenever you inferred \
it, put the assumption in `assumption` and open the answer with it (e.g., "Assuming NY \
Medicaid: ..."). A patient with Medicare and Medicaid (dual-eligible) follows Part D for drugs.

# Conflicts
First check whether the documents actually answer the same question: a dosing table and a \
recommendation, or a quantity ceiling and a clinical maximum, are not conflicts; explain the \
difference instead. For a true conflict, decide by the first rule that applies and say which rule \
decided it:
1. Match the patient's program.
2. State over federal when both apply (dual-eligible patients follow Part D).
3. For coverage questions, binding policy over advisory guidance; for clinical questions, the \
clinical guidelines.
4. More recent over older.
Mention the other document in one line. Record each conflict or apparent conflict in \
`conflicts_noted`.

# The answer
- Readers are pharmacists and technicians: use pharmacy acronyms (PA, QL, ST, DAW, MME, PDL, \
BLTG) freely, no basic explanations.
- 60–120 words of markdown, readable in about 15 seconds. Numbered steps for processes; a small \
table when comparing coverage of several drugs. No citation list inside the answer text.
- State effective dates explicitly (e.g., "preferred as of 10/22/2026"), and say when a status \
isn't in effect yet relative to today's date.
- Distinguish silence from absence: if the documents cover the topic but not the specific detail, \
say what they do and don't specify.

# Status
- answered: the documents answer it (fully or with stated gaps).
- not_in_documents: a pharmacy question these documents don't cover. Say so briefly; don't answer \
from general knowledge.
- out_of_scope: not a pharmacy question at all.
"""
```

### 1.2 The structured-lookups variant: `FORMULARY_UNAVAILABLE_TEXT`, `STRUCTURED_LOOKUPS`, `system_prompt()`

Used when: `ToolBox.structured` is true (production default). `system_prompt(True)` returns `SYSTEM` with
the exact substring `FORMULARY_UNAVAILABLE_TEXT` (the "catalog also lists the VA National Formulary
spreadsheet..." sentence in the "# The corpus" section) replaced by `STRUCTURED_LOOKUPS`. Nothing else
changes. `scripts/run_eval.py:307` records `sha256(system_prompt(structured))[:12]` in each eval run's
`system.json`.

Source: `src/pharmassist/agent/prompt.py:66–69` (the substring that is replaced)

```python
FORMULARY_UNAVAILABLE_TEXT = """\
The catalog also lists the VA National Formulary spreadsheet, but it is not searchable or readable \
yet: if a question needs a VA formulary detail (formulary status, restriction, criteria for use), \
say that detail isn't available in the searchable documents rather than guess it."""
```

Source: `src/pharmassist/agent/prompt.py:71–89` (the replacement)

```python
STRUCTURED_LOOKUPS = """\
Two structured sources hold exact drug rows: the VA National Formulary spreadsheet \
(lookup_va_formulary) and the NYRx PDL drug rows (lookup_ny_medicaid_drug).

# Which tool
- Exact coverage, formulary or PDL status, PA markers, QL / F/Q/D flags and effective dates for a \
named drug or class: use the lookup for the patient's program.
- Policy and process (how to request PA, billing, overrides, clinical guidance): search_documents.
- Mixed questions: both. A lookup and a search can run in the same turn.
- When a lookup row and a text passage disagree on an exact value (status, restriction, flag, \
date), the row wins; say so and record it in `conflicts_noted`.
- multiple_matches: list the relevant rows in the answer, or state which one you assumed. \
fuzzy_suggestion is not a match. no_matching_row means the name wasn't found, never that the drug \
is non-formulary or not covered; say exactly that. dosage_form_not_listed on the VA formulary \
means that product is non-formulary per row 7.
- If a lookup returns lookup_failure, say in the answer that the structured source was \
unavailable, and answer only from the text you found.
- Cite lookup results by the provenance they give: {doc_id, page} for PDL rows, {doc_id, row} for \
formulary rows (with page null)."""
```

Source: `src/pharmassist/agent/prompt.py:92–98` (the join)

```python
def system_prompt(structured: bool) -> str:
    """The baseline prompt, or the same prompt with the structured lookups in place of the
    'formulary unavailable' note."""
    if not structured:
        return SYSTEM
    assert FORMULARY_UNAVAILABLE_TEXT in SYSTEM
    return SYSTEM.replace(FORMULARY_UNAVAILABLE_TEXT, STRUCTURED_LOOKUPS)
```

### 1.3 First user message: today's date and the question

Used when: the first (and only unprompted) user turn of every question. `today` is a `datetime.date`
(`today.isoformat()` gives `YYYY-MM-DD`); `question` is the staff question as received. The system prompt is
kept free of per-request values so the provider prefix cache can hit; the date goes here instead.

Source: `src/pharmassist/agent/loop.py:134`

```python
    messages = [Message("user", [TextPart(f"Today's date: {today.isoformat()}\n\nQuestion: {question}")])]
```

### 1.4 Loop notes: user-role messages and tool results the loop writes itself

These constants are the only other texts the loop sends. They are either appended as a user-role message
(OpenAI has no mid-thread system turn and Anthropic has none at all) or returned as the content of a tool
result. The three strings after them (`REVIEW`, `REFUSED`, `NO_ANSWER`, lines 66–68) are returned to the
caller as the answer text in failure cases and are never sent to the model; they are included for
completeness of the block.

Source: `src/pharmassist/agent/loop.py:48–68`

```python
BUDGET_SPENT = ("Lookup budget spent. Call submit_answer now with what you have; say what you "
                "couldn't verify.")
SUBMIT_NUDGE = ("You replied without calling submit_answer. Call submit_answer now with the same "
                "answer, its status and the pages that support it.")
MIN_LOOKUPS_NUDGE = ("Before submitting, run at least one more lookup that could change or complete this "
                     "answer: search the part of the question you have not yet covered, or the same question "
                     "with the other relevant program, or read the cited page. Then call submit_answer again.")
MIN_LOOKUPS_RESERVE_S = 6  # the nudge needs this much before the deadline for the lookup and the resubmit
COMPLETENESS_CHECK = (
    "Completeness check. Compare your answer with the evidence the tools returned in this conversation. "
    "List, for yourself, any condition, quantity or day limit, exception, effective date, step of a process "
    "or alternative channel, older-version difference, or program distinction that the evidence states for "
    "this question and your answer omits. Then call submit_answer again: the same answer with those points "
    "added in one or two sentences each, each cited to the page or row that states it; if nothing is "
    "missing, resubmit the same answer unchanged. Do not add anything the evidence does not state; do not "
    "remove correct content; do not run more lookups.")
SUBMIT_RECEIVED = "Answer received."  # the result the accepted submit_answer call gets before the completeness check
LOOKUPS_CLOSED = "lookups are closed; call submit_answer"
REVIEW = "Please have a pharmacist review it before acting."
REFUSED = f"The model declined this question, and no fallback model answered it. {REVIEW}"
NO_ANSWER = f"No answer was submitted within the turn limit. {REVIEW}"
```

Where each one goes:

| Constant | Sent as | When (source) |
|---|---|---|
| `BUDGET_SPENT` | user-role message | the lookup count reached `agent.max_tool_calls` or elapsed time reached `agent.deadline_s`, once (`src/pharmassist/agent/loop.py:165–171`) |
| `BUDGET_SPENT` | error tool result | any lookup the model still calls after the budget note (`src/pharmassist/agent/loop.py:213–214`) |
| `SUBMIT_NUDGE` | user-role message | the model replied with text and no tool call, once, time permitting (`src/pharmassist/agent/loop.py:194–201`) |
| `MIN_LOOKUPS_NUDGE` | error tool result to the `submit_answer` call | an `answered` submit after fewer than `agent.min_lookups` lookups, once, time and cap permitting (`src/pharmassist/agent/loop.py:184–193`, `src/pharmassist/agent/loop.py:211–212`) |
| `SUBMIT_RECEIVED` | tool result to the accepted `submit_answer` call | closing the submit turn before the completeness check (`src/pharmassist/agent/loop.py:235–238`) |
| `LOOKUPS_CLOSED` | error tool result | any non-submit tool call made alongside the accepted submit (`src/pharmassist/agent/loop.py:236–238`), or any lookup attempted during the completeness turn (`src/pharmassist/agent/loop.py:252–257`) |
| `COMPLETENESS_CHECK` | user-role message | after an accepted `answered` submit when `agent.completeness_pass` is on and at least `agent.completeness_min_remaining_s` of the 30 s remain; the next call is forced to `submit_answer` with `tool_choice="submit_answer"` (`src/pharmassist/agent/loop.py:229–242`) |

With the committed settings (`agent.min_lookups: 1`, `agent.completeness_pass: false`, see the `agent:` block
above), `MIN_LOOKUPS_NUDGE` is sent only when the model submits `answered` without having run any lookup,
and `COMPLETENESS_CHECK`, `SUBMIT_RECEIVED` and the completeness-turn `LOOKUPS_CLOSED` are not sent at all;
they are sent when those settings are turned on (as in the eval run `reports/evals/v2_complete_2026-10-18_1819`).
The loop's own defaults when the keys are absent are `min_lookups` 2 and `completeness_pass` on
(`src/pharmassist/agent/loop.py:130–132`).

The model-call site, for reference (system text, messages and tools go through the router unchanged):

Source: `src/pharmassist/agent/loop.py:142–148`

```python
    def complete(tool_choice="auto"):
        """One model call on the thread so far, recorded in model_calls (usage, cost, timing)."""
        elapsed = clock() - start
        t0 = clock()
        c = router.complete(system=system, messages=messages, tools=specs,
                            timeout_s=max(5.0, min(call_timeout, HARD_LIMIT_S - elapsed)), prefer=state["prefer"],
                            tool_choice=tool_choice)
```

### 1.5 Tool definitions the model reads

Used when: every model call (`tool_defs(structured)` at `src/pharmassist/agent/loop.py:127`). The model reads the `name`,
`description` and `input_schema` of each tool. With `structured` false the four `TOOLS` are sent; with
`structured` true (production) the first three `TOOLS`, both `LOOKUP_TOOLS`, and `SUBMIT_STRUCTURED` (a
copy of `submit_answer` whose citation items also take `row`) are sent, in that order. `submit_answer` is
the only tool marked `strict`.

Source: `src/pharmassist/agent/tools.py:34–41` (constants the schemas and descriptions use)

```python
PROGRAMS = ("VA", "Medicare Part D", "NY Medicaid")
RRF_K = 60  # the same fusion constant the hybrid search uses
MAX_MERGED = 20  # cap on the union of the two top-k lists (k is at most 15)
RESULT_CHARS = 4000  # of each tool result kept in the trace for LangSmith's tool runs
_POOL = ThreadPoolExecutor(max_workers=4)  # the original-question and agent searches run side by side
STATUSES = ("answered", "not_in_documents", "out_of_scope")
FORMULARY_UNAVAILABLE = ("The VA National Formulary spreadsheet isn't available in the searchable "
                         "documents yet; don't infer its contents.")
```

Source: `src/pharmassist/agent/tools.py:43–103` (`TOOLS`: search_documents, read_page, list_documents, submit_answer)

```python
TOOLS = [
    {
        "name": "search_documents",
        "description": "Hybrid keyword + semantic search over the document chunks. Returns the best "
                       "matching chunks with doc_id, page, program, authority, date and text.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to look for; include exact terms "
                          "such as drug names, codes or field numbers."},
                "program": {"type": "string", "enum": list(PROGRAMS),
                            "description": "Only return chunks from this program."},
                "k": {"type": "integer", "description": "Number of chunks, 1–15 (default 8)."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "read_page",
        "description": "Full text of one PDF page (1-based page index), to read a whole table row "
                       "or check the context around a search hit.",
        "input_schema": {
            "type": "object",
            "properties": {"doc_id": {"type": "string"}, "page": {"type": "integer"}},
            "required": ["doc_id", "page"],
        },
    },
    {
        "name": "list_documents",
        "description": "The document catalog: id, title, program, type, authority, date and page count.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "submit_answer",
        "description": "Submit the final answer. Call exactly once, as the last step.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": list(STATUSES)},
                "assumption": {"type": ["string", "null"],
                               "description": "The program or reading you assumed, or null if none."},
                "answer": {"type": "string", "description": "The answer in markdown."},
                "citations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"doc_id": {"type": "string"}, "page": {"type": "integer"}},
                        "required": ["doc_id", "page"],
                        "additionalProperties": False,
                    },
                },
                "conflicts_noted": {"type": "array", "items": {"type": "string"},
                                    "description": "One line per conflict or apparent conflict; "
                                                   "empty if none."},
            },
            "required": ["status", "assumption", "answer", "citations", "conflicts_noted"],
            "additionalProperties": False,
        },
    },
]
```

Source: `src/pharmassist/agent/tools.py:106–153` (`LOOKUP_TOOLS`: lookup_va_formulary, lookup_ny_medicaid_drug)

```python
LOOKUP_TOOLS = [
    {
        "name": "lookup_va_formulary",
        "description": (
            "Exact rows from the VA National Formulary spreadsheet (sheet Formulary): VA class, "
            "restriction (PA-F = facility-level prior authorization), generic name, dosage form, "
            "comments, U/E formulary, clinical guidance. Matches the generic name, a brand the row "
            "states as EQV-, and combination products containing the drug; never a fuzzy guess. "
            "The VA National Formulary is dosage form specific (row 7): if a specific dosage form "
            "is not listed, that product is non-formulary, although other dosage forms of the same "
            "drug may be formulary. Result: exact_match, multiple_matches (all candidates "
            "returned), dosage_form_not_listed, fuzzy_suggestion (not a match), no_matching_row "
            "(the name wasn't found; NOT evidence of non-formulary status), or a lookup_failure "
            "error. Cite a row as {doc_id, row}."),
        "input_schema": {
            "type": "object",
            "properties": {
                "drug": {"type": "string", "description": "Generic or brand name; a strength may follow."},
                "dosage_form": {"type": "string", "description": "Optional, e.g. 'film', "
                                "'sublingual tablet', 'patch'."},
            },
            "required": ["drug"],
        },
    },
    {
        "name": "lookup_ny_medicaid_drug",
        "description": (
            "Exact rows from the NYRx Preferred Drug List (pages 4–60): drug name as printed, the "
            "column it's listed in (preferred / non-preferred), flags (CC, ST, F/Q/D, DO, BLTG, "
            "MR), effective-date markers (1 = preferred as of 10/22/2026, 2 = non-preferred as of "
            "10/22/2026), and the class's Coverage Parameters text, with page provenance. Matches "
            "the name, name plus strength or form, the generic the PDL states as '(gen Brand)', or "
            "a drug class name (e.g. 'GLP-1'); never a fuzzy guess. Result: exact_match, "
            "multiple_matches (all candidates returned), class_match, fuzzy_suggestion (not a "
            "match), no_matching_row (NOT evidence that the drug isn't covered), or a "
            "lookup_failure error. Covers the Preferred Drug Program pages only; the PDL's other sections "
            "(MAT formulary, BLTG, DUR F/Q/D, dose optimization; pages 61–86) are in search_documents. "
            "Cite rows by {doc_id, page}."),
        "input_schema": {
            "type": "object",
            "properties": {
                "drug": {"type": "string", "description": "Drug or class name as a pharmacist would write it."},
                "drug_class": {"type": "string", "description": "Optional: narrow to a class, e.g. 'GLP-1'."},
            },
            "required": ["drug"],
        },
    },
]
```

Source: `src/pharmassist/agent/tools.py:155–177` (`SUBMIT_STRUCTURED`, and how the list is assembled)

```python
# with the lookups, a citation is a PDF page or a spreadsheet row
SUBMIT_STRUCTURED = json.loads(json.dumps(TOOLS[3]))
SUBMIT_STRUCTURED["input_schema"]["properties"]["citations"]["items"] = {
    "type": "object",
    "properties": {
        "doc_id": {"type": "string"},
        "page": {"type": ["integer", "null"], "description": "PDF page; null for a spreadsheet row."},
        "row": {"type": ["integer", "null"], "description": "Spreadsheet row (VA formulary); else null."},
    },
    "required": ["doc_id", "page", "row"],
    "additionalProperties": False,
}


def tool_dicts(structured: bool) -> list[dict]:
    """The tool definitions as plain dicts (the evaluated v1 shape, snapshot-tested)."""
    return TOOLS[:3] + LOOKUP_TOOLS + [SUBMIT_STRUCTURED] if structured else TOOLS


def tool_defs(structured: bool) -> list[ToolSpec]:
    """The tools sent to the model, as ToolSpecs for the provider layer."""
    return [ToolSpec(name=t["name"], description=t["description"], input_schema=t["input_schema"],
                     strict=bool(t.get("strict"))) for t in tool_dicts(structured)]
```

Provider wire format. OpenAI receives each tool as a function tool (`parameters` = the input schema,
`strict` honoured); Anthropic receives `name`/`description`/`input_schema` and `strict: True` only for
`submit_answer`:

Source: `src/pharmassist/llm/openai_provider.py:33–35`

```python
def tool_param(t: ToolSpec) -> dict:
    return {"type": "function", "name": t.name, "description": t.description,
            "parameters": t.input_schema, "strict": bool(t.strict)}
```

Source: `src/pharmassist/llm/anthropic_provider.py:31–35`

```python
def tool_param(t: ToolSpec) -> dict:
    out = {"name": t.name, "description": t.description, "input_schema": t.input_schema}
    if t.strict:
        out["strict"] = True
    return out
```

### 1.6 Tool results: the text templates the model gets back

Tool results are data (search hits, page text, lookup rows), but the following fixed strings and framing
are part of what the model reads.

**search_documents.** The result is `json.dumps(rows)` where each row has `doc_id`, `page`, `program`,
`authority`, `date`, `text` and, for section results, `pages` and `section`. No prose framing is added. (The
`text` variable built at line 437 is kept for the trace's evidence record, not returned to the model.)

Source: `src/pharmassist/agent/tools.py:421–442`

```python
    def search_documents(self, query: str, program: str | None = None, k: int | None = None):
        if program is not None and program not in PROGRAMS:
            raise ToolError(f"program must be one of {list(PROGRAMS)}, got {program!r}")
        k = max(1, min(int(k or self.search_k), 15))
        hits = self._search_with_original(query, program, k)
        rows, found, texts = [], [], {}
        for h in hits:
            # a section result spans pages; its text marks each one ("[p 34]"), and any of them
            # may be cited
            pages = h.get("pages") or [h["page"]]
            row = {"doc_id": h["doc_id"], "page": h["page"], "program": h["program"],
                   "authority": h["authority"], "date": h["date"], "text": h["text"]}
            if len(pages) > 1 or h.get("section"):
                row.update(pages=pages, section=h.get("section"))
            rows.append(row)
            # the hit's text (with its document's date) is evidence for each page it covers
            text = f"{h['doc_id']} ({h['program']}, {h['authority']}, {h['date']})\n{h['text']}"
            for p in pages:
                loc = locator(h["doc_id"], p)
                found.append(loc)
                texts[loc] = texts[loc] + "\n\n" + text if loc in texts and text not in texts[loc] else text
        return json.dumps(rows, ensure_ascii=False), found, texts
```

**read_page.** The page text is prefixed with a one-line header naming the document, page, program,
authority and date, truncated at `agent.read_page_chars` with `[page truncated]`, and, only when
`page_figures` is on (off by default), followed by the page's figure interpretations under a fixed heading.

Source: `src/pharmassist/agent/tools.py:517–538`

```python
    def read_page(self, doc_id: str, page: int):
        entry = self.catalog.get(doc_id)
        if entry is None:
            raise ToolError(f"unknown doc_id {doc_id!r}; call list_documents for valid ids")
        if not str(entry.get("file") or "").lower().endswith(".pdf"):
            raise ToolError("Use lookup_va_formulary for the VA formulary spreadsheet." if self.structured
                            else FORMULARY_UNAVAILABLE)
        pages = entry.get("pages")
        if pages and not 1 <= page <= pages:
            raise ToolError(f"{doc_id} has pages 1–{pages}, got {page}")
        pdf = self._pdf(doc_id)
        if not 1 <= page <= pdf.page_count:
            raise ToolError(f"{doc_id} has pages 1–{pdf.page_count}, got {page}")
        text = pdf[page - 1].get_text()
        if len(text) > self.read_page_chars:
            text = text[: self.read_page_chars] + "\n[page truncated]"
        if self.page_figures:  # the page's figures, as extracted (labelled machine-generated)
            figs = self._figures(doc_id, page)
            if figs:
                text += "\n\n[Figures on this page, interpreted from the page image]\n" + "\n\n".join(figs)
        header = f"{doc_id} page {page} ({entry.get('program')}, {entry.get('authority')}, {entry.get('date')})\n\n"
        return header + text, [locator(doc_id, page)]
```

When `page_figures` is on, each figure is rendered by `figures.render()` as a header line
`[Figure, <kind>] <title> (PDF page <n>). Machine-generated visual interpretation; status: <STATUS_TEXT>.`
followed by box/edge/series/row lines. The status texts and the renderer:

Source: `src/pharmassist/parsers/figures.py:43–47`

```python
STATUS_TEXT = {
    "machine_interpreted": "machine-interpreted from the page image by a vision model; not verified",
    "ocr_checked": "machine-interpreted from the page image by a vision model; structure and OCR cross-check passed",
    "reviewed": "machine-interpreted from the page image by a vision model; compared box by box against the page image (not clinician-verified)",
}
```

Source: `src/pharmassist/parsers/figures.py:306–345`

```python
def render(record: dict, status: str, page: int) -> tuple[str, list[str]]:
    """(header, lines): the header is repeated on every chunk cut from this figure."""
    kind = record.get("kind")
    title = (record.get("title") or "").strip() or "untitled in the image; see the section heading"
    head = (f"[Figure, {kind}] {title} (PDF page {page}). "
            f"Machine-generated visual interpretation; status: {STATUS_TEXT[status]}.")
    lines = []
    if kind == "flowchart":
        nodes = {n["id"]: n for n in record.get("nodes", [])}
        label = lambda i: " ".join(nodes[i]["text"].split()) if i in nodes else f"(unknown box {i})"
        for i, n in nodes.items():
            exits = [e for e in record.get("edges", []) if e["from"] == i]
            line = f"Box {i} ({n['shape']}): {label(i)}"
            if exits:
                line += " -> " + "; ".join(
                    (f"if {e['label'].strip()}: " if (e.get("label") or "").strip() else "then ")
                    + f"box {e['to']}" for e in exits)
            lines.append(line)
        for p in _paths(record):
            lines.append("Decision path: " + " -> ".join(
                f"[{lab}] {n}" if lab else n for n, lab in p))
    elif kind == "chart":
        c = record.get("chart") or {}
        lines.append(f"Chart type: {c.get('chart_type', '')}; x: {c.get('x_axis', '')}; y: {c.get('y_axis', '')}; "
                     f"units: {c.get('units', '')}")
        for s in c.get("series", []):
            pts = "; ".join(f"{p.get('label')}: {p.get('value')}" for p in s.get("points", []))
            lines.append(f"Series {s.get('name', '')}: {pts}")
    elif kind == "table_image":
        t = record.get("table") or {}
        hdr = " | ".join(t.get("header", []))
        lines += [" | ".join(r) for r in t.get("rows", [])]
        head += f"\nColumns: {hdr}"
    if record.get("description"):
        lines.append(record["description"].strip())
    for f in record.get("footnotes") or []:
        lines.append(f"Footnote: {f}")
    for u in record.get("unreadable") or []:
        lines.append(f"Unreadable or ambiguous (not interpreted): {u}")
    return head, lines
```

**lookup_va_formulary, lookup_ny_medicaid_drug, list_documents.** Each returns `json.dumps(...)` of the
lookup result or catalog rows, with no added framing. The lookup result dictionaries (`result`,
`rows`, `classes`, `rule`, `pa_levels`, ...) are produced by `src/pharmassist/tables/va_formulary.py` and
`src/pharmassist/tables/ny_pdl.py` from the spreadsheet and PDL rows; they are data, not prompt text.

Source: `src/pharmassist/agent/tools.py:540–572`

```python
    def lookup_va_formulary(self, drug: str, dosage_form: str | None = None):
        try:
            from pharmassist.tables import va_formulary
            f = _table(self.store, "va_formulary")
            r = va_formulary.lookup(drug, dosage_form, formulary=f)
        except Exception as e:  # any failure reading the source is a lookup failure, not a crash
            raise ToolError(f"lookup_failure: the VA formulary couldn't be read ({type(e).__name__}: "
                            f"{e}). Say the structured formulary source was unavailable; don't "
                            "infer formulary status.") from e
        found = [va_formulary.locator(x["row"]) for x in r.get("rows", [])]
        found += [va_formulary.locator(n) for n in (f.rule_row, f.pa_row, f.header_row)]
        return json.dumps(r, ensure_ascii=False), found

    def lookup_ny_medicaid_drug(self, drug: str, drug_class: str | None = None):
        try:
            from pharmassist.tables import ny_pdl
            r = ny_pdl.lookup(drug, drug_class, rows=_table(self.store, "ny_pdl"))
        except Exception as e:
            raise ToolError(f"lookup_failure: the NYRx PDL rows couldn't be read ({type(e).__name__}: "
                            f"{e}). Say the structured PDL source was unavailable, then use "
                            "search_documents on the PDL text instead.") from e
        found = {locator(ny_pdl.DOC_ID, ny_pdl.RULES_PAGE)}
        for c in r.get("classes", []):
            found.update(locator(ny_pdl.DOC_ID, p) for p in c["coverage_pages"])
            found.update(locator(ny_pdl.DOC_ID, x["cite"]["page"]) for x in c["rows"])
        return json.dumps(r, ensure_ascii=False), sorted(found)

    def list_documents(self):
        rows = [{"id": doc_id, "title": e.get("title"), "program": e.get("program"), "doc_type": e.get("doc_type"),
                 "authority": e.get("authority"), "date": str(e.get("date")), "pages": e.get("pages"),
                 "searchable": str(e.get("file") or "").lower().endswith(".pdf")}
                for doc_id, e in self.catalog.items()]
        return json.dumps(rows, ensure_ascii=False), []
```

**Error strings the model sees as error tool results.** Raised as `ToolError` (or `TypeError` for bad
arguments) inside `ToolBox.run()` and returned with `is_error=True`:

Source: `src/pharmassist/agent/tools.py:364–396` (the dispatcher: `unknown tool ...`, `bad arguments for ...`)

```python
    def run(self, name: str, args: dict) -> tuple[str, bool]:
        """Run one tool call. Returns (result text, is_error) and records it in self.calls."""
        t0 = self.clock()
        found, is_error = [], False
        handlers = {"search_documents": self.search_documents, "read_page": self.read_page,
                    "list_documents": self.list_documents}
        if self.structured:
            handlers.update(lookup_va_formulary=self.lookup_va_formulary,
                            lookup_ny_medicaid_drug=self.lookup_ny_medicaid_drug)
        try:
            handler = handlers.get(name)
            if handler is None:
                raise ToolError(f"unknown tool {name!r}")
            out = handler(**args)
            result, found = out[0], list(dict.fromkeys(out[1]))
            self._add_evidence(out[2] if len(out) > 2 else {l: result for l in found})
        except ToolError as e:
            result, is_error = str(e), True
            error_kind = ("lookup_failure" if result.startswith("lookup_failure") else
                          "unknown_tool" if result.startswith("unknown tool") else "tool_error")
        except TypeError as e:  # unexpected or missing arguments
            result, is_error, error_kind = f"bad arguments for {name}: {e}", True, "bad_arguments"
        self.seen.update(found)
        call = {"name": name, "input": args, "duration_s": round(self.clock() - t0, 3),
                "is_error": is_error, "pages": sorted(found), "result": result[:RESULT_CHARS]}
        if is_error:
            call["error_kind"] = error_kind  # a fixed category, for tracing (never the message)
        elif name.startswith("lookup_"):
            call["lookup"] = _lookup_summary(result)
        if name == "search_documents" and self._search_meta is not None:
            call["search"], self._search_meta = self._search_meta, None
        self.calls.append(call)
        return result, is_error
```

The individual messages: `src/pharmassist/agent/tools.py:40–41` (`FORMULARY_UNAVAILABLE`, shown above in 1.5), `src/pharmassist/agent/tools.py:423`
(bad `program`), `src/pharmassist/agent/tools.py:501` (PDF couldn't be opened), `src/pharmassist/agent/tools.py:520–523` and `src/pharmassist/agent/tools.py:526–529` (unknown
doc_id, non-PDF document, page out of range; shown above in the read_page block), `src/pharmassist/agent/tools.py:546–548` and
`src/pharmassist/agent/tools.py:558–560` (`lookup_failure: ...`; shown above in the lookup block).

**How an error result is marked for each provider.** OpenAI gets the text prefixed with `[tool error] `;
Anthropic gets a `tool_result` block with `is_error: true` and the text unchanged.

Source: `src/pharmassist/llm/openai_provider.py:38–59`

```python
def to_input(messages: Sequence[Message]) -> list[dict]:
    """Canonical messages -> Responses `input` items."""
    items: list[dict] = []
    for m in messages:
        if m.role == "user":
            items.append({"role": "user", "content": m.text})
        elif m.role == "assistant":
            own = (m.provider_state or {}).get("openai")
            if own and own.get("items"):
                items.extend(own["items"])      # reasoning + message + function_call items, as returned
                continue
            if m.text:
                items.append({"role": "assistant", "content": m.text})
            for c in m.tool_calls:
                items.append({"type": "function_call", "call_id": safe_id(c.id), "name": c.name,
                              "arguments": json.dumps(c.arguments, ensure_ascii=False)})
        else:  # tool results
            for r in m.parts:
                if isinstance(r, ToolResult):
                    out = f"[tool error] {r.content}" if r.is_error else r.content
                    items.append({"type": "function_call_output", "call_id": safe_id(r.call_id), "output": out})
    return items
```

Source: `src/pharmassist/llm/anthropic_provider.py:38–46`

```python
def _user_blocks(m: Message) -> list[dict]:
    blocks = []
    for p in m.parts:
        if isinstance(p, TextPart):
            blocks.append({"type": "text", "text": p.text})
        elif isinstance(p, ToolResult):
            blocks.append({"type": "tool_result", "tool_use_id": safe_id(p.call_id), "content": p.content,
                           "is_error": bool(p.is_error)})
    return blocks
```

### 1.7 `agent/verify.py`, `agent/offline.py`, `agent/telemetry.py`

None of these sends anything to a model while answering. `verify.py`'s claim checks and `assemble()` are
deterministic; its one model prompt, `AUDIT_SYSTEM`, is the optional offline claim audit and is listed under
the judges (2.3). `offline.py` only prepares a saved trace for those checks. `telemetry.py` sends the
trace to LangSmith (not a model).

### 1.8 Provider calls: nothing is prepended

The system text, messages and tools go to each API as they are. For the record, the two call sites:

Source: `src/pharmassist/llm/openai_provider.py:141–151` (OpenAI Responses API: `instructions=system`, reasoning effort, stateless)

```python
    def complete(self, *, model: str, system: str, messages: Sequence[Message], tools: Sequence[ToolSpec],
                 max_tokens: int, effort: Effort, timeout_s: float,
                 tool_choice: Literal["auto", "required"] | str = "auto") -> Completion:
        choice = tool_choice if tool_choice in ("auto", "required") else {"type": "function", "name": tool_choice}
        t0 = time.perf_counter()
        try:
            resp = self.client().responses.create(
                model=model, instructions=system, input=to_input(messages), tools=[tool_param(t) for t in tools],
                tool_choice=choice, parallel_tool_calls=True, max_output_tokens=max_tokens,
                reasoning={"effort": effort}, store=False, include=["reasoning.encrypted_content"],
                timeout=timeout_s)
```

Source: `src/pharmassist/llm/anthropic_provider.py:132–143` (Anthropic Messages API: `system=system`, `output_config.effort`, prompt caching, optional server-side refusal fallback beta)

```python
    def complete(self, *, model: str, system: str, messages: Sequence[Message], tools: Sequence[ToolSpec],
                 max_tokens: int, effort: Effort, timeout_s: float,
                 tool_choice: Literal["auto", "required"] | str = "auto") -> Completion:
        params = {"model": model, "max_tokens": max_tokens, "system": system, "tools": [tool_param(t) for t in tools],
                  "output_config": {"effort": effort}, "cache_control": {"type": "ephemeral"},
                  "messages": to_messages(messages), "timeout": max(1.0, float(timeout_s))}
        if tool_choice == "required":
            params["tool_choice"] = {"type": "any"}
        elif tool_choice != "auto":
            params["tool_choice"] = {"type": "tool", "name": tool_choice}
        if self.refusal_fallback:
            params.update(betas=[FALLBACK_BETA], fallbacks="default")
```

---

## 2. The evaluation judges

Run by `scripts/run_eval.py` (never on the live path). Both judges call the Anthropic Messages API
directly (`judge._call`) with structured outputs (`json_schema`), so each reply is one JSON object. Each is run
`eval.judge_passes` times per question: accuracy takes the majority grade, groundedness the median pass.
`scripts/run_eval.py` holds no prompt text of its own.

### Settings (config.yaml `eval:`)

Source: `config.yaml:177–197`

```yaml
eval:
  golden: evals/golden.jsonl
  judge_model: claude-opus-5-5
  judge_effort: medium
  judge_max_tokens: 8000
  judge_passes: 3           # accuracy = majority grade; groundedness = the median pass
  page_chars: 8000          # per cited page given to the groundedness judge (same cut as read_page)
  answer_words: [60, 120]   # target answer length from REQUIREMENTS.md
  prices_per_mtok: {input: 4.00, output: 20.00, cache_read: 0.20, cache_write: 5.00}
  # optional offline deterministic checks (agent/offline.py; free): never on the live path
  offline_checks:
    enabled: false
  # optional offline audit: one batched model call per answer, after it was given; never on the live path
  claim_audit:
    enabled: false
    model: claude-sonnet-5-5
    effort: low
    max_tokens: 4000
    timeout_s: 60
    evidence_chars: 6000
    prices_per_mtok: {input: 2.00, output: 10.00, cache_read: 0.20, cache_write: 2.50}
```

The shared call (model `eval.judge_model`, `eval.judge_max_tokens`, effort `eval.judge_effort`, 180 s timeout):

Source: `src/pharmassist/eval/judge.py:15`, `src/pharmassist/eval/judge.py:104–113`

```python
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
```

### 2.1 Accuracy judge: `ACCURACY_SYSTEM`, `ACCURACY_SCHEMA`, and its user message

Used when: grading one answered golden question against the reference answer and its `must_include`
terms. There is no separate must-include prompt: the terms are listed in this user message and the judge
marks each present or not (`scoring.py` also runs a literal substring check with no model).

Source: `src/pharmassist/eval/judge.py:17–37` (system text)

```python
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
```

Source: `src/pharmassist/eval/judge.py:77–89` (output schema)

```python
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
```

Source: `src/pharmassist/eval/judge.py:116–127` (the user message: today's date, the question, the reference answer and notes,
answerability, the must_include terms, then the assistant's reply as `_answer_block` renders it)

```python
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
```

### 2.2 Groundedness judge: `GROUNDEDNESS_SYSTEM`, `GROUNDEDNESS_SCHEMA`, and its user message

Used when: checking an answer's claims against the text of the sources it cites, without the reference
answer. Only cited sources that exist are included (`report.py` filters unknown docs, pages and rows). The
report's "safe" measure (no unsupported content shown) is derived from this judge's verdicts; there is no
separate safety-audit prompt.

Source: `src/pharmassist/eval/judge.py:39–75` (system text)

```python
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
```

Source: `src/pharmassist/eval/judge.py:91–101` (output schema)

```python
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
```

Source: `src/pharmassist/eval/judge.py:130–157` (the user message: today's date, then each cited source as
`=== <locator> ===`, its catalog line and its text (a PDF page cut at `eval.page_chars` with `[page truncated]`,
or a formulary row as `column: value` lines), then the assistant's reply via `_answer_block`)

```python
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
```

Source: `src/pharmassist/tables/va_formulary.py:144–152` (how a cited VA formulary row is rendered for the judge)

```python
def row_text(row: int) -> str:
    """One row as 'column: value' lines, for the groundedness judge."""
    f = load()
    if row in f.notes:
        return f"Note row {row}: {f.notes[row]}"
    if row == f.header_row:
        return "Header row: " + " | ".join(HEADER)
    r = f.rows.loc[row]
    return "\n".join(f"{h}: {r[k].strip()}" for h, k in zip(HEADER, FIELDS))
```

### 2.3 Offline claim audit: `AUDIT_SYSTEM`, `AUDIT_SCHEMA`, and its user message

Used when: `scripts/run_eval.py --audit` (or `eval.claim_audit.enabled: true`), one batched call per
answer after it was given; never while answering. `offline.answer_claims()` splits the answer into
sentences (table rows one each) and every sentence cites all of the answer's citations; `audit_claims()`
lists them as `Claim <i> [<type>]: <text>` / `Cites: ...` followed by the cited evidence under `## <locator>`
headings. Settings: `eval.claim_audit` in the block above (model `claude-sonnet-5-5`, effort `low`,
`max_tokens` 4000, `evidence_chars` 6000, 60 s timeout).

Source: `src/pharmassist/agent/verify.py:923–929` (system text)

```python
AUDIT_SYSTEM = """\
You audit claims written for pharmacy staff against the evidence each one cites. Use only the \
evidence text given; never your own knowledge. For each claim decide supported (its cited evidence \
states it, with every condition and qualifier), partially_supported (the core is stated but a \
value, scope or condition isn't), or unsupported; quote in unsupported_words the claim's words the \
evidence doesn't support (empty if supported); and say whether it is self_contained (understandable \
alone). One sentence of reason each."""
```

Source: `src/pharmassist/agent/verify.py:931–941` (output schema)

```python
AUDIT_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["verdicts"],
    "properties": {"verdicts": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["claim", "verdict", "unsupported_words", "self_contained", "reason"],
        "properties": {"claim": {"type": "integer"},
                       "verdict": {"type": "string", "enum": ["supported", "partially_supported", "unsupported"]},
                       "unsupported_words": {"type": "string"},
                       "self_contained": {"type": "boolean"},
                       "reason": {"type": "string"}}}}},
}
```

Source: `src/pharmassist/agent/verify.py:944–969` (the user message assembly and the call)

```python
def audit_claims(client, acfg: dict, claims: list[dict], evidence: dict[str, str], question: str = "") -> dict:
    """One batched model call judging every claim against its cited pages, for eval reports only.
    Never called while answering. Returns {"verdicts", "model", "usage"}."""
    chars = acfg.get("evidence_chars", 6000)
    blocks, locs_used = [], []
    for i, c in enumerate(claims, 1):
        locs = locators_of(c)
        blocks.append(f"Claim {i} [{c.get('type')}]: {c.get('text')}\nCites: {', '.join(locs) or 'nothing'}")
        locs_used += [l for l in locs if l not in locs_used]
    ev = "\n\n".join(f"## {l}\n{evidence.get(l, '(not returned by any tool)')[:chars]}" for l in locs_used)
    user = (f"# Staff question\n{question}\n\n" if question else "") + "# Claims\n" + "\n\n".join(blocks) + \
        "\n\n# Evidence\n" + ev
    resp = client.beta.messages.create(
        model=acfg["model"], max_tokens=acfg.get("max_tokens", 2000), system=AUDIT_SYSTEM,
        messages=[{"role": "user", "content": user}],
        output_config={"format": {"type": "json_schema", "schema": AUDIT_SCHEMA},
                       **({"effort": acfg["effort"]} if acfg.get("effort") else {})},
        timeout=acfg.get("timeout_s", 60))
    if resp.stop_reason != "end_turn":
        raise RuntimeError(f"audit stopped with {resp.stop_reason}")
    u = resp.usage
    usage = {"input": u.input_tokens or 0, "output": u.output_tokens or 0,
             "cache_read": getattr(u, "cache_read_input_tokens", None) or 0,
             "cache_write": getattr(u, "cache_creation_input_tokens", None) or 0}
    return {"verdicts": json.loads("".join(b.text for b in resp.content if b.type == "text"))["verdicts"],
            "model": resp.model, "usage": usage}
```

Source: `src/pharmassist/agent/offline.py:25–41` and `src/pharmassist/agent/offline.py:60–69` (how the answer becomes the claims list)

```python
def answer_claims(answer: str, citations: list[dict]) -> list[dict]:
    """The answer's sentences as claims (table rows as one claim each), every one citing all of the
    answer's citations. The first is marked as the direct answer."""
    cites = [{k: c.get(k) for k in ("doc_id", "page", "row") if k in c} for c in citations]
    lines = (answer or "").split("\n")
    texts = []
    for i, line in enumerate(lines):
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if not line.strip() or TABLE_RULE.match(line) or TABLE_RULE.match(nxt):  # rule or table header
            continue
        if line.strip().startswith("|"):
            texts.append(" | ".join(c.strip() for c in line.strip().strip("|").split("|")))
            continue
        line = BULLET.sub("", line).replace("**", "").strip()
        texts += [s.strip() for s in re.split(r"(?<=[.!?])\s+", line) if s.strip()]
    return [{"text": t, "type": "other", "direct_answer": i == 0, "step": None, "citations": cites}
            for i, t in enumerate(texts)]
```

```python
def audit(client, acfg: dict, trace: dict) -> dict:
    """The Sonnet claim audit on the answer's sentences: one batched model call."""
    claims = answer_claims(trace.get("answer", ""), trace.get("citations") or [])
    if not claims:
        return {"verdicts": [], "model": None, "usage": {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}}
    out = V.audit_claims(client, acfg, claims, trace.get("cited_evidence") or {}, trace.get("question", ""))
    for v in out["verdicts"]:
        if 1 <= v["claim"] <= len(claims):
            v["text"] = claims[v["claim"] - 1]["text"]
    return out
```

### 2.4 DeepEval second scorer: `ACCURACY_CRITERIA`

Used when: `scripts/deepeval_score.py` re-scores finished eval runs with the DeepEval library. Only one prompt text is
authored in this repository, the `GEval` accuracy criteria; the other three metrics (`FaithfulnessMetric`,
`HallucinationMetric`, `AnswerRelevancyMetric`) use DeepEval's own prompt templates, which live in the
installed library, not in this repo. Judge model: `--judge`, default `claude-sonnet-5-5` (`scripts/deepeval_score.py:468`).

Source: `scripts/deepeval_score.py:81–87`

```python
ACCURACY_CRITERIA = (
    "Compare the actual output with the expected output for a pharmacy staff question; score 1 when "
    "every fact the expected output states is present and correct in the actual output, 0.5 when the "
    "main conclusion is right but a stated condition, limit, date, program or process step is missing, "
    "0 when the conclusion is wrong or contradicts the expected output; extra correct detail is not "
    "penalised"
)
```

Source: `scripts/deepeval_score.py:204–213` (how the criteria are passed; `evaluation_params` tells GEval which test-case
fields to show the judge)

```python
def build_metrics(judge):
    return {
        "groundedness": FaithfulnessMetric(threshold=0.5, model=judge, include_reason=True, async_mode=True),
        "truthfulness": HallucinationMetric(threshold=0.5, model=judge, include_reason=True, async_mode=True),
        "relevancy": AnswerRelevancyMetric(threshold=0.5, model=judge, include_reason=True, async_mode=True),
        "accuracy": GEval(
            name="accuracy", criteria=ACCURACY_CRITERIA, model=judge, threshold=0.5, async_mode=True,
            evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT,
                               LLMTestCaseParams.EXPECTED_OUTPUT]),
    }
```

---

## 3. Ingestion-time prompts

### Settings (config.yaml `figures:`)

Source: `config.yaml:268–272`

```yaml
figures:
  model: claude-opus-5-5          # the strongest vision model; ~20 figures, so cost stays small
  max_tokens: 16000               # thinking is always on for this model and counts toward it
  prices_per_mtok: {input: 4.00, output: 20.00}
  max_spend_usd: 8.00             # the script stops before a call that would pass this
```

### 3.1 Figure interpretation (vision): `PROMPT`, `TOOL` schema, and the OCR/caption pieces

Used when: `scripts/extract_figures.py` runs `figures.extract()` once per non-decorative image found by the
Docling parse (flowcharts, charts, table images, unclassified raster images). One Messages API call with
the PNG crop and the formatted `PROMPT`; the reply is forced to the `TOOL["input_schema"]` (made strict by
`_strict()`) through `output_config.format: json_schema`. Effort is `medium` for flowcharts and unclassified
images, `low` otherwise. Results are cached by crop hash + model + `PROMPT_VERSION`. Placeholders: `{page}`,
`{title}`, `{doc_type}` from the catalog entry; `{caption}` is either `Its caption is: "<caption>".\n` or
empty; `{ocr}` is either `OCR text found in the image (unordered, may be incomplete or wrong):\n` + the OCR
strings joined by ` | ` (cut at 3000 chars) or empty.

Source: `src/pharmassist/parsers/figures.py:39` (prompt version, part of the cache key)

```python
PROMPT_VERSION = 2
```

Source: `src/pharmassist/parsers/figures.py:89–100` (the prompt text)

```python
PROMPT = """This image is a figure cropped from page {page} of "{title}" (a {doc_type}).
{caption}Return the record as JSON matching the schema.

Rules:
- Transcribe only what is visible. Do not add clinical knowledge, and do not complete cut-off text.
- Flowchart: one node per box, using the printed box numbers as ids. Copy box text verbatim. Record every
  arrow in the direction its arrowhead points, with its printed branch label (Yes/No/etc.). An arrow
  that joins another arrow points at the box that line ends in. If you cannot tell where an arrow goes,
  or which label belongs to it, put that in `unreadable` instead of guessing.
- Chart: every bar/point value as printed (keep signs and units); say if values are read off the axis.
- Logos, icons, photos with no information, and ornaments are "decorative".
{ocr}"""
```

Source: `src/pharmassist/parsers/figures.py:49–87` (the record schema the model fills; its `description` strings are read by the model.
The tool's top-level `name`/`description` are not sent: only `TOOL["input_schema"]` is passed, as the
`json_schema` output format)

```python
TOOL = {
    "name": "record_figure",
    "description": "Record what the figure contains, faithfully and only what is visible.",
    "input_schema": {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["flowchart", "chart", "table_image", "diagram", "photo",
                                                 "text_image", "decorative"]},
            "title": {"type": "string", "description": "The figure's printed title, or a short neutral one"},
            "decorative_reason": {"type": "string"},
            "nodes": {"type": "array", "description": "flowchart boxes, in their printed number order",
                      "items": {"type": "object", "properties": {
                          "id": {"type": "string", "description": "the printed box number if any, else n1, n2..."},
                          "shape": {"type": "string", "enum": ["start", "decision", "action", "end", "note"]},
                          "text": {"type": "string", "description": "the box text verbatim, bullets kept"}},
                          "required": ["id", "shape", "text"]}},
            "edges": {"type": "array", "description": "every arrow, in the direction the arrowhead points",
                      "items": {"type": "object", "properties": {
                          "from": {"type": "string"}, "to": {"type": "string"},
                          "label": {"type": "string", "description": "branch label exactly as printed (Yes/No/...), empty if none"}},
                          "required": ["from", "to"]}},
            "chart": {"type": "object", "properties": {
                "chart_type": {"type": "string"}, "x_axis": {"type": "string"}, "y_axis": {"type": "string"},
                "units": {"type": "string"},
                "series": {"type": "array", "items": {"type": "object", "properties": {
                    "name": {"type": "string"},
                    "points": {"type": "array", "items": {"type": "object", "properties": {
                        "label": {"type": "string"}, "value": {"type": "string"}}}}}}}}},
            "table": {"type": "object", "properties": {
                "header": {"type": "array", "items": {"type": "string"}},
                "rows": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}}}},
            "description": {"type": "string", "description": "diagram/photo/text_image: what it shows, and any text verbatim"},
            "footnotes": {"type": "array", "items": {"type": "string"}},
            "unreadable": {"type": "array", "items": {"type": "string"},
                           "description": "text, arrows or values you cannot read or are unsure of; never guess them"},
        },
        "required": ["kind", "title", "unreadable"],
    },
}
```

Source: `src/pharmassist/parsers/figures.py:114–123` (the schema is sent with `additionalProperties: false` on every object)

```python
def _strict(schema):
    """The schema with additionalProperties: false on every object (structured outputs require it)."""
    if isinstance(schema, dict):
        out = {k: _strict(v) for k, v in schema.items()}
        if out.get("type") == "object":
            out["additionalProperties"] = False
        return out
    if isinstance(schema, list):
        return [_strict(v) for v in schema]
    return schema
```

Source: `src/pharmassist/parsers/figures.py:182–215` (how the caption and OCR pieces are built and the call is made)

```python
def extract(fig: dict, entry: dict, log=print) -> dict:
    """The vision record for one figure (cached). Returns {"record", "usage", "model", "cached"}."""
    cfg = load_config()["figures"]
    crop = PROJECT_ROOT / fig["crop"]
    cp = _cache_path(crop, cfg["model"])
    if cp.exists():
        return {**json.loads(cp.read_text()), "cached": True}
    ocr = fig.get("ocr_text") or []
    ocr_hint = ("OCR text found in the image (unordered, may be incomplete or wrong):\n" + " | ".join(ocr)[:3000]
                if ocr else "")
    caption = f'Its caption is: "{fig["caption"]}".\n' if fig.get("caption") else ""
    top = fig["classes"][0][0] if fig.get("classes") else None
    effort = "medium" if top in (None, "flow_chart") else "low"  # arrows need care; photos and charts less
    with _client().messages.stream(
        model=cfg["model"], max_tokens=cfg["max_tokens"],
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": _strict(TOOL["input_schema"])}},
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                         "data": base64.b64encode(crop.read_bytes()).decode()}},
            {"type": "text", "text": PROMPT.format(page=fig["page"], title=entry["title"], doc_type=entry["doc_type"],
                                                   caption=caption, ocr=ocr_hint)},
        ]}],
    ) as stream:
        resp = stream.get_final_message()
    if resp.stop_reason not in ("end_turn", "stop_sequence"):
        raise RuntimeError(f"{fig['figure_id']}: vision call ended with {resp.stop_reason}")
    record = json.loads(next(b.text for b in resp.content if b.type == "text"))
    out = {"record": record, "model": resp.model, "effort": effort,
           "usage": {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens}}
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps(out, indent=1))
    log(f"  vision: {fig['figure_id']} -> {record.get('kind')} "
        f"({resp.usage.input_tokens} in / {resp.usage.output_tokens} out)")
    return {**out, "cached": False}
```

### 3.2 Decorative classification and OCR cross-check: no prompts

The decorative/vision decision is deterministic (`decide()`, `src/pharmassist/parsers/figures.py:165–174`: Docling class, image
fraction, crop present); the model can additionally return `kind: "decorative"` with a `decorative_reason`
through the schema above. The structure and OCR cross-check (`check()`, `src/pharmassist/parsers/figures.py:229–261`) compares the
record's node texts with Docling's OCR of the same crop in code; no model is called. Chunk embedding
(OpenAI `text-embedding-3-large`) sends the chunk text only; there is no prompt.

---

## 5. The semantic cache: no prompt

`src/pharmassist/cache/` (base, memory and Valkey backends) stores finished answers keyed by the embedding
of the normalised question and returns a stored answer, with its citations, when the cosine similarity is
at least `cache.threshold`. The only model call involved is `Router.embed()` (`src/pharmassist/llm/router.py:93`), an OpenAI
`text-embedding-3-large` embedding of the question text. No prompt text exists for the cache.

Source: `config.yaml:318–325`

```yaml
cache:
  enabled: true
  backend: valkey                       # valkey | memory | null
  url_env: REDIS_URL                    # redis://host:6379/0 (ElastiCache Valkey; local docker-compose)
  threshold: 0.90                       # cosine similarity for a hit
  max_entries: 20000
  ttl_days: 30
  index_name: pa_answers               # the Valkey vector index
```

---

## 6. Index

| Prompt / text | File | Used by |
|---|---|---|
| `SYSTEM` (agent system prompt, baseline) | `src/pharmassist/agent/prompt.py:7–64` | agent |
| `FORMULARY_UNAVAILABLE_TEXT` (replaced substring) | `src/pharmassist/agent/prompt.py:66–69` | agent |
| `STRUCTURED_LOOKUPS` (replacement; production variant) | `src/pharmassist/agent/prompt.py:71–89` | agent |
| `system_prompt()` (the join) | `src/pharmassist/agent/prompt.py:92–98` | agent |
| First user message (`Today's date: ... Question: ...`) | `src/pharmassist/agent/loop.py:134` | agent |
| `BUDGET_SPENT` | `src/pharmassist/agent/loop.py:48–49` | agent |
| `SUBMIT_NUDGE` | `src/pharmassist/agent/loop.py:50–51` | agent |
| `MIN_LOOKUPS_NUDGE` | `src/pharmassist/agent/loop.py:52–54` | agent |
| `COMPLETENESS_CHECK` | `src/pharmassist/agent/loop.py:56–63` | agent |
| `SUBMIT_RECEIVED` | `src/pharmassist/agent/loop.py:64` | agent |
| `LOOKUPS_CLOSED` | `src/pharmassist/agent/loop.py:65` | agent |
| `TOOLS` (search_documents, read_page, list_documents, submit_answer) | `src/pharmassist/agent/tools.py:43–103` | agent |
| `LOOKUP_TOOLS` (lookup_va_formulary, lookup_ny_medicaid_drug) | `src/pharmassist/agent/tools.py:106–153` | agent |
| `SUBMIT_STRUCTURED` (submit_answer with row citations) | `src/pharmassist/agent/tools.py:156–166` | agent |
| `FORMULARY_UNAVAILABLE` (read_page error, unstructured mode) | `src/pharmassist/agent/tools.py:40–41` | agent |
| search_documents result rows | `src/pharmassist/agent/tools.py:421–442` | agent |
| read_page header, `[page truncated]`, figures heading | `src/pharmassist/agent/tools.py:517–538` | agent |
| Figure render header and `STATUS_TEXT` (read_page, page_figures on) | `src/pharmassist/parsers/figures.py:43–47, 306–345` | agent (off by default) |
| Lookup and list_documents results, `lookup_failure` messages | `src/pharmassist/agent/tools.py:540–572` | agent |
| Tool dispatcher errors (`unknown tool`, `bad arguments for`) | `src/pharmassist/agent/tools.py:364–396` | agent |
| `[tool error] ` prefix (OpenAI) / `is_error` block (Anthropic) | `src/pharmassist/llm/openai_provider.py:54–58`; `src/pharmassist/llm/anthropic_provider.py:38–46` | agent |
| `ACCURACY_SYSTEM` + `ACCURACY_SCHEMA` + user message | `src/pharmassist/eval/judge.py:17–37, 77–89, 116–127` | judge |
| `GROUNDEDNESS_SYSTEM` + `GROUNDEDNESS_SCHEMA` + user message | `src/pharmassist/eval/judge.py:39–75, 91–101, 130–157` | judge |
| `row_text()` (formulary row as the judge sees it) | `src/pharmassist/tables/va_formulary.py:144–152` | judge |
| `AUDIT_SYSTEM` + `AUDIT_SCHEMA` + user message (offline claim audit) | `src/pharmassist/agent/verify.py:923–969` | judge (offline, opt-in) |
| `ACCURACY_CRITERIA` (DeepEval GEval) | `scripts/deepeval_score.py:81–87` | judge (second scorer) |
| Figure vision `PROMPT` + `TOOL` schema + caption/OCR pieces | `src/pharmassist/parsers/figures.py:89–100, 49–87, 182–215` | ingestion |
| Semantic cache | `src/pharmassist/cache/`, `src/pharmassist/llm/router.py:93` | none (embeddings only) |
