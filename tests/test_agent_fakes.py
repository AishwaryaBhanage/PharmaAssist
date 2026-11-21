"""Fakes shared by the agent and LLM tests: a scripted Provider, an in-memory Store that implements
only what the tools read, a search stub and a tiny PDF. No network, no API key, no index.

The tests at the bottom check the fakes themselves: that a Provider receives a canonical
conversation the real APIs would accept (alternating turns, every tool call answered)."""

import copy
import itertools
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from pharmassist.agent import tools
from pharmassist.llm import pricing
from pharmassist.llm.base import Completion, Message, ProviderError, TextPart, ToolCall, ToolResult, Usage
from pharmassist.llm.router import Role, Router

PRICES = {"input": 2.0, "output": 10.0, "cache_read": 0.2, "cache_write": 2.5}
USAGE = Usage(input=1000, output=100, cache_read=500, cache_write=0)   # 0.0031 USD at PRICES
_ids = itertools.count()
QUESTION = "Ozempic pen: preferred or PA?"
PDL_PAGES = 86

CFG = {
    # the min-lookups nudge and the completeness pass are off here (config.yaml turns them on), so scripts stay
    # short; COMPLETE_CFG below turns them on for their own tests
    "agent": {"search_k": 8, "max_tool_calls": 6, "deadline_s": 25, "read_page_chars": 8000,
              "structured_lookups": False, "page_figures": False, "trace_evidence_chars": 6000,
              "min_lookups": 0, "completeness_pass": False, "completeness_min_remaining_s": 8},
    "llm": {"primary": {"provider": "openai", "model": "gpt-5.5", "effort": "medium", "max_tokens": 4096,
                        "prices_per_mtok": PRICES},
            "fallback": {"provider": "anthropic", "model": "claude-sonnet-5-5", "effort": "medium",
                         "max_tokens": 4096, "prices_per_mtok": PRICES},
            "retry": {"attempts": 2, "backoff_s": 0.0}, "call_timeout_s": 25,
            "embedding": {"model": "text-embedding-3-large", "dimension": 3072}},
    "search": {"mode": "hybrid", "rrf_k": 60, "fusion_depth": 100, "return_parents": True, "rerank": None},
    "tracing_v2": {"content": "full"},
}
STRUCTURED_CFG = {**CFG, "agent": {**CFG["agent"], "structured_lookups": True}}
COMPLETE_CFG = {**CFG, "agent": {**CFG["agent"], "min_lookups": 2, "completeness_pass": True}}


# ---- canonical message builders ----

def tool(name, **args) -> ToolCall:
    return ToolCall(id=f"tu_{next(_ids)}", name=name, arguments=args)


def text(t) -> TextPart:
    return TextPart(t)


def submit(citations=(), status="answered", answer="Ozempic pen is preferred.", assumption="Assuming NY Medicaid",
           conflicts=()):
    return tool("submit_answer", status=status, assumption=assumption, answer=answer,
                citations=[{"doc_id": d, "page": p} for d, p in citations], conflicts_noted=list(conflicts))


def submit_rows(citations, answer="VA: PA-F."):
    """submit_answer in the structured shape: each citation {doc_id, page, row}."""
    return tool("submit_answer", status="answered", assumption=None, answer=answer, citations=list(citations),
                conflicts_noted=[])


def reply(*parts, stop=None, model=None, usage=USAGE):
    """A scripted assistant turn. `stop` defaults to tool_use when a part is a ToolCall, else end_turn."""
    parts = list(parts)
    if stop is None:
        stop = "tool_use" if any(isinstance(p, ToolCall) for p in parts) else "end_turn"
    return {"parts": parts, "stop": stop, "model": model, "usage": usage}


REFUSAL = {"parts": [], "stop": "refusal", "model": None, "usage": USAGE}


def error(status=None, retryable=False, malformed=False, provider="fake"):
    return ProviderError(provider, f"scripted failure {status or ''}".strip(), status=status, retryable=retryable,
                         malformed=malformed)


# ---- the API's conversation rules, checked on every fake call ----

class InvalidRequest(Exception):
    """What the fake raises where a real API would return a 400."""


def check_messages(messages):
    if not messages or messages[0].role != "user":
        raise InvalidRequest("the first message must be a user message")
    pending: set[str] = set()
    last_role = None
    for i, m in enumerate(messages):
        if m.role == "assistant":
            if last_role == "assistant":
                raise InvalidRequest(f"messages.{i}: two assistant turns in a row")
            if pending:
                raise InvalidRequest(f"messages.{i}: tool calls {sorted(pending)} were never answered")
            pending = {c.id for c in m.tool_calls}
        elif m.role == "tool":
            answered = {p.call_id for p in m.parts if isinstance(p, ToolResult)}
            if answered - pending:
                raise InvalidRequest(f"messages.{i}: results for unknown calls {sorted(answered - pending)}")
            pending -= answered
            if pending:
                raise InvalidRequest(f"messages.{i}: tool calls {sorted(pending)} have no result")
        elif m.role == "user":
            if pending:
                raise InvalidRequest(f"messages.{i}: a user turn before the tool results")
            if any(not isinstance(p, TextPart) for p in m.parts):
                raise InvalidRequest(f"messages.{i}: a user turn carries non-text parts")
        last_role = m.role
    if last_role == "assistant":
        raise InvalidRequest("the conversation must end with a user or tool turn")


class FakeProvider:
    """Returns scripted turns in order (a dict from reply(), REFUSAL, or an exception to raise); records
    every request as the router sent it. `on_call` runs before each scripted reply (to advance a clock)."""

    def __init__(self, name, *script, on_call=None, prices=PRICES):
        self.name, self.script, self.requests, self.on_call, self.prices = name, list(script), [], on_call, prices

    def complete(self, *, model, system, messages, tools, max_tokens, effort, timeout_s, tool_choice="auto"):
        check_messages(messages)
        self.requests.append({"model": model, "system": system, "messages": copy.deepcopy(list(messages)),
                              "tools": list(tools), "max_tokens": max_tokens, "effort": effort,
                              "timeout_s": timeout_s, "tool_choice": tool_choice})
        if not self.script:
            raise AssertionError(f"{self.name}: no scripted reply left for call {len(self.requests)}")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        if self.on_call:
            self.on_call()
        usage = item["usage"]
        message = Message("assistant", list(item["parts"]), provider_state={self.name: {"call": len(self.requests)}})
        return Completion(message=message, stop_reason=item["stop"], usage=usage, provider=self.name,
                          model=item["model"] or model, requested_model=model, duration_s=0.1,
                          cost_usd=pricing.cost_usd(usage, self.prices), raw_id=f"{self.name}_{len(self.requests)}")


def make_router(*primary_script, fallback_script=(), on_call=None, attempts=2, cfg=CFG):
    """A real Router over two FakeProviders ('openai' primary, 'anthropic' fallback), no sleeping."""
    primary = FakeProvider("openai", *primary_script, on_call=on_call)
    fallback = FakeProvider("anthropic", *fallback_script, on_call=on_call)
    llm = cfg["llm"]
    r = Router(Role(primary, llm["primary"]["model"], prices=PRICES),
               Role(fallback, llm["fallback"]["model"], prices=PRICES), attempts=attempts, backoff_s=0.0,
               sleep=lambda s: None)
    r.fake_primary, r.fake_fallback = primary, fallback
    return r


# ---- the store ----

def file_catalog() -> dict[str, dict]:
    """docs/catalog.yaml in the store's catalog() shape (the store seeds its documents table from it)."""
    out = {}
    for doc_id, e in tools.catalog().items():
        out[doc_id] = {"title": e["title"], "program": e["program"], "doc_type": e["doc_type"],
                       "authority": e["authority"], "publisher": e.get("publisher", ""), "date": str(e["date"]),
                       "source_url": e["source_url"], "file": e["file"], "pages": e["pages"], "version": f"{doc_id}@v1"}
    return out


class FakeStore:
    """Only what the tools read: documents.catalog(), documents.generation(), content.table_rows(),
    content.figures_for_page()."""

    def __init__(self, catalog=None, tables=None, figures=None, generation=1):
        cat = file_catalog() if catalog is None else catalog
        tables, figures = tables or {}, figures or {}
        self.table_calls = []

        def table_rows(name, *, drug=None, limit=2000):
            self.table_calls.append((name, drug, limit))
            return list(tables.get(name, []))[:limit]

        self.documents = NS(catalog=lambda: copy.deepcopy(cat), generation=lambda: generation)
        self.content = NS(table_rows=table_rows, figures_for_page=lambda d, p: list(figures.get((d, p), [])))


PDL_HIT = {"doc_id": "ny_medicaid_pdl", "page": 34, "program": "NY Medicaid", "authority": "binding",
           "date": "2026-09-14", "text": "Ozempic pen ..."}


class FakeSearch:
    """search_fn returning one PDL p34 chunk per call (or `results` per query); records the calls."""

    def __init__(self, results=None):
        self.calls, self.results = [], results

    def __call__(self, query, k, *, store, embed, program=None, cfg=None):
        self.calls.append({"query": query, "k": k, "program": program})
        if self.results is None:
            return [dict(PDL_HIT)]
        return list(self.results.get(query, []))[:k]

    def agent_calls(self, question=QUESTION):
        """The searches the agent's own queries ran (each tool call also searches the question)."""
        return [c for c in self.calls if c["query"] != question]


def make_pdf(path: Path, pages: int = PDL_PAGES, text="Ozempic pen: preferred. Rybelsus: non-preferred.") -> Path:
    import pymupdf
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"{text} (page {i + 1})")
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def pdf(tmp_path):
    return make_pdf(tmp_path / "doc.pdf")


def make_tools(store=None, search=None, cfg=CFG, pdf_path=None, question=QUESTION, **kw):
    search = search if search is not None else FakeSearch()
    box = tools.ToolBox(store or FakeStore(), search, embed=None, cfg=cfg, pdf_path=pdf_path, question=question, **kw)
    box.fake_search = search
    return box


# ---- synthetic drug tables, in the store's row shape ----

VA_CELLS = {
    5: ["The VA National Formulary is dosage form specific: if a dosage form is not listed, it is non-formulary.",
        "", "", "", "", "", ""],
    6: ["PA-N = national PA; PA-V = VISN PA; PA-F = facility-level prior authorization.", "", "", "", "", "", ""],
    7: ["VA Class", "Restriction", "Generic", "Dosage Form", "Comments", "U/E Formulary", "Clinical Guidance"],
    8: ["HS502", "PA-F", "SEMAGLUTIDE (EQV-OZEMPIC)", "INJ,SOLN", "", "", ""],
    9: ["CN101", "", "BUPRENORPHINE/NALOXONE", "TAB,SUBLINGUAL", "", "", ""],
    10: ["CN101", "", "BUPRENORPHINE", "FILM,BUCCAL", "", "", ""],
}
VA_ROWS = [{"row": n, "cells": cells, "drug": cells[2]} for n, cells in VA_CELLS.items()]

NY_ROWS = [
    {"row_id": "ny_medicaid_pdl#p34#row-1", "page": 34, "drug_name": "Ozempic®", "drug_name_norm": "ozempic",
     "generic_of": None, "section": "III. Endocrine", "drug_class": "GLP-1 Receptor Agonists", "class_flags": ["CC"],
     "status": "preferred", "flags": [], "marker": None, "coverage_parameters": "Trial of metformin required.",
     "coverage_pages": [34, 35], "class_start_page": 34, "continued_from_page": None, "extraction_method": "test",
     "name_base": "ozempic", "drug": "Ozempic"},
    {"row_id": "ny_medicaid_pdl#p34#row-2", "page": 34, "drug_name": "Rybelsus®", "drug_name_norm": "rybelsus",
     "generic_of": None, "section": "III. Endocrine", "drug_class": "GLP-1 Receptor Agonists", "class_flags": ["CC"],
     "status": "non-preferred", "flags": ["ST"], "marker": None, "coverage_parameters": "Trial of metformin required.",
     "coverage_pages": [34, 35], "class_start_page": 34, "continued_from_page": None, "extraction_method": "test",
     "name_base": "rybelsus", "drug": "Rybelsus"},
]
TABLES = {"va_formulary": VA_ROWS, "ny_pdl": NY_ROWS}


# ---- the fakes' own checks ----

def _msgs(*spec):
    out = []
    for role, parts in spec:
        out.append(Message(role, parts))
    return out


@pytest.mark.parametrize("messages, err", [
    (_msgs(("assistant", [text("a")])), "first message"),
    (_msgs(("user", [text("q")]), ("assistant", [ToolCall("t1", "search_documents", {})]), ("user", [text("x")])),
     "before the tool results"),
    (_msgs(("user", [text("q")]), ("assistant", [ToolCall("t1", "search_documents", {})]),
           ("tool", [ToolResult("t2", "r")])), "unknown calls"),
    (_msgs(("user", [text("q")]), ("assistant", [text("a")])), "end with a user"),
])
def test_the_fake_provider_rejects_what_the_apis_reject(messages, err):
    with pytest.raises(InvalidRequest, match=err):
        check_messages(messages)


def test_the_fake_provider_accepts_a_user_note_after_tool_results():
    check_messages(_msgs(("user", [text("q")]), ("assistant", [ToolCall("t1", "search_documents", {})]),
                         ("tool", [ToolResult("t1", "[]")]), ("user", [text("budget")])))


def test_the_synthetic_tables_build_with_the_real_table_code():
    f = tools.va_formulary_from_rows(VA_ROWS)
    assert (f.header_row, f.rule_row, f.pa_row) == (7, 5, 6) and list(f.rows.index) == [8, 9, 10]
    from pharmassist.tables import ny_pdl, va_formulary
    assert va_formulary.lookup("Ozempic", formulary=f)["result"] == "exact_match"
    r = ny_pdl.lookup("Ozempic", rows=NY_ROWS)
    assert r["result"] == "exact_match" and r["classes"][0]["rows"][0]["listed_as"] == "preferred"
    assert json.dumps(r)  # the lookup output stays JSON-serialisable, as the model receives it
