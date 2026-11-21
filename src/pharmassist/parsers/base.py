"""Shared parser interface: every parser turns a PDF into a flat list of blocks."""

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Block:
    page: int                                     # 1-based PDF page
    type: str                                     # "text", "table" or "figure"
    text: str | None = None                       # text blocks; a figure's rendered interpretation
    rows: list[list[str | None]] | None = None    # table blocks
    bbox: tuple[float, float, float, float] | None = None  # x0, y0, x1, y1 in PDF points, top-left origin
    # richer parsers (docling) also fill these; the baseline parser leaves them empty
    header_rows: int = 0                          # tables: how many leading rows are column headers
    caption: str | None = None                    # tables and figures
    footnotes: list[str] | None = None            # tables and figures
    label: str | None = None                      # docling layout label (section_header, list_item, ...)
    extraction: str = "pdf_text"                  # pdf_text | ocr | tableformer | vision | ...
    figure_id: str | None = None                  # figures: key into the document's figure inventory
    verification: str | None = None               # figures: machine-interpreted status (see figures.py)


class Parser(ABC):
    name: str

    @abstractmethod
    def parse(self, path: Path, pages: Iterable[int] | None = None) -> list[Block]:
        """Parse a PDF, optionally only the given 1-based pages, into blocks in reading order."""
