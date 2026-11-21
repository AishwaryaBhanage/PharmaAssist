"""Build one document version: source bytes -> Docling blocks -> figures -> chunks -> embeddings ->
the store, verified and activated. The worker (worker.py) calls `build_version` once per job.

The stages mirror document_versions.status (parsing -> extracting_figures -> chunking -> embedding
-> verifying -> active) so admins see where a build is. The v1 pieces are reused unchanged: the
Docling parser and its cache key, the figure decisions/vision/checks, the section chunker (with the
docling_sections setup's sizes, counted with bge-small's tokenizer, so chunk ids and boundaries are
identical to the v1 index), the drug-table extractors and the OpenAI embedder.

Ids are deterministic (chunk `<doc_id>:s<n>:c<m>`, parent `<doc_id>:s<n>`, figure
`<doc_id>:p<page>:f<k>`), keyed with the version id in the store, so a re-run overwrites its own
rows and never touches another version's. Figure crops live under PROJECT_ROOT/storage/figures/
<doc_id>/<version_id>/ because the figure helpers address crops relative to the project root.

Errors: `PermanentError` means retrying won't help (hash mismatch, unparseable file, nothing to
index, the vision spend cap); `TransientError` (from the embedder) means try again later. Anything
else (store failures) is left to the worker, which treats it as transient.
"""

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from pharmassist import cloud
from pharmassist.config import PROJECT_ROOT
from pharmassist.embedders.base import TransientError
from pharmassist.parsers import docling_parser
from pharmassist.parsers import figures as F
from pharmassist.store.protocols import (ChunkRecord, Document, DocumentVersion, FigureRecord, ParentRecord,
                                         TableRowRecord)

log_default = logging.getLogger("pharmassist.ingest")

PDF = "application/pdf"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
STAGES = ("parsing", "extracting_figures", "chunking", "embedding", "verifying")
CHUNKER_VERSION = "docling_sections-v1"     # bump when chunk boundaries or ids change
EST_IN, EST_OUT = 2500, 4000               # vision tokens per figure, for the spend-cap estimate
TRANSIENT_NAMES = {"RateLimitError", "APITimeoutError", "APIConnectionError", "InternalServerError",
                   "ServiceUnavailableError", "TimeoutError", "ConnectionError"}


class PermanentError(Exception):
    """Retrying won't help: the version fails with this message as its readable error."""


@dataclass
class Tools:
    """The replaceable pieces (tests pass fakes; production uses the defaults)."""
    parse_fn: Callable = None          # (path, doc_id, figures_dir) -> docling_parser.convert's dict
    vision_fn: Callable = None         # (fig, entry) -> {"record", "usage", "model", "cached"}
    ocr_fn: Callable = None            # (crop_path) -> list[str]
    token_spans: Callable = None       # text -> [(start, end)] in the chunker's tokenizer
    sleep: Callable = time.sleep
    extra: dict = field(default_factory=dict)

    def __post_init__(self):
        self.parse_fn = self.parse_fn or docling_parser.convert
        self.vision_fn = self.vision_fn or F.extract
        self.ocr_fn = self.ocr_fn or F.ocr_crop
        self.token_spans = self.token_spans or bge_token_spans()


def bge_token_spans() -> Callable:
    """Offsets from BAAI/bge-small-en-v1.5's tokenizer (the one v1 chunked with), loaded lazily and
    without the model weights."""
    tok = None

    def spans(text: str):
        nonlocal tok
        if tok is None:
            from transformers import AutoTokenizer
            tok = AutoTokenizer.from_pretrained("BAAI/bge-small-en-v1.5")
        enc = tok(text, add_special_tokens=False, return_offsets_mapping=True, verbose=False)
        return [tuple(s) for s in enc["offset_mapping"]]
    return spans


def default_embed_fn(cfg: dict) -> Callable:
    """OpenAI text-embedding-3-large through the v1 embedder (bounded retries, dimension enforced).
    The deployed worker swaps in stream B's router; both are `embed(texts) -> list[list[float]]`."""
    from pharmassist.embedders.openai_large import OpenAIEmbedder
    e = cfg["llm"]["embedding"]
    emb = OpenAIEmbedder(e["model"], dimension=e["dimension"], timeout_s=e.get("timeout_s", 60),
                         batch_size=e.get("batch_size", 128))

    def embed(texts):
        return emb.embed_documents(list(texts)).tolist() if texts else []
    embed.model_name = e["model"]
    return embed


def chunker_sizes(cfg: dict) -> dict:
    """child/overlap/parent token sizes of the docling_sections setup (following chunks_from)."""
    setups, name = cfg["setups"], "docling_sections"
    while "chunker" not in setups[name]:
        name = setups[name].get("chunks_from") or setups[name]["index"]
    sizes = dict(setups[name]["chunker"])
    sizes.pop("name", None)
    return sizes


def parser_version() -> str:
    try:
        import importlib.metadata as m
        return f"docling-{m.version('docling')}/opts-{docling_parser.PARSER_VERSION}"
    except Exception:
        return f"docling/opts-{docling_parser.PARSER_VERSION}"


def figures_dir(doc_id: str, version_id: str) -> Path:
    return PROJECT_ROOT / "storage" / "figures" / doc_id / version_id


def _entry(document: Document, path: Path) -> dict:
    """The catalog-shaped record the v1 chunker and figure code read. `file` is the absolute path of
    the downloaded copy: docs_dir() / <absolute> resolves to it, so nothing reads docs/."""
    return {"id": document.id, "file": str(path), "title": document.title, "program": document.program,
            "doc_type": document.doc_type, "authority": document.authority, "date": document.doc_date}


# ---------------------------------------------------------------- stages

def _download(storage, version: DocumentVersion, work_dir: Path) -> Path:
    try:
        data = storage.get_bytes(version.s3_key)
    except KeyError:
        raise PermanentError(f"source object {version.s3_key} is missing from storage") from None
    except Exception as e:
        raise TransientError(f"storage read failed: {type(e).__name__}") from None
    if cloud.sha256_bytes(data) != version.sha256:
        raise PermanentError("the stored file's SHA-256 doesn't match the version (corrupt upload?)")
    path = Path(work_dir) / version.file_name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _restore_crops(result: dict, storage, doc_id: str, version_id: str) -> bool:
    """A cached parse references crops on disk; fetch missing ones from storage. False when a crop a
    vision figure needs is gone, which forces a fresh conversion."""
    for fig in result.get("figures", []):
        if not fig.get("crop"):
            continue
        local = PROJECT_ROOT / fig["crop"]
        if local.exists():
            continue
        try:
            storage.get_file(cloud.figure_key(doc_id, Path(fig["crop"]).name, version_id), local)
        except KeyError:
            if F.decide(fig) == "vision":
                return False
    return True


def _parse(path: Path, document: Document, version: DocumentVersion, storage, tools: Tools, log) -> dict:
    """Docling blocks and the figure inventory, from the local or storage cache when this exact file
    was converted before with the same options."""
    src, opts = docling_parser.cache_key(path)
    local = docling_parser.cache_dir() / document.id / f"{src[:16]}-{opts}.json"
    s3key = cloud.parse_cache_key(document.id, version.id, opts)
    result, origin = None, None
    if local.exists():
        result, origin = json.loads(local.read_text()), "local cache"
    elif storage.exists(s3key):
        result, origin = json.loads(storage.get_bytes(s3key)), "storage cache"
    if result is not None and not _restore_crops(result, storage, document.id, version.id):
        result, origin = None, None
    if result is None:
        t0 = time.perf_counter()
        try:
            result = tools.parse_fn(path, document.id, figures_dir(document.id, version.id))
        except TransientError:
            raise
        except Exception as e:
            raise PermanentError(f"parse failed: {type(e).__name__}: {str(e)[:200]}") from None
        result.update({"doc_id": document.id, "source_sha256": src, "options": docling_parser._options_key()})
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_text(json.dumps(result))
        storage.put_bytes(s3key, json.dumps(result).encode(), "application/json")
        origin = f"converted in {time.perf_counter() - t0:.0f}s"
    log(f"parsed: {len(result['blocks'])} blocks, {len(result.get('figures', []))} images, "
        f"{result.get('pages')} pages ({origin})")
    return result


def _is_transient(e: Exception) -> bool:
    return isinstance(e, TransientError) or type(e).__name__ in TRANSIENT_NAMES


def _figures(parsed: dict, path: Path, document: Document, version: DocumentVersion, cfg: dict, storage,
             tools: Tools, log) -> tuple[dict, list[FigureRecord], dict]:
    """Every image gets a decision; the non-decorative ones are interpreted by the vision model
    (cached by crop hash), checked, and become FigureRecords with their crop in storage. Returns the
    chunker's records dict, the rows, and the inventory counts."""
    fcfg = cfg["figures"]
    price = fcfg["prices_per_mtok"]
    per_fig = (EST_IN * price["input"] + EST_OUT * price["output"]) / 1e6
    entry = _entry(document, path)
    todo, counts = [], {"images": 0, "decorative": 0, "vision": 0, "indexed": 0, "cached": 0}
    for fig in parsed.get("figures", []):
        counts["images"] += 1
        if F.expand_to_image(fig, path):
            log(f"figure {fig['figure_id']}: crop expanded to the full embedded image")
        if F.decide(fig) == "vision":
            todo.append(fig)
        else:
            counts["decorative"] += 1
    uncached = [f for f in todo if not F._cache_path(PROJECT_ROOT / f["crop"], fcfg["model"]).exists()]
    est = len(uncached) * per_fig
    if est > fcfg["max_spend_usd"]:
        raise PermanentError(f"{len(uncached)} figures need vision calls (est. ${est:.2f}), over figures.max_spend_usd "
                             f"${fcfg['max_spend_usd']}; raise the cap and retry")
    records, rows, spent = {}, [], 0.0
    for fig in todo:
        counts["vision"] += 1
        if spent + per_fig > fcfg["max_spend_usd"]:
            raise PermanentError(f"vision spend ${spent:.2f} would pass figures.max_spend_usd ${fcfg['max_spend_usd']}")
        try:
            res = tools.vision_fn(fig, entry)
        except Exception as e:
            if _is_transient(e):
                raise TransientError(f"vision call failed: {type(e).__name__}") from None
            raise PermanentError(f"vision call failed for {fig['figure_id']}: {type(e).__name__}") from None
        u = res.get("usage") or {}
        cost = (u.get("input_tokens", 0) * price["input"] + u.get("output_tokens", 0) * price["output"]) / 1e6
        if res.get("cached"):
            counts["cached"] += 1
        else:
            spent += cost
        rec = dict(res["record"])
        ocr = fig.get("ocr_text") or []
        if not ocr and rec.get("kind") != "decorative":
            ocr = tools.ocr_fn(PROJECT_ROOT / fig["crop"])   # independent OCR of the crop for the checks
        title_ok = F.title_supported(rec.get("title") or "", ocr, fig.get("caption"))
        if not title_ok:   # a title the image doesn't show was supplied by the model: don't index it
            rec["title"] = fig.get("caption") or ""
        chk = F.check(rec, ocr)
        status = F.status_for(fig["figure_id"], chk)
        if rec.get("kind") == "decorative":
            counts["decorative"] += 1
            continue
        counts["indexed"] += 1
        crop = PROJECT_ROOT / fig["crop"]
        crop_key = cloud.figure_key(document.id, crop.name, version.id)
        storage.put_bytes(crop_key, crop.read_bytes(), "image/png")
        records[fig["figure_id"]] = {"record": rec, "status": status, "page": fig["page"], "bbox": fig["bbox"],
                                     "crop": fig["crop"], "doc_id": document.id, "model": res.get("model"),
                                     "checks": chk}
        rows.append(FigureRecord(
            version_id=version.id, figure_id=fig["figure_id"], document_id=document.id, page=fig["page"],
            kind=rec.get("kind") or "figure", status=status, title=rec.get("title") or None, crop_s3_key=crop_key,
            record={"record": rec, "checks": chk, "bbox": fig["bbox"], "source": fig.get("source"),
                    "classes": fig.get("classes"), "caption": fig.get("caption"), "ocr_text": ocr,
                    "title_in_image": title_ok, "model": res.get("model"), "vision_cost_usd": round(cost, 4)}))
    counts["spent_usd"] = round(spent, 4)
    log(f"figures: {counts}")
    return records, rows, counts


def _chunk(parsed: dict, path: Path, document: Document, version: DocumentVersion, records: dict, cfg: dict,
           tools: Tools) -> tuple[list[ChunkRecord], list[ParentRecord]]:
    from pharmassist.chunkers.docling_sections import DoclingSectionChunker
    from pharmassist.parsers.base import Block

    class VersionChunker(DoclingSectionChunker):
        """The v1 chunker over this version's figure records and downloaded file (the NY PDL's
        class pages are extracted from the file the tree is given, not from docs/)."""

        def tree(self, blocks, entry, path=None):
            return super().tree(blocks, entry, path or self.path)

    chunker = VersionChunker(tools.token_spans, **chunker_sizes(cfg))
    chunker.records, chunker.path, chunker.source_sha256 = records, path, version.sha256
    blocks = [Block(**{**b, "bbox": tuple(b["bbox"]) if b.get("bbox") else None}) for b in parsed["blocks"]]
    try:
        chunks = chunker.chunk(blocks, _entry(document, path))
    except Exception as e:
        raise PermanentError(f"chunking failed: {type(e).__name__}: {str(e)[:200]}") from None
    parents = [ParentRecord(version_id=version.id, parent_id=p.parent_id, document_id=document.id, text=p.text,
                            page_start=p.pages[0] if p.pages else None, page_end=p.pages[-1] if p.pages else None,
                            section_path=list(p.path)) for p in chunker.parents]
    rows = []
    for c in chunks:
        pages = c.pages or [c.page]
        rows.append(ChunkRecord(
            version_id=version.id, chunk_id=c.chunk_id, document_id=document.id, text=c.text, search_text=c.text,
            program=document.program, authority=document.authority, doc_date=document.doc_date,
            parent_id=c.parent_id, page_start=pages[0], page_end=pages[-1],
            section_path=[s for s in (c.section or "").split(" > ") if s],
            content_types=list(c.content_types), extraction=",".join(c.extraction) or None,
            figure_ids=list(c.figure_ids), verification=c.verification,
            metadata={"doc_type": c.doc_type, "pages": pages, "printed_pages": c.printed_pages,
                      "bboxes": c.bboxes, "source_sha256": c.source_sha256, "extraction": list(c.extraction)}))
    return rows, parents


def _table_rows(path: Path, document: Document, version: DocumentVersion) -> list[TableRowRecord]:
    """Structured drug rows for the two documents that have them, decided as v1 did: the VA formulary
    spreadsheet (any XLSX) and the NY Medicaid PDL (by document id). Row shapes are the contract
    stream B's lookups rebuild the tables from:
      va_formulary  {"sheet", "row", "cells": [7 strings, columns A:G], "drug": the Generic cell,
                     "header_row": bool} — one per spreadsheet row, notes and header included
      ny_pdl        dataclasses.asdict(ny_pdl.Row) + {"row", "drug": drug_name}"""
    from pharmassist.tables import ny_pdl, va_formulary
    rows = []
    try:
        if version.content_type == XLSX:
            raw = va_formulary._read_sheet(path)
            cells_of = {int(i): [str(v).strip() for v in r.tolist()] for i, r in raw.iterrows()}
            header_row = next((i for i, c in cells_of.items() if c == va_formulary.HEADER), None)
            if header_row is None:
                raise PermanentError("the spreadsheet has no VA formulary header row "
                                     f"({' | '.join(va_formulary.HEADER)})")
            for i, cells in cells_of.items():
                cells = (cells + [""] * 7)[:7]
                rows.append(TableRowRecord(version.id, "va_formulary", i,
                                           {"sheet": va_formulary.SHEET, "row": i, "cells": cells,
                                            "drug": cells[2] if i > header_row else "", "header_row": i == header_row}))
        elif document.id == ny_pdl.DOC_ID:
            for n, r in enumerate(ny_pdl.extract(path=path), 1):
                rows.append(TableRowRecord(version.id, "ny_pdl", n, {**asdict(r), "row": n, "drug": r.drug_name}))
    except PermanentError:
        raise
    except Exception as e:
        raise PermanentError(f"drug table extraction failed: {type(e).__name__}: {str(e)[:200]}") from None
    return rows


def embed_all(texts: list[str], embed_fn, cfg: dict, tools: Tools, log) -> list[list[float]]:
    """Embeddings in batches; a transient failure of one batch is retried with backoff a few times
    before the whole build is handed back to the queue. The dimension is enforced on every batch."""
    e = cfg["llm"]["embedding"]
    batch, dim, retries = e.get("batch_size", 128), e["dimension"], e.get("max_retries", 3)
    out: list[list[float]] = []
    for i in range(0, len(texts), batch):
        for attempt in range(retries + 1):
            try:
                vecs = embed_fn(texts[i:i + batch])
                break
            except Exception as ex:
                if not _is_transient(ex) or attempt == retries:
                    if _is_transient(ex):
                        raise TransientError(f"embedding failed after {attempt + 1} attempts: {type(ex).__name__}") from None
                    raise
                tools.sleep(min(2.0 ** attempt, 30.0))
        vecs = [list(map(float, v)) for v in vecs]
        if len(vecs) != len(texts[i:i + batch]) or any(len(v) != dim for v in vecs):
            raise PermanentError(f"embedding returned {len(vecs)} vectors of dimension "
                                 f"{len(vecs[0]) if vecs else 0}; expected {len(texts[i:i + batch])} x {dim}")
        out += vecs
    if texts:
        log(f"embedded {len(texts)} chunks in {(len(texts) + batch - 1) // batch} batches")
    return out


# ---------------------------------------------------------------- the build

def build_version(store, version: DocumentVersion, *, work_dir, embed_fn, cfg: dict, log=None, progress=None,
                  storage=None, tools: Tools | None = None) -> dict:
    """Build `version` end to end and activate it. Returns the build's counts and timings.

    `log(message)` receives progress lines (ids and counts, never text); `progress(stage)` is called
    as each stage starts (the worker mirrors it on the job). Raises PermanentError or TransientError;
    store errors propagate."""
    log = log or (lambda m: log_default.info("version %s: %s", version.id, m))
    progress = progress or (lambda stage: None)
    tools = tools or Tools()
    if storage is None:
        from pharmassist.ingest.storage import storage_from_config
        storage = storage_from_config(cfg)
    document = store.documents.get_document(version.document_id)
    if document is None:
        raise PermanentError(f"document {version.document_id} no longer exists")
    if version.content_type not in (PDF, XLSX):
        raise PermanentError(f"unsupported content type {version.content_type!r}")
    work_dir = Path(work_dir)
    timings, t_all = {}, time.perf_counter()

    def stage(name: str):
        store.documents.set_version_status(version.id, name)
        progress(name)
        timings[name] = time.perf_counter()

    stage("parsing")
    path = _download(storage, version, work_dir)
    store.content.delete_version_content(version.id)   # a previous attempt's rows, if any
    parsed, pages = {"blocks": [], "figures": []}, version.pages
    if version.content_type == PDF:
        parsed = _parse(path, document, version, storage, tools, log)
        pages = parsed.get("pages") or pages

    stage("extracting_figures")
    records, figure_rows, fig_counts = {}, [], {"images": 0, "indexed": 0}
    if version.content_type == PDF:
        records, figure_rows, fig_counts = _figures(parsed, path, document, version, cfg, storage, tools, log)

    stage("chunking")
    chunks, parents = ([], [])
    if version.content_type == PDF:
        chunks, parents = _chunk(parsed, path, document, version, records, cfg, tools)
    table_rows = _table_rows(path, document, version)
    if version.content_type == PDF and not chunks:
        raise PermanentError("no text could be extracted from the PDF (scanned without OCR text, or empty)")
    log(f"chunked: {len(parents)} parents, {len(chunks)} chunks, {len(table_rows)} table rows")

    stage("embedding")
    vectors = embed_all([c.search_text for c in chunks], embed_fn, cfg, tools, log)
    for c, v in zip(chunks, vectors):
        c.embedding = v
    store.content.put_parents(parents)
    store.content.put_chunks(chunks)
    store.content.put_figures(figure_rows)
    store.content.put_table_rows(table_rows)

    e = cfg["llm"]["embedding"]
    store.documents.set_version_status(
        version.id, "verifying", pages=pages, parser_version=parser_version() if chunks else None,
        chunker_version=CHUNKER_VERSION if chunks else None,
        embedder_model=getattr(embed_fn, "model_name", e["model"]) if chunks else None,
        embedding_dim=e["dimension"] if chunks else None, chunk_count=len(chunks), figure_count=len(figure_rows))
    progress("verifying")
    timings["verifying"] = time.perf_counter()
    expected = {"chunks": len(chunks), "parents": len(parents), "figures": len(figure_rows), "table_rows": len(table_rows)}
    counts = store.content.counts(version.id)
    if {k: counts.get(k, 0) for k in expected} != expected:
        raise TransientError(f"stored counts {counts} differ from what was built {expected}")
    generation = store.documents.activate(version.id)

    marks = list(timings.items()) + [("done", time.perf_counter())]
    stage_s = {a: round(tb - ta, 1) for (a, ta), (_, tb) in zip(marks, marks[1:])}
    stats = {**expected, "pages": pages, "figures_inventory": fig_counts, "generation": generation,
             "stage_s": stage_s, "total_s": round(time.perf_counter() - t_all, 1)}
    log(f"activated: generation {generation}, {stats['total_s']}s {stage_s}")
    return stats
