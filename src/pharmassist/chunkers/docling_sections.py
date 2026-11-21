"""Section-wise parent-child chunks over Docling's parse.

Same section tree, parents and children as the sections chunker, adapted to richer blocks:
- A table is one unit whose header (caption + column-header rows) is repeated at the top of every
  chunk holding part of it; children split it between rows, never inside one. Footnotes stay at the
  end of the table body.
- An indexed figure (see parsers/figures.py) is one unit: its header names the figure, the PDF page
  and its machine-interpretation status; the body is one line per box with its labelled exits, then
  the complete start-to-end decision paths. A figure under the parent limit stays in one parent.
- Decorative or unreadable-only images contribute nothing here; they are listed in FIGURES.json.
- Each chunk carries provenance: source hash, printed page labels, section, content types,
  extraction methods, source bounding boxes, figure ids and verification status.
"""

import json
import re

import pymupdf

from pharmassist.catalog import docs_dir
from pharmassist.chunkers.base import Chunk
from pharmassist.chunkers.sections import SectionChunker, Unit
from pharmassist.config import PROJECT_ROOT
from pharmassist.parsers import figures as F
from pharmassist.parsers.base import Block

PAGE_OF = re.compile(r"\bPage\s+(\d+)\s+of\s+\d+\b", re.I)
BARE_LABEL = re.compile(r"^(\d{1,3}|[ivxlc]{1,6})$", re.I)
MARGIN = 0.1


def printed_page_labels(path) -> dict[int, str]:
    """PDF page -> the page number printed on it ("Page 21 of 165", or a bare number/roman numeral in
    the top or bottom margin). Pages without one are left out."""
    out = {}
    with pymupdf.open(path) as doc:
        for i, page in enumerate(doc):
            h = page.rect.height
            text = page.get_text()
            m = PAGE_OF.search(text)
            if m:
                out[i + 1] = m.group(1)
                continue
            for b in page.get_text("blocks"):
                t = b[4].strip()
                if (b[3] > (1 - MARGIN) * h or b[1] < MARGIN * h) and BARE_LABEL.match(t):
                    out[i + 1] = t
                    break
    return out


def is_toc(rows: list[list]) -> bool:
    """Most rows carry dot leaders ("Research Priorities ........ 71")."""
    hits = sum(1 for r in rows if any("....." in (c or "") for c in r))
    return bool(rows) and hits >= 0.5 * len(rows)


def fill_group_labels(rows: list[list], header_rows: int) -> list[list]:
    """Repeat row-group labels down their column. A tall merged cell (a rotated "Topic" spanning a
    page of recommendations) is often recognised for only its first rows; a leading column that is
    mostly empty below a value is such a label column, and its blanks take the value above."""
    body = [list(r) for r in rows[header_rows:]]
    if len(body) < 3:
        return rows
    for j in range(min(2, len(body[0]))):
        col = [r[j] if j < len(r) else "" for r in body]
        if col[0] and sum(1 for c in col if c) <= len(col) / 2:
            last = ""
            for r in body:
                if j < len(r):
                    last = r[j] = r[j] or last
    return [list(r) for r in rows[:header_rows]] + body


def _inside(a, b) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    area = (a[2] - a[0]) * (a[3] - a[1])
    return (w * h) / area if w > 0 and h > 0 and area > 0 else 0.0


def _records() -> dict:
    f = PROJECT_ROOT / "storage" / "figures" / "records.json"
    return json.loads(f.read_text()) if f.exists() else {}


class DoclingSectionChunker(SectionChunker):
    name = "docling_sections"

    def __init__(self, token_spans, **kw):
        super().__init__(token_spans, **kw)
        self.records = _records()
        self.source_sha256: str | None = None   # set by the ingest pipeline from the document version
        self.printed: dict[int, str] = {}

    def units_for(self, block: Block, text: str) -> list[Unit]:
        meta = {"ctype": block.type, "extraction": block.extraction,
                "bbox": [block.page, *block.bbox] if block.bbox else None}
        if block.type == "table":
            if is_toc(block.rows or []):
                return []   # a table of contents: page-number leaders, no content
            nh = block.header_rows
            rows = [" | ".join(c or "" for c in r) for r in fill_group_labels(block.rows or [], nh)]
            head = f"[Table{': ' + block.caption if block.caption else ''}] (PDF page {block.page})"
            if nh:
                head += "\nColumns: " + " / ".join(rows[:nh])
            body = rows[nh:] or rows
            body += [f"Table note: {f}" for f in block.footnotes or []]
            return [Unit(block.page, "\n".join(body), "table", head, meta)]
        if block.type == "figure":
            rec = self.records.get(block.figure_id)
            if not rec:
                return []
            head, lines = F.render(rec["record"], rec["status"], block.page)
            meta.update({"extraction": "vision", "figure_id": block.figure_id, "status": rec["status"]})
            return [Unit(block.page, "\n".join(lines), "figure", head, meta)]
        return [Unit(block.page, text, "text", None, meta)]

    def decorate(self, chunk: Chunk, units: list[Unit]) -> None:
        metas = [u.meta for u in units if u.meta] or [  # the NY PDL class pages: the row extractor's rows
            {"ctype": "table", "extraction": "pdl_row_extractor", "bbox": None}]
        chunk.source_sha256 = self.source_sha256
        chunk.printed_pages = [self.printed[p] for p in chunk.pages if p in self.printed]
        chunk.content_types = sorted({m["ctype"] for m in metas})
        chunk.extraction = sorted({m["extraction"] for m in metas})
        seen = []
        for m in metas:
            if m["bbox"] and m["bbox"] not in seen:
                seen.append(m["bbox"])
        chunk.bboxes = seen
        chunk.figure_ids = sorted({m["figure_id"] for m in metas if m.get("figure_id")})
        statuses = {m["status"] for m in metas if m.get("status")}
        chunk.verification = min(statuses, key=list(F.STATUS_TEXT).index) if statuses else None

    def chunk(self, blocks: list[Block], entry: dict) -> list[Chunk]:
        self.printed = printed_page_labels(docs_dir() / entry["file"])
        for b in blocks:  # the tree skips blocks without text; give indexed figures their title
            if b.type == "figure" and b.figure_id in self.records:
                b.text = self.records[b.figure_id]["record"].get("title") or "figure"
                b.bbox = tuple(self.records[b.figure_id]["bbox"])   # may be wider than docling's crop
        # a table continued on the next page with the same column headers keeps its caption
        prev = None
        for b in blocks:
            if b.type != "table":
                continue
            if (prev and not b.caption and prev.caption and b.page == prev.page + 1 and b.header_rows
                    and b.rows[:b.header_rows] == prev.rows[:prev.header_rows]):
                b.caption = prev.caption.removesuffix(" (continued)") + " (continued)"
            prev = b
        # loose text inside an indexed flowchart is OCR of the drawing; the figure unit carries it
        charts = [(r["page"], r["bbox"]) for r in self.records.values()
                  if r["doc_id"] == entry["id"] and r["record"].get("kind") == "flowchart"]
        blocks = [b for b in blocks if not (b.type == "text" and b.bbox and any(
            p == b.page and _inside(b.bbox, bb) > 0.8 for p, bb in charts))]
        children = super().chunk(blocks, entry)
        paths = {p.parent_id: " > ".join(p.path) for p in self.parents}
        for c in children:
            c.section = paths.get(c.parent_id)
        return children
