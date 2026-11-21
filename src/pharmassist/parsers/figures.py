"""Figure inventory decisions and targeted vision extraction.

Every image the parser found gets exactly one decision, recorded in reports/parsing/FIGURES.json:

- decorative  Docling classified it as a logo/icon/signature/..., or it covers under MIN_IMAGE_FRAC
              of the page. Inventoried, not indexed.
- vision      Everything else (flowcharts, charts, unclassified raster images) is sent once to a
              Claude vision model, which returns a typed record: a flowchart as numbered nodes and
              directed, labelled edges; a chart as its data points; a table image as rows; or
              "decorative" with a reason. Unreadable or ambiguous parts are listed, never guessed.

Docling's OCR alone is not enough for a flowchart: it returns the box texts as an unordered bag with
no arrows, branch labels or outcomes.

Checks on every vision record (deterministic, no model):
- structure: edges point at known nodes; a decision has at least two labelled exits.
- OCR cross-check: each node's content words are looked up in independent OCR text of the same
  crop (Docling's OCR). A node whose words mostly aren't there is flagged as possibly invented.

Verification status (shown with every figure chunk and in the app):
  machine_interpreted   vision output, checks not passed or not run
  ocr_checked           vision output, structure and OCR cross-check passed
  reviewed              compared box by box against the page image (docs/figure_reviews.yaml says
                        by whom and what was checked)

Vision results are cached by crop hash + model + prompt version: storage/figure_cache/.
"""

import base64
import hashlib
import json
import re
from pathlib import Path

import yaml

from pharmassist.config import PROJECT_ROOT, load_config

PROMPT_VERSION = 2
DECORATIVE_CLASSES = {"logo", "icon", "signature", "stamp", "qr_code", "bar_code", "picture_group"}
MIN_IMAGE_FRAC = 0.02
OCR_MATCH = 0.6            # a node passes when this share of its content words is in the OCR text
STATUS_TEXT = {
    "machine_interpreted": "machine-interpreted from the page image by a vision model; not verified",
    "ocr_checked": "machine-interpreted from the page image by a vision model; structure and OCR cross-check passed",
    "reviewed": "machine-interpreted from the page image by a vision model; compared box by box against the page image (not clinician-verified)",
}

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


_CLIENT = None


def _client():
    global _CLIENT
    if _CLIENT is None:
        from pharmassist.agent.loop import make_client  # same key and workspace handling as the agent
        _CLIENT = make_client()
    return _CLIENT


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


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9][a-z0-9\-]{3,}", s.lower())}


def ocr_crop(crop: Path) -> list[str]:
    """Independent OCR of a figure crop with Docling's OCR stack (used when Docling missed the figure)."""
    from docling.datamodel.base_models import InputFormat
    from docling.document_converter import DocumentConverter
    doc = DocumentConverter(allowed_formats=[InputFormat.IMAGE]).convert(crop).document
    return [" ".join(t.text.split()) for t in doc.texts if t.text.strip()]


def expand_to_image(fig: dict, pdf_path: Path) -> bool:
    """Docling sometimes crops a raster flowchart short (opioids p26: it starts at box 20 and reads
    boxes 18-19 as loose text). If the picture lies inside a larger embedded image, crop the whole
    image instead. Returns whether the figure's bbox and crop changed."""
    import pymupdf
    top = fig["classes"][0][0] if fig.get("classes") else None
    if fig["source"] != "docling" or not fig.get("crop") or top != "flow_chart":
        return False
    fb = fig["bbox"]
    farea = (fb[2] - fb[0]) * (fb[3] - fb[1])
    with pymupdf.open(pdf_path) as pdf:
        page = pdf[fig["page"] - 1]
        for b in page.get_text("dict")["blocks"]:
            if b["type"] != 1:
                continue
            ib = b["bbox"]
            w = min(fb[2], ib[2]) - max(fb[0], ib[0])
            h = min(fb[3], ib[3]) - max(fb[1], ib[1])
            iarea = (ib[2] - ib[0]) * (ib[3] - ib[1])
            if w > 0 and h > 0 and w * h >= 0.9 * farea and iarea >= 1.15 * farea:
                page.get_pixmap(clip=pymupdf.Rect(ib), dpi=144).save(PROJECT_ROOT / fig["crop"])
                fig["bbox"] = [round(x, 1) for x in ib]
                fig["bbox_source"] = "pdf_image_block (docling crop was partial)"
                return True
    return False


def decide(fig: dict) -> str:
    """decorative | vision"""
    top = fig["classes"][0][0] if fig.get("classes") else None
    if top in DECORATIVE_CLASSES:
        return "decorative"
    if fig["source"] == "pdf_image" and fig.get("frac", 1) < MIN_IMAGE_FRAC:
        return "decorative"
    if not fig.get("crop"):
        return "decorative"
    return "vision"


def _cache_path(crop: Path, model: str) -> Path:
    h = hashlib.sha256(crop.read_bytes() + f"|{model}|{PROMPT_VERSION}".encode()).hexdigest()
    return PROJECT_ROOT / "storage" / "figure_cache" / f"{h[:24]}.json"


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


def _phrase(s: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", s.lower()))


def title_supported(title: str, ocr: list[str], caption: str | None = None) -> bool:
    """Whether a model-given title is printed as a phrase in the image (OCR) or in the parser's caption.
    Shared words aren't enough: an invented title reuses the figure's own vocabulary."""
    t = _phrase(title)
    return bool(t) and (t in _phrase(" ".join(ocr)) or t in _phrase(caption or ""))


def check(record: dict, ocr: list[str]) -> dict:
    """Structure and OCR cross-check of a vision record. Returns {"passed", "problems", "ocr_match"}."""
    problems = []
    if record.get("kind") == "flowchart":
        nodes = {n["id"]: n for n in record.get("nodes", [])}
        edges = record.get("edges", [])
        for e in edges:
            for end in ("from", "to"):
                if e.get(end) not in nodes:
                    problems.append(f"edge {e.get('from')}->{e.get('to')} names unknown node {e.get(end)!r}")
        out = {i: [e for e in edges if e.get("from") == i] for i in nodes}
        for i, n in nodes.items():
            if n["shape"] == "decision" and (len(out[i]) < 2 or not all((e.get("label") or "").strip() for e in out[i])):
                problems.append(f"decision {i} has {len(out[i])} exits, not all labelled")
            if n["shape"] == "decision" and not out[i]:
                problems.append(f"decision {i} has no exit")
            # an action box with no exit is a terminal outcome in these guidelines (e.g. "refer for acute care")
    match = None
    if ocr and record.get("kind") == "flowchart":
        bag = _words(" ".join(ocr))
        fails, scores = [], []
        for n in record.get("nodes", []):
            w = _words(n["text"])
            if w:
                s = len(w & bag) / len(w)
                scores.append(s)
                if s < OCR_MATCH:
                    fails.append(f"node {n['id']} text only {s:.0%} found in OCR")
        problems += fails
        match = round(sum(scores) / len(scores), 3) if scores else None
    elif record.get("kind") == "flowchart":
        problems.append("no OCR text to cross-check against")
    return {"passed": not problems, "problems": problems, "ocr_match": match}


def reviews() -> dict:
    f = PROJECT_ROOT / "docs" / "figure_reviews.yaml"
    return (yaml.safe_load(f.read_text()) or {}).get("figures", {}) if f.exists() else {}


def status_for(figure_id: str, chk: dict) -> str:
    r = reviews().get(figure_id)
    if r and r.get("result") == "matches":
        return "reviewed"
    return "ocr_checked" if chk.get("passed") else "machine_interpreted"


# ---- rendering a record as indexable text ----

def _paths(record: dict, limit: int = 40) -> list[list[tuple[str, str]]]:
    """Start-to-end paths as [(node, label-of-edge-taken-into-it)], cycles cut."""
    nodes = [n["id"] for n in record.get("nodes", [])]
    edges = record.get("edges", [])
    has_in = {e["to"] for e in edges}
    starts = [n for n in nodes if n not in has_in] or nodes[:1]
    out = []

    def walk(n, path):
        if len(out) >= limit:
            return
        seen = {p for p, _ in path}
        exits = [e for e in edges if e["from"] == n]
        if not exits:
            out.append(path)
            return
        for e in exits:
            step = (e["to"], (e.get("label") or "").strip())
            if e["to"] in seen:   # a loop: end the path, saying where it returns
                out.append(path + [(f"back to box {e['to']}", step[1])])
            else:
                walk(e["to"], path + [step])

    for s in starts:
        walk(s, [(s, "")])
    return out


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
