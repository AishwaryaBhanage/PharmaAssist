"""Section-wise parent-child chunks.

Sections come from the PDF outline when it has one (each entry placed by finding its title on the
target page; the outline's own coordinates are unreliable in this corpus), otherwise from bold
lines set larger than body text. The NY PDL's drug-class pages (4–60) are built from the PDL row
extractor, one section per class, so those tables stay whole and structured.

- Parents: a section of at most `parent_max_tokens`; a longer one is split into its own text and
  its sub-sections, recursively, at block boundaries with no overlap. A table or paragraph (e.g.
  a recommendation) is never split; one longer than the limit is its own parent.
- Children: windows of at most `child_tokens` (heading-path prefix included) inside one parent, at
  sentence or table-row boundaries, overlapping by `overlap_tokens`. Children are what search ranks.
- Text keeps page markers ("[p 34]") wherever the page changes; repeated headers and footers
  (margin lines on more than half the pages) are dropped.
"""

import re
from collections import Counter
from dataclasses import dataclass, field

import pymupdf

from pharmassist.catalog import docs_dir
from pharmassist.chunkers.base import Chunk, Chunker, block_text
from pharmassist.parsers.base import Block

MARGIN = 0.08          # top/bottom share of the page where running headers and footers live
REPEAT_FRAC = 0.5      # a margin line on more than this share of pages is boilerplate
SKIP_TITLES = {"structure bookmarks", "document", "table of contents", "contents"}
PREFIX_MAX_WORDS = 40  # long heading paths are shortened from the middle
PDL_DOC, PDL_PAGES = "ny_medicaid_pdl", range(4, 61)
PAGE_MARKER_ALLOWANCE = 12  # tokens kept free for "[p N]" markers inside a child
SENTENCE = re.compile(r"(?<=[.!?;:])\s+(?=[A-Z0-9•(\[\"“])|\s*\n\s*(?=•|\d+\.\s|[A-Z])")


def _norm(s: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s.lower()).split())


@dataclass
class Unit:
    page: int
    text: str
    kind: str = "text"   # the parser block type: "text", "table" or "figure"
    header: str | None = None   # tables/figures: repeated at the top of every chunk that holds part of it
    meta: dict | None = None    # richer parsers: bbox, extraction method, figure id, verification


@dataclass
class Node:
    title: str
    level: int
    units: list[Unit] = field(default_factory=list)
    children: list["Node"] = field(default_factory=list)


@dataclass
class Parent:
    parent_id: str
    doc_id: str
    path: list[str]
    units: list[Unit]
    text: str = ""
    pages: list[int] = field(default_factory=list)


# ---- cleaning and headings ----

def _page_lines(doc) -> list[list[dict]]:
    """Per page: lines with text, y, size and boldness."""
    out = []
    for page in doc:
        lines = []
        for b in page.get_text("dict")["blocks"]:
            for l in b.get("lines", []):
                spans = [s for s in l["spans"] if s["text"].strip()]
                if spans:
                    lines.append({"text": " ".join("".join(s["text"] for s in spans).split()),
                                  "y": l["bbox"][1], "size": round(max(s["size"] for s in spans), 1),
                                  "bold": all("Bold" in s["font"] or s["flags"] & 16 for s in spans),
                                  "chars": sum(len(s["text"]) for s in spans)})
        out.append(lines)
    return out


def _repeated_margin(doc, blocks: list[Block]) -> set[str]:
    heights = {i + 1: p.rect.height for i, p in enumerate(doc)}
    seen = Counter()
    for b in blocks:
        h = heights[b.page]
        if b.type == "text" and (b.bbox[3] < MARGIN * h or b.bbox[1] > (1 - MARGIN) * h):
            seen[re.sub(r"\d+", "#", _norm(b.text or ""))] += 1
    return {t for t, n in seen.items() if t and n > REPEAT_FRAC * doc.page_count}


def _outline_anchors(doc, lines) -> list[tuple[int, float, int, str]]:
    """(page, y, level, title) for each usable outline entry, placed where its title is printed."""
    anchors = []
    for level, title, page, _ in doc.get_toc(simple=False):
        title = " ".join(title.split())
        if not title or _norm(title) in SKIP_TITLES or not 1 <= page <= doc.page_count:
            continue
        key = _norm(title)[:25]
        hit = next((l for l in lines[page - 1] if key and (_norm(l["text"]).startswith(key)
                                                       or key.startswith(_norm(l["text"])[:25] or "#"))
                    and len(_norm(l["text"])) >= min(len(key), 8)), None)
        anchors.append((page, hit["y"] if hit else 0.0, level, title))
    return anchors


def _number_levels(anchors):
    """The NY pharmacy manual's outline is flat; its bold 'N.0' headings are the sections."""
    return [(p, y, 1 if re.match(r"\d+\.0\b", t) else 2, t) for p, y, _, t in anchors]


def _repeated_lines(doc, lines) -> set[str]:
    """Lines printed on more than half the pages (running headers and footers)."""
    seen = Counter(k for pl in lines for k in {re.sub(r"\d+", "#", _norm(l["text"])) for l in pl})
    return {t for t, n in seen.items() if t and n > REPEAT_FRAC * doc.page_count}


def _font_anchors(doc, lines, pages) -> list[tuple[int, float, int, str]]:
    """Bold lines larger than body text; larger size = higher level. Adjacent lines of the same
    heading size (a title on two lines) are merged."""
    sizes = Counter()
    for pl in lines:
        for l in pl:
            sizes[l["size"]] += l["chars"]
    if not sizes:
        # an image-only PDF (scanned pages): no text spans, so no font sizes; the document becomes one
        # section and its OCR text is chunked by length (found with an uploaded 4-page scan, 2026-10-18)
        return []
    body = sizes.most_common(1)[0][0]
    running = _repeated_lines(doc, lines)
    heads = []
    for p in pages:
        for l in lines[p - 1]:
            if (l["bold"] and l["size"] >= body + 0.5 and 3 <= len(l["text"]) <= 120
                    and re.sub(r"\d+", "#", _norm(l["text"])) not in running):
                prev = heads[-1] if heads else None
                if prev and prev[0] == p and prev[4] == l["size"] and 0 < l["y"] - prev[1] < 2.2 * l["size"]:
                    heads[-1] = (p, prev[1], prev[2], prev[3] + " " + l["text"], l["size"])
                else:
                    heads.append((p, l["y"], None, l["text"], l["size"]))
    levels = {s: i + 1 for i, s in enumerate(sorted({x[4] for x in heads}, reverse=True))}
    return [(p, y, levels[s], t) for p, y, _, t, s in heads]


# ---- the PDL's drug-class pages ----

def _pdl_class_nodes(path=None) -> list[tuple[int, Node]]:
    """One node per PDL class (pages 4–60), from the row extractor: rows by column with flags and
    markers, then the class's coverage parameters, with page markers."""
    from pharmassist.tables.ny_pdl import extract
    classes: dict[tuple, dict] = {}
    for r in extract(PDL_PAGES, path=path):
        c = classes.setdefault((r.class_start_page, r.drug_class), {"rows": [], "row": r})
        c["rows"].append(r)
    out = []
    for (start, name), c in classes.items():
        r0 = c["row"]
        title = name + (f" ({', '.join(r0.class_flags)})" if r0.class_flags else "")
        node = Node(title, 2)
        for page in sorted({r.page for r in c["rows"]}):
            for status in ("preferred", "non-preferred"):
                items = []
                for r in c["rows"]:
                    if r.page == page and r.status == status:
                        extra = ", ".join(r.flags + ([f"{r.marker['meaning']}"] if r.marker else []))
                        items.append(r.drug_name + (f" ({extra})" if extra else ""))
                if items:
                    node.units.append(Unit(page, f"{status.capitalize()} drugs: " + "; ".join(items)))
        if r0.coverage_parameters:
            node.units.append(Unit(r0.coverage_pages[0] if r0.coverage_pages else start,
                                   "Coverage parameters: " + r0.coverage_parameters))
        node.title = f"{r0.section or 'Preferred Drug List'} > {title}"
        node.level = 1
        out.append((start, node))
    return out


# ---- tree, parents, children ----

class SectionChunker(Chunker):
    name = "sections"

    def __init__(self, token_spans, child_tokens: int = 350, overlap_tokens: int = 100,
                 parent_max_tokens: int = 1500):
        self.token_spans = token_spans
        self.child_tokens, self.overlap_tokens = child_tokens, overlap_tokens
        self.parent_max_tokens = parent_max_tokens
        self.parents: list[Parent] = []   # filled per document; the ingest pipeline saves them
        self._ntok: dict[str, int] = {}

    def ntok(self, text: str) -> int:
        if text not in self._ntok:
            self._ntok[text] = len(self.token_spans(text))
        return self._ntok[text]

    def tree(self, blocks: list[Block], entry: dict, path=None) -> Node:
        """`path` overrides the catalog's file (the ingestion worker passes its downloaded copy)."""
        doc = pymupdf.open(path or docs_dir() / entry["file"])
        lines = _page_lines(doc)
        boiler = _repeated_margin(doc, blocks)
        is_pdl = entry["id"] == PDL_DOC
        text_pages = [p for p in range(1, doc.page_count + 1) if not (is_pdl and p in PDL_PAGES)]
        outline = _outline_anchors(doc, lines) if not is_pdl else []
        if entry["id"] == "ny_medicaid_pharmacy_policy":
            outline = _number_levels(outline)
        anchors = outline if len(outline) >= 3 else _font_anchors(doc, lines, text_pages)

        events = [(p, y, 0, ("anchor", lvl, t)) for p, y, lvl, t in anchors]
        for b in blocks:
            if is_pdl and b.page in PDL_PAGES:
                continue
            text = block_text(b).strip()
            if not text or re.sub(r"\d+", "#", _norm(text)) in boiler:
                continue
            for u in self.units_for(b, text):
                events.append((b.page, b.bbox[1] + 1, 1, ("unit", u)))  # after a heading on its line
        if is_pdl:
            events += [(start, 0.0, 0, ("node", node)) for start, node in _pdl_class_nodes(path)]
        events.sort(key=lambda e: (e[0], e[1], e[2]))

        root = Node(entry["title"], 0)
        stack = [root]
        for _, _, _, ev in events:
            if ev[0] == "anchor":
                _, level, title = ev
                while stack[-1].level >= level:
                    stack.pop()
                node = Node(title, level)
                stack[-1].children.append(node)
                stack.append(node)
            elif ev[0] == "node":
                stack = [root]
                root.children.append(ev[1])
            else:
                u = ev[1]
                head = _norm(stack[-1].title)
                if head and u.kind == "text" and _norm(u.text) == head:
                    continue  # the heading line itself; the path prefix carries it
                stack[-1].units.append(u)
        return root

    def units_for(self, block: Block, text: str) -> list[Unit]:
        """The units one parsed block contributes (subclasses split tables and figures)."""
        return [Unit(block.page, text, block.type)]

    def _tokens(self, node: Node) -> int:
        return sum(self.ntok(u.text) + (self.ntok(u.header) if u.header else 0) for u in node.units) + sum(self._tokens(c) for c in node.children)

    @staticmethod
    def _flat(node: Node) -> list[Unit]:
        return node.units + [u for c in node.children for u in SectionChunker._flat(c)]

    def _pack(self, units: list[Unit]) -> list[list[Unit]]:
        groups, cur, n = [], [], 0
        for u in units:
            t = self.ntok(u.text) + (self.ntok(u.header) if u.header else 0)
            if cur and n + t > self.parent_max_tokens:
                groups.append(cur)
                cur, n = [], 0
            cur.append(u)
            n += t
        return groups + ([cur] if cur else [])

    def _cost(self, window: list[Unit], u: Unit) -> int:
        """Tokens `u` adds to a window: its text, plus its header when it starts a new header run."""
        prev = window[-1].header if window else None
        return self.ntok(u.text) + (self.ntok(u.header) if u.header and u.header != prev else 0)

    def decorate(self, chunk: Chunk, units: list[Unit]) -> None:
        """Subclasses add per-chunk metadata from the units it covers."""

    def _emit(self, node: Node, path: list[str], out: list[tuple[list[str], list[Unit]]]):
        if self._tokens(node) <= self.parent_max_tokens:
            units = self._flat(node)
            if units:
                out.append((path, units))
            return
        for group in self._pack(node.units):
            out.append((path, group))
        for c in node.children:
            self._emit(c, path + [c.title], out)

    @staticmethod
    def _with_pages(units: list[Unit]) -> str:
        parts, page, header = [], None, None
        for u in units:
            if u.page != page:
                parts.append(f"[p {u.page}]")
                page = u.page
            if u.header and u.header != header:
                parts.append(u.header)   # a table's columns / a figure's title and status, once per run
            header = u.header
            parts.append(u.text)
        return "\n".join(parts)

    def _prefix(self, entry: dict, path: list[str]) -> str:
        # an outline whose top entry restates the document title would repeat it
        title = _norm(entry["title"])
        path = [h for h in path if not (title.startswith(_norm(h)[:40]) and len(_norm(h)) >= 20)]
        words = (" > ".join([entry["title"], *path])).split()
        if len(words) > PREFIX_MAX_WORDS:
            words = words[:12] + ["…"] + words[-(PREFIX_MAX_WORDS - 13):]
        return " ".join(words) + "\n"

    def _sentences(self, units: list[Unit]) -> list[Unit]:
        out = []
        for u in units:
            if u.header:  # tables and figures split at rows / boxes, keeping their header
                out += [Unit(u.page, line, u.kind, u.header, u.meta) for line in u.text.split("\n") if line.strip()]
                continue
            for s in SENTENCE.split(u.text):
                if s.strip():
                    out.append(Unit(u.page, " ".join(s.split()) if "\n" not in s else s.strip(), u.kind, None, u.meta))
        return out

    def _hard_split(self, s: Unit, budget: int) -> list[Unit]:
        spans = self.token_spans(s.text)
        return [Unit(s.page, s.text[spans[i][0]:spans[min(i + budget, len(spans)) - 1][1]], s.kind, s.header, s.meta)
                for i in range(0, len(spans), budget)]

    def chunk(self, blocks: list[Block], entry: dict) -> list[Chunk]:
        self.parents = []
        groups: list[tuple[list[str], list[Unit]]] = []
        self._emit(self.tree(blocks, entry), [], groups)
        children = []
        for pn, (path, units) in enumerate(groups):
            prefix = self._prefix(entry, path)
            pid = f"{entry['id']}:s{pn}"
            pages = sorted({u.page for u in units})
            self.parents.append(Parent(pid, entry["id"], path, units, prefix + self._with_pages(units), pages))
            budget = self.child_tokens - self.ntok(prefix) - PAGE_MARKER_ALLOWANCE
            sents = []
            for s in self._sentences(units):
                room = budget - (self.ntok(s.header) if s.header else 0)
                sents += self._hard_split(s, max(room, 32)) if self.ntok(s.text) > room else [s]
            start, cn = 0, 0
            while start < len(sents):
                end, n = start, 0
                while end < len(sents) and n + self._cost(sents[start:end], sents[end]) <= budget:
                    n += self._cost(sents[start:end], sents[end])
                    end += 1
                end = max(end, start + 1)
                window = sents[start:end]
                chunk = self.make_chunk(entry, window[0].page, cn, prefix + self._with_pages(window))
                chunk.chunk_id = f"{pid}:c{cn}"
                chunk.pages = sorted({u.page for u in window})
                chunk.parent_id = pid
                self.decorate(chunk, window)
                children.append(chunk)
                cn += 1
                if end >= len(sents):
                    break
                # step back so the next window repeats ~overlap_tokens of this one
                back, nxt = 0, end
                while nxt - 1 > start and back + self.ntok(sents[nxt - 1].text) <= self.overlap_tokens:
                    nxt -= 1
                    back += self.ntok(sents[nxt].text)
                start = nxt
        return children
