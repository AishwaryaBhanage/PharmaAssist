"""The agent's tools: definitions sent to the model, and a ToolBox that runs them for one question.

v2: the ToolBox reads from the `Store` contracts (store/protocols.py) instead of the v1 index files.
search_documents calls `pharmassist.search.hybrid.search` (stream A; v1's result-dict shape),
list_documents reads `store.documents.catalog()`, read_page opens the source PDF through an injected
`pdf_path(doc_id)` resolver (the API downloads from S3 into storage.pdf_cache_dir; tests pass a tmp
file) and adds the page's figure interpretations from `store.content.figures_for_page` when asked,
and the drug lookups match over `store.content.table_rows(...)` with the same matching code as v1
(tables/), so their output text is unchanged.

The ToolBox remembers every (doc_id, page) a tool returned, which is what the citation check uses,
and the text it returned for each, which the trace keeps for the offline answer checks (they never
run while answering); it times each call for the trace. One ToolBox serves one question.

Every search_documents call also searches the staff's original question (same program and k), so
the agent's own wording can never be the only query: an agent query that misses evidence the
question itself finds (golden Q01, Q04, Q19) no longer loses it. The result is the union of both
top-k lists, deduplicated by unit (parent section or chunk) so a unit both found takes one slot,
ordered by reciprocal rank fusion. Neither list is cut back to k: in the golden set the question's
own search ranks missed gold at 7 of 8, which a k-limited fusion drops. The original question's
results are cached per (program, k) for the run.
"""

import json
import re
import threading
import weakref
import time
from concurrent.futures import ThreadPoolExecutor
from functools import cache
from pathlib import Path

from pharmassist.llm.base import ToolSpec

PROGRAMS = ("VA", "Medicare Part D", "NY Medicaid")
RRF_K = 60  # the same fusion constant the hybrid search uses
MAX_MERGED = 20  # cap on the union of the two top-k lists (k is at most 15)
RESULT_CHARS = 4000  # of each tool result kept in the trace for LangSmith's tool runs
_POOL = ThreadPoolExecutor(max_workers=4)  # the original-question and agent searches run side by side
STATUSES = ("answered", "not_in_documents", "out_of_scope")
FORMULARY_UNAVAILABLE = ("The VA National Formulary spreadsheet isn't available in the searchable "
                         "documents yet; don't infer its contents.")

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


def _lookup_summary(result: str) -> dict:
    """A lookup result's category and row count, without its contents."""
    try:
        r = json.loads(result)
    except (TypeError, ValueError):
        return {}
    rows = len(r.get("rows") or []) + sum(len(c.get("rows") or []) for c in r.get("classes") or [])
    return {"result": r.get("result"), "rows": rows}


class ToolError(Exception):
    """A tool failure the model should see (bad argument, unknown page) rather than a crash."""


@cache
def catalog() -> dict[str, dict]:
    """The file catalog (docs/catalog.yaml): v1's source of truth, still used by the eval, rag_v1 and
    verify modules. The agent itself reads the store's catalog (ToolBox.catalog)."""
    from pharmassist.catalog import load_catalog
    return {e["id"]: e for e in load_catalog()}


def local_pdf_path(doc_id: str, cat: dict | None = None) -> Path:
    """The source PDF in docs/ (the CLI and local runs); the API injects an S3 downloader instead."""
    from pharmassist.catalog import docs_dir
    entry = (cat or catalog()).get(doc_id)
    if not entry:
        raise ToolError(f"unknown doc_id {doc_id!r}")
    return docs_dir() / entry["file"]


@cache
def _pdf(doc_id: str):
    """A local source PDF by doc id (docs/ via the file catalog); the eval judge reads cited pages with it."""
    import pymupdf
    return pymupdf.open(local_pdf_path(doc_id))


def locator(doc_id: str, page: int | None = None, row: int | None = None) -> str:
    """What a tool returned and a citation points at: 'doc:p34' (PDF page) or 'doc:r1697' (sheet row)."""
    return f"{doc_id}:r{row}" if row is not None else f"{doc_id}:p{page}"


def parse_locator(loc: str) -> tuple[str, str, int]:
    """'ny_medicaid_pdl:p34' -> ('ny_medicaid_pdl', 'p', 34)."""
    doc_id, rest = loc.rsplit(":", 1)
    return doc_id, rest[0], int(rest[1:])


def page_link(doc_id: str, page: int | None, cat: dict | None = None) -> str | None:
    """Link to a cited page: the catalog's source URL with #page=N (PDFs only)."""
    entry = (cat if cat is not None else catalog()).get(doc_id)
    if not entry:
        return None
    if not str(entry.get("file") or "").lower().endswith(".pdf") or page is None:
        return entry.get("source_url")
    return f"{entry.get('source_url')}#page={page}"


def _same_query(a: str, b: str) -> bool:
    """Equal ignoring case, spacing and punctuation (so they'd return the same results)."""
    words = lambda s: re.findall(r"\w+", s.lower())
    return words(a) == words(b)


def _unit_id(h: dict) -> str:
    """What a result stands for: its parent section (parent-child setups), else its chunk."""
    if h.get("matched_child") and h.get("parent_id"):
        return h["parent_id"]
    if h.get("chunk_id"):
        return h["chunk_id"]
    return f"{h['doc_id']}:p{h['page']}:{(h.get('text') or '')[:80]}"


def fuse(lists: dict[str, list[dict]], limit: int) -> tuple[list[dict], list[dict]]:
    """RRF over ranked result lists ({source: hits}): every distinct unit, best first, at most
    `limit`. Returns the hits and, for each, which sources found it at what rank. Ties keep the
    first source's order (the original question)."""
    score, best, found_by, order = {}, {}, {}, []
    for s_i, (source, hits) in enumerate(lists.items()):
        for rank, h in enumerate(hits, 1):
            u = _unit_id(h)
            if u not in score:
                score[u], best[u], found_by[u] = 0.0, h, {}
                order.append((u, s_i, rank))
            score[u] += 1 / (RRF_K + rank)
            found_by[u][source] = rank
    first = {u: (s_i, rank) for u, s_i, rank in order}
    top = sorted(score, key=lambda u: (-score[u], min(found_by[u].values()), first[u]))[:limit]
    return [best[u] for u in top], [{"unit": u, "found_by": found_by[u]} for u in top]


def hybrid_search(query: str, k: int, *, store, embed, program=None, cfg=None) -> list[dict]:
    """The default search: stream A's pgvector + full-text hybrid, imported lazily so this module
    loads without it (tests inject a stub)."""
    from pharmassist.search.hybrid import search
    return search(query, k, store=store, embed=embed, program=program, cfg=cfg)


# ---- drug tables from the store: built once per (store, table, index generation) ----

_tables_lock = threading.Lock()
# per live store object (weak keys: a store that is gone takes its tables with it, and a recycled object
# id can never alias another store), then per table: (index generation, built table)
_tables: "weakref.WeakKeyDictionary[object, dict[str, tuple]]" = weakref.WeakKeyDictionary()
_tables_by_id: dict[tuple, tuple] = {}   # fallback for stores that cannot be weakly referenced


def _generation(store) -> int | None:
    try:
        return store.documents.generation()
    except Exception:
        return None


def va_formulary_from_rows(rows: list[dict]):
    """A tables.va_formulary.Formulary from the store's `va_formulary` rows. Each row is one sheet
    row (notes, header and drug rows alike): {"row": <spreadsheet row number>, "cells": [7 strings
    A:G]}; rows keyed by the header labels instead of "cells" are accepted too."""
    import pandas as pd
    from pharmassist.tables import va_formulary
    cells = {}
    for r in rows:
        n = int(r.get("row") if r.get("row") is not None else r.get("row_no"))
        vals = r.get("cells")
        if vals is None:
            vals = [str(r.get(h) or r.get(f) or "") for h, f in zip(va_formulary.HEADER, va_formulary.FIELDS)]
        cells[n] = [str(v) if v is not None else "" for v in vals]
    if not cells:
        raise ToolError("the store holds no VA formulary rows")
    return va_formulary.from_cells(pd.DataFrame.from_dict(cells, orient="index").sort_index())


def _table(store, name: str):
    gen = _generation(store)
    with _tables_lock:
        try:
            hit = _tables.get(store, {}).get(name)
        except TypeError:                       # not weak-referenceable
            hit = _tables_by_id.get((id(store), name))
        if hit is not None and hit[0] == gen:
            return hit[1]
    rows = store.content.table_rows(name, limit=100_000)
    if not rows:
        raise ToolError(f"the store holds no {name} rows")
    built = va_formulary_from_rows(rows) if name == "va_formulary" else rows
    with _tables_lock:
        try:
            _tables.setdefault(store, {})[name] = (gen, built)
        except TypeError:
            _tables_by_id[(id(store), name)] = (gen, built)
    return built


class ToolBox:
    def __init__(self, store, search_fn=None, embed=None, cfg: dict | None = None, *, pdf_path=None,
                 question: str | None = None, clock=time.perf_counter, structured: bool | None = None,
                 page_figures: bool | None = None):
        """One question's tools. `store`: a Store (protocols.py). `search_fn(query, k, *, store, embed,
        program, cfg)` returning v1-shaped hit dicts (default: pharmassist.search.hybrid.search).
        `embed(text) -> vector` for one query (the app wraps Router.embed, which takes a list). `cfg`: the whole config (agent.search_k,
        agent.read_page_chars, agent.structured_lookups, agent.page_figures, search.*). `pdf_path(doc_id)
        -> Path` resolves a document's PDF (default: docs/ via the store's catalog `file`). `question` is
        the staff's original question: every search also runs it; ask() sets it when None."""
        if cfg is None:
            from pharmassist.config import load_config
            cfg = load_config()
        acfg = cfg.get("agent", {})
        self.store, self.embed, self.cfg = store, embed, cfg
        self.search_fn = search_fn or hybrid_search
        self.search_cfg = cfg.get("search", {})
        self.search_k = int(acfg.get("search_k", 8))
        self.read_page_chars = int(acfg.get("read_page_chars", 8000))
        self.structured = bool(acfg.get("structured_lookups", True)) if structured is None else structured
        self.page_figures = bool(acfg.get("page_figures", False)) if page_figures is None else page_figures
        self._pdf_path = pdf_path or (lambda doc_id: local_pdf_path(doc_id, self.catalog))
        self.clock, self.question = clock, question
        self.seen: set[str] = set()  # every locator ('doc:p34', 'doc:r1697') a tool returned
        self.evidence: dict[str, str] = {}  # locator -> the text tools returned for it
        self._evidence_parts: dict[str, list[str]] = {}
        self.calls: list[dict] = []
        self._original_cache: dict[tuple, list[dict]] = {}  # (program, k) -> original-question hits
        self._search_meta: dict | None = None
        self._catalog: dict | None = None
        self._pdfs: dict = {}

    @property
    def catalog(self) -> dict[str, dict]:
        """{doc_id: {title, program, doc_type, authority, publisher, date, source_url, file, pages, ...}}
        for documents with an active version, read once per question."""
        if self._catalog is None:
            self._catalog = {k: dict(v) for k, v in self.store.documents.catalog().items()}
        return self._catalog

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

    @property
    def evidence_parts(self) -> dict[str, list[str]]:
        """Each tool result recorded for a locator, separately (lookup results stay parseable)."""
        return self._evidence_parts

    def queries(self) -> list[str]:
        """Every search query run for the question: the agent's and the original question."""
        out = []
        for c in self.calls:
            for e in (c.get("search") or {}).get("executed", []):
                if e["query"] not in out:
                    out.append(e["query"])
            if c["name"] == "search_documents" and c["input"].get("query") not in out:
                out.append(c["input"].get("query"))
        return out

    def _add_evidence(self, texts: dict[str, str]) -> None:
        for loc, text in texts.items():
            parts = self._evidence_parts.setdefault(loc, [])
            if text not in parts:
                parts.append(text)
                self.evidence[loc] = "\n\n".join(parts)

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

    def _timed(self, text: str, program: str | None, k: int) -> tuple[list[dict], float]:
        t0 = time.perf_counter()
        hits = self.search_fn(text, k, store=self.store, embed=self.embed, program=program, cfg=self.search_cfg)
        return hits, round(time.perf_counter() - t0, 3)

    def _search_with_original(self, query: str, program: str | None, k: int) -> list[dict]:
        """The agent's query and the original question (same program and k), run concurrently and
        fused; the original's results come from the run's cache when already searched."""
        executed, lists = [], {}
        key = (program, k)
        original = self.question
        futures = {}
        if original:
            if key in self._original_cache:
                lists["original"] = self._original_cache[key]
                executed.append({"source": "original", "query": original, "program": program, "k": k,
                                 "seconds": 0.0, "cached": True, "results": len(lists["original"])})
            else:
                futures["original"] = _POOL.submit(self._timed, original, program, k)
        if not original or not _same_query(query, original):
            futures["agent"] = _POOL.submit(self._timed, query, program, k)
        for source in ("original", "agent"):
            if source in futures:
                hits, secs = futures[source].result()
                lists[source] = hits
                if source == "original":
                    self._original_cache[key] = hits
                executed.append({"source": source, "query": original if source == "original" else query,
                                 "program": program, "k": k, "seconds": secs, "cached": False,
                                 "results": len(hits)})
        fused, provenance = fuse(lists, min(MAX_MERGED, k * len(lists)))
        # each returned unit's score in each search that found it (recorded for tracing only)
        scores = {}
        for source, hits in lists.items():
            for h in hits:
                scores.setdefault(_unit_id(h), {}).setdefault(source, h.get("score"))
        n_in = sum(len(v) for v in lists.values())
        both = sum(len(p["found_by"]) > 1 for p in provenance)
        self._search_meta = {
            "original_query": original, "agent_query": query, "executed": executed,
            "duplicates_merged": n_in - len({_unit_id(h) for v in lists.values() for h in v}),
            "returned": len(fused), "from_both": both,
            "from_original_only": sum(set(p["found_by"]) == {"original"} for p in provenance),
            "from_agent_only": sum(set(p["found_by"]) == {"agent"} for p in provenance),
            "provenance": provenance,
            "hits": [{"unit": p["unit"], "doc_id": h["doc_id"], "pages": h.get("pages") or [h["page"]],
                      "ranks": p["found_by"], "scores": scores.get(p["unit"], {})}
                     for h, p in zip(fused, provenance)]}
        return fused

    def _pdf(self, doc_id: str):
        if doc_id not in self._pdfs:
            import pymupdf
            path = self._pdf_path(doc_id)
            try:
                self._pdfs[doc_id] = pymupdf.open(path)
            except Exception as e:
                raise ToolError(f"the PDF for {doc_id} couldn't be opened ({type(e).__name__})") from e
        return self._pdfs[doc_id]

    def _figures(self, doc_id: str, page: int) -> list[str]:
        """Rendered vision records of the indexed figures on one page (header + lines), in figure order."""
        from pharmassist.parsers.figures import render
        out = []
        try:
            records = self.store.content.figures_for_page(doc_id, page)
        except Exception:
            return out  # figures are an extra; a store hiccup shouldn't fail the page read
        for r in sorted(records, key=lambda r: r.figure_id):
            head, lines = render(r.record, r.status, page)
            out.append("\n".join([head, *lines]))
        return out

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
