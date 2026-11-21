"""A citation as the UI shows it (CitationOut): stable id, document title, page or sheet row, a
label, the validated external link (only the document's own https source URL for that page) and the
app's own link to that page, plus the figures indexed on it. Moved from v1's agent_service; the
document list now comes from the store and the figures from `store.content`."""

from __future__ import annotations

from app.deps import API
from pharmassist.store.protocols import FigureRecord

SHEET = "Formulary"      # the VA formulary sheet drug rows come from (pharmassist.tables.va_formulary.SHEET)
STATUS_TEXT = {
    "machine_interpreted": "machine-interpreted from the page image by a vision model; not verified",
    "ocr_checked": "machine-interpreted from the page image by a vision model; structure and OCR cross-check passed",
    "reviewed": "machine-interpreted from the page image by a vision model; compared box by box against the page "
                "image (not clinician-verified)",
}


def parse_locator(loc: str) -> tuple[str, str, int]:
    """'ny_medicaid_pdl:p34' -> ('ny_medicaid_pdl', 'p', 34)."""
    doc_id, rest = loc.rsplit(":", 1)
    return doc_id, rest[0], int(rest[1:])


def crop_name(f: FigureRecord) -> str | None:
    return f.crop_s3_key.rsplit("/", 1)[-1] if f.crop_s3_key else None


def figure_view(f: FigureRecord) -> dict:
    name = crop_name(f)
    return {"figure_id": f.figure_id, "kind": f.kind, "title": f.title, "status": f.status,
            "status_text": STATUS_TEXT.get(f.status, f.status),
            "crop_url": f"{API}/figures/{f.document_id}/{name}" if name else None}


def citation_view(c: dict, catalog: dict[str, dict], figures_for_page) -> dict:
    """`catalog`: store.documents.catalog(); `figures_for_page(doc_id, page) -> list[FigureRecord]`."""
    loc = c.get("locator") or ""
    doc_id = c.get("doc_id")
    entry = catalog.get(doc_id) or {}
    try:
        _, kind, n = parse_locator(loc)
    except (ValueError, IndexError):
        kind, n = None, None
    sheet = None
    if kind == "r":
        sheet, label = SHEET, f"{SHEET} sheet, row {n}"
    elif kind == "p":
        label = f"Page {n}"
    else:
        label = "Location not available"
    link, source = c.get("link"), entry.get("source_url") or ""
    valid = bool(link and source.startswith("https://") and link.split("#", 1)[0] == source and not c.get("flag"))
    is_pdf = str(entry.get("file", "")).endswith(".pdf")
    figures = []
    if kind == "p" and doc_id:
        try:
            figures = [figure_view(f) for f in figures_for_page(doc_id, n)]
        except Exception:   # a figure lookup failure must not lose the citation
            figures = []
    return {"id": loc, "doc_id": doc_id, "document": entry.get("title") or "Unknown document",
            "label": label, "page": n if kind == "p" else None, "sheet": sheet, "row": n if kind == "r" else None,
            "url": link if valid else None,
            "local_url": f"{API}/sources/{doc_id}/p{n}.pdf" if kind == "p" and is_pdf else None,
            "flagged": bool(c.get("flag")), "flag_reason": c.get("flag"), "figures": figures}
