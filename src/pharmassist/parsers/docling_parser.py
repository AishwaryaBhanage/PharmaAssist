"""Docling parser: layout, reading order, TableFormer tables, picture classification and OCR.

Docling is an ingestion-only dependency (the `ingest` extra in pyproject.toml); the web app never imports it.

What it adds over the baseline parser:
- Tables keep their structure: merged cells are expanded into every row/column they cover, column
  header rows are counted, and captions and footnotes travel with the table.
- Every embedded image is accounted for. Docling's pictures are classified (flow_chart, bar_chart,
  logo, icon, ...); images Docling's layout model missed (it misses the diabetes guideline's raster
  flowcharts entirely) are found from the PDF's own image blocks. Each one lands in the figure
  inventory with a decision; nothing is dropped silently (see figures.py).
- Text inside a picture is not emitted as loose body text, where it would read as a jumble. (The
  figure's `ocr_text` is filled only for images Docling missed, from the PDF text layer; flowcharts
  are cross-checked against an independent OCR of their crop in scripts/extract_figures.py.)

Results are cached by source hash + parser configuration: storage/parse_cache/<doc>/<key>.json.
"""

import hashlib
import json
import time
from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path

import pymupdf

from pharmassist.config import PROJECT_ROOT
from pharmassist.parsers.base import Block, Parser

PARSER_VERSION = 1           # bump when the conversion below changes; it invalidates the cache
IMAGES_SCALE = 2             # figure crops at 144 dpi
MIN_IMAGE_FRAC = 0.02        # PDF images smaller than this share of the page are inventoried as tiny
COVER_OVERLAP = 0.5          # a PDF image this much inside a docling picture is that picture
SKIP_LABELS = {"page_header", "page_footer"}  # running heads; printed page numbers are read separately


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _options_key() -> dict:
    import importlib.metadata as m
    return {"parser_version": PARSER_VERSION, "docling": m.version("docling"), "ocr": "auto",
            "tables": "tableformer-accurate", "picture_classification": True, "images_scale": IMAGES_SCALE}


def cache_key(path: Path) -> tuple[str, str]:
    opts = json.dumps(_options_key(), sort_keys=True)
    return sha256(path), hashlib.sha256(opts.encode()).hexdigest()[:12]


def _overlap(a, b) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    area = (a[2] - a[0]) * (a[3] - a[1])
    return (w * h) / area if w > 0 and h > 0 and area > 0 else 0.0


def _converter():
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    opts = PdfPipelineOptions()
    opts.do_ocr = True                      # bitmap regions only (Docling's default), not full pages
    opts.do_table_structure = True          # TableFormer, accurate mode with cell matching (defaults)
    opts.do_picture_classification = True
    opts.generate_picture_images = True
    opts.images_scale = IMAGES_SCALE
    return DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})


def _table_grid(table) -> tuple[list[list[str]], int]:
    """Rows of cell text with merged cells repeated across their span, and the header row count."""
    data = table.data
    grid = [["" for _ in range(data.num_cols)] for _ in range(data.num_rows)]
    header_rows = set()
    for c in data.table_cells:
        text = " ".join((c.text or "").split())
        for r in range(c.start_row_offset_idx, c.end_row_offset_idx):
            for k in range(c.start_col_offset_idx, c.end_col_offset_idx):
                if 0 <= r < data.num_rows and 0 <= k < data.num_cols:
                    grid[r][k] = text
        if c.column_header:
            header_rows.update(range(c.start_row_offset_idx, c.end_row_offset_idx))
    # header rows are the leading run only; a stray header flag mid-table is treated as body
    n = 0
    while n in header_rows:
        n += 1
    return grid, n


def _classes(pic) -> list[tuple[str, float]]:
    meta = getattr(pic, "meta", None)
    if meta is not None and getattr(meta, "classification", None):
        return [(p.class_name, round(p.confidence, 3)) for p in meta.classification.predictions[:3]]
    for ann in getattr(pic, "annotations", None) or []:
        if getattr(ann, "kind", "") == "classification":
            return [(p.class_name, round(p.confidence, 3)) for p in ann.predicted_classes[:3]]
    return []


def _ref_texts(doc, refs) -> list[str]:
    out = []
    for r in refs or []:
        try:
            item = r.resolve(doc)
        except Exception:
            continue
        if getattr(item, "text", None):
            out.append(" ".join(item.text.split()))
    return out


def convert(path: Path, doc_id: str, figures_dir: Path) -> dict:
    """Run Docling on one PDF; return {"blocks": [...], "figures": [...], ...} (JSON-ready)."""
    from docling_core.types.doc import PictureItem, TableItem, TextItem

    t0 = time.perf_counter()
    res = _converter().convert(path)
    d = res.document
    heights = {no: p.size.height for no, p in d.pages.items()}
    figures_dir.mkdir(parents=True, exist_ok=True)

    def tl(prov):
        b = prov.bbox.to_top_left_origin(heights[prov.page_no])
        return (round(b.l, 1), round(b.t, 1), round(b.r, 1), round(b.b, 1))

    blocks, figures = [], []
    inside_picture: set[str] = set()
    for pic in d.pictures:
        for item, _ in d.iterate_items(root=pic, with_groups=False):
            if item is not pic:
                inside_picture.add(item.self_ref)

    for item, _ in d.iterate_items(with_groups=False):
        if not item.prov:
            continue
        prov = item.prov[0]
        if isinstance(item, TableItem):
            grid, nh = _table_grid(item)
            if not any(any(c for c in r) for r in grid):
                continue
            blocks.append(Block(prov.page_no, "table", rows=grid, bbox=tl(prov), header_rows=nh,
                                caption=item.caption_text(d) or None,
                                footnotes=_ref_texts(d, item.footnotes) or None, extraction="tableformer"))
        elif isinstance(item, PictureItem):
            n = sum(1 for f in figures if f["page"] == prov.page_no)
            fid = f"{doc_id}:p{prov.page_no}:f{n}"
            img = item.get_image(d)
            crop = None
            if img is not None:
                crop = figures_dir / f"p{prov.page_no:03d}_f{n}.png"
                img.save(crop)
            ocr = [" ".join(t.text.split()) for t, _ in d.iterate_items(root=item, with_groups=False)
                   if t is not item and isinstance(t, TextItem) and t.text.strip()]
            figures.append({"figure_id": fid, "page": prov.page_no, "bbox": tl(prov), "source": "docling",
                            "classes": _classes(item), "caption": item.caption_text(d) or None,
                            "ocr_text": ocr, "crop": str(crop.relative_to(PROJECT_ROOT)) if crop else None,
                            "size_px": list(img.size) if img is not None else None})
            blocks.append(Block(prov.page_no, "figure", bbox=tl(prov), figure_id=fid,
                                caption=item.caption_text(d) or None, extraction="pending"))
        elif isinstance(item, TextItem):
            if item.self_ref in inside_picture or str(item.label) in SKIP_LABELS:
                continue
            text = (item.text or "").strip()
            if not text:
                continue
            # docling merges the PDF text layer with OCR of bitmap regions; it doesn't say which
            blocks.append(Block(prov.page_no, "text", text=text, bbox=tl(prov), label=str(item.label),
                                extraction="docling_text"))

    figures += _missed_images(path, doc_id, figures, figures_dir)
    for f in figures:
        if f["source"] == "pdf_image" and f.get("frac", 0) >= MIN_IMAGE_FRAC:
            blocks.append(Block(f["page"], "figure", bbox=tuple(f["bbox"]), figure_id=f["figure_id"],
                                extraction="pending"))
    blocks.sort(key=lambda b: (b.page, b.bbox[1] if b.bbox else 0, b.bbox[0] if b.bbox else 0))
    return {"blocks": [asdict(b) for b in blocks], "figures": figures,
            "seconds": round(time.perf_counter() - t0, 1), "pages": len(d.pages)}


def _missed_images(path: Path, doc_id: str, figures: list[dict], figures_dir: Path) -> list[dict]:
    """Embedded images Docling didn't report as pictures: every one is inventoried; those above
    MIN_IMAGE_FRAC of the page get a crop and become figure blocks (classified later)."""
    out = []
    with pymupdf.open(path) as pdf:
        for i, page in enumerate(pdf):
            pno = i + 1
            area = page.rect.width * page.rect.height
            known = [f["bbox"] for f in figures if f["page"] == pno]
            n = sum(1 for f in figures if f["page"] == pno)
            for b in page.get_text("dict")["blocks"]:
                if b["type"] != 1:
                    continue
                bb = tuple(round(x, 1) for x in b["bbox"])
                if any(_overlap(bb, k) > COVER_OVERLAP for k in known):
                    continue
                frac = (bb[2] - bb[0]) * (bb[3] - bb[1]) / area
                fid = f"{doc_id}:p{pno}:f{n}"
                rec = {"figure_id": fid, "page": pno, "bbox": bb, "source": "pdf_image", "classes": [],
                       "caption": None, "ocr_text": [], "crop": None, "frac": round(frac, 4),
                       "size_px": [b.get("width"), b.get("height")]}
                if frac >= MIN_IMAGE_FRAC:
                    crop = figures_dir / f"p{pno:03d}_f{n}.png"
                    page.get_pixmap(clip=pymupdf.Rect(bb), dpi=72 * IMAGES_SCALE).save(crop)
                    rec["crop"] = str(crop.relative_to(PROJECT_ROOT))
                    # the PDF's own text inside the image box (usually none for a raster figure)
                    inner = " ".join(page.get_textbox(pymupdf.Rect(bb)).split())
                    rec["ocr_text"] = [inner] if inner else []
                out.append(rec)
                known.append(bb)
                n += 1
    return out


def cache_dir() -> Path:
    return PROJECT_ROOT / "storage" / "parse_cache"


def figures_root() -> Path:
    return PROJECT_ROOT / "storage" / "figures"


def parse_cached(path: Path, doc_id: str, log=print) -> dict:
    """The cached Docling result for this exact file and configuration, converting on a miss."""
    src, opts = cache_key(path)
    f = cache_dir() / doc_id / f"{src[:16]}-{opts}.json"
    if f.exists():
        return json.loads(f.read_text())
    log(f"  docling: converting {path.name} (cache miss {f.name})")
    out = convert(path, doc_id, figures_root() / doc_id)
    out.update({"doc_id": doc_id, "source_sha256": src, "options": _options_key()})
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(out))
    return out


class DoclingParser(Parser):
    name = "docling"

    def __init__(self, doc_id: str | None = None):
        self.doc_id = doc_id
        self.last: dict | None = None  # the full cached result (figures, hash) of the latest parse

    def parse(self, path: Path, pages: Iterable[int] | None = None) -> list[Block]:
        path = Path(path)
        result = parse_cached(path, self.doc_id or path.stem)
        self.last = result
        blocks = [Block(**{**b, "bbox": tuple(b["bbox"]) if b["bbox"] else None}) for b in result["blocks"]]
        if pages is not None:
            wanted = set(pages)
            blocks = [b for b in blocks if b.page in wanted]
        return blocks
