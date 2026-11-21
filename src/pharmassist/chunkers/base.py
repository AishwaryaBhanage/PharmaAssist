"""Shared chunker interface: turn one document's parsed blocks into retrievable chunks."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from pharmassist.parsers.base import Block


@dataclass
class Chunk:
    chunk_id: str      # "<doc_id>:p<page>:<n>" (fixed) or "<doc_id>:s<n>:c<m>" (sections)
    doc_id: str
    page: int          # the first page the chunk covers
    text: str
    program: str
    doc_type: str
    authority: str
    date: str
    pages: list[int] = field(default_factory=list)  # every page covered (sections chunker)
    parent_id: str | None = None                     # the parent section (sections chunker)
    # provenance (docling setups; empty for the older indexes)
    source_sha256: str | None = None                 # hash of the exact PDF that was parsed
    printed_pages: list[str] = field(default_factory=list)   # page labels printed on those pages
    section: str | None = None                       # heading path
    content_types: list[str] = field(default_factory=list)   # text / table / figure
    extraction: list[str] = field(default_factory=list)      # docling_text / tableformer / vision
    bboxes: list[list[float]] = field(default_factory=list)  # [page, x0, y0, x1, y1] per source block
    figure_ids: list[str] = field(default_factory=list)
    verification: str | None = None                  # figures: machine-interpreted status


def block_text(block: Block) -> str:
    """Text of a block; tables are flattened to one line per row, cells joined by " | "."""
    if block.type == "table":
        return "\n".join(" | ".join(" ".join((c or "").split()) for c in row) for row in block.rows or [])
    return block.text or ""


class Chunker(ABC):
    name: str

    @abstractmethod
    def chunk(self, blocks: list[Block], entry: dict) -> list[Chunk]:
        """Chunk one document. `entry` is its catalog.yaml record (id, program, doc_type, ...)."""

    @staticmethod
    def make_chunk(entry: dict, page: int, n: int, text: str) -> Chunk:
        return Chunk(
            chunk_id=f"{entry['id']}:p{page}:{n}", doc_id=entry["id"], page=page, text=text,
            program=entry["program"], doc_type=entry["doc_type"],
            authority=entry["authority"], date=str(entry["date"]),
        )
