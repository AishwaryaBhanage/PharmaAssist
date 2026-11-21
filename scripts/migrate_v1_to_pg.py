"""One-off loader: the v1 build into PostgreSQL (v2). No embedding or vision spend.

Reads, under --source-root (default: the main checkout, which holds the real data):
    docs/catalog.yaml                       the documents and their source files (sha256 → version id)
    index/docling_sections/chunks.jsonl     child chunks (row i of vectors.npy is chunk i; dimension 3072)
    index/docling_sections/parents.jsonl    parent sections
    index/docling_sections/manifest.json    embedder model and dimension
    index/tables/va_formulary_cells.json    VA National Formulary cells  → table_rows(va_formulary) of va_national_formulary_2026_09
    index/tables/ny_pdl_rows.jsonl          NYRx PDL drug rows           → table_rows(ny_pdl) of ny_medicaid_pdl
    storage/figures/records.json            figure vision records (crops under storage/figures/<doc_id>/)

For each catalog document: upsert `documents`, create a `document_versions` row (id = sha256[:16],
s3_key = sources/<doc_id>/<sha16>/<file>), write parents, chunks with their existing vectors, figures
and table rows, set the counts, then `activate` (queued → parsing → chunking → extracting_figures →
verifying → active). Idempotent: a version that is already active is skipped; a version left half-
loaded by an interrupted run is cleared and reloaded.

Nothing is uploaded to S3: the source files and figure crops are already there under exactly these
keys (sources/<doc_id>/<sha16>/<file>, figures/<doc_id>/<name>) from the v1 ingestion.

Run (from the repository root, DATABASE_URL set or --dsn given):
    PYTHONPATH=src python scripts/migrate_v1_to_pg.py --dry-run
    PYTHONPATH=src python scripts/migrate_v1_to_pg.py --dsn postgresql:///pharmassist_dev
"""

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pharmassist.store.protocols import (ChunkRecord, Document, DocumentVersion, FigureRecord, ParentRecord,  # noqa: E402
                                         TableRowRecord)

DEFAULT_ROOT = Path(__file__).resolve().parents[1]
INDEX = "docling_sections"
TABLE_DOCS = {"va_formulary": "va_national_formulary_2026_09", "ny_pdl": "ny_medicaid_pdl"}
CONTENT_TYPES = {".pdf": "application/pdf",
                 ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
VA_HEADER = ["VA Class", "Restriction", "Generic", "Dosage Form", "Comments", "U/E Formulary", "Clinical Guidance"]
EXPECTED_DIM = 3072
BATCH = 500


# ---------------------------------------------------------------- reading the v1 build

def load_build(root: Path) -> dict:
    d = root / "index" / INDEX
    manifest = json.loads((d / "manifest.json").read_text())
    chunks = [json.loads(line) for line in (d / "chunks.jsonl").open()]
    parents = [json.loads(line) for line in (d / "parents.jsonl").open()] if (d / "parents.jsonl").exists() else []
    vectors = np.load(d / "vectors.npy")
    if vectors.shape != (len(chunks), EXPECTED_DIM):
        raise SystemExit(f"vectors.npy is {vectors.shape}; expected ({len(chunks)}, {EXPECTED_DIM}) to match chunks.jsonl")
    if manifest.get("dim") not in (None, EXPECTED_DIM) or manifest.get("n_chunks", len(chunks)) != len(chunks):
        raise SystemExit(f"manifest disagrees with the files: dim {manifest.get('dim')}, n_chunks {manifest.get('n_chunks')}")
    return {"manifest": manifest, "chunks": chunks, "parents": parents, "vectors": vectors}


def load_catalog(root: Path) -> list[dict]:
    return yaml.safe_load((root / "docs" / "catalog.yaml").read_text())["documents"]


def load_figures(root: Path) -> dict:
    f = root / "storage" / "figures" / "records.json"
    return json.loads(f.read_text()) if f.exists() else {}


def _split_section(section) -> list[str]:
    return [s for s in (section or "").split(" > ") if s]


def chunk_record(c: dict, version_id: str, vector) -> ChunkRecord:
    """v1 Chunk fields → columns; whatever has no column goes to `metadata` (search/hybrid.py reads it
    back so results keep v1's keys). `search_text` is the text v1 embedded: the chunk text itself,
    which already starts with the heading path."""
    pages = c.get("pages") or [c["page"]]
    extraction = list(c.get("extraction") or [])
    return ChunkRecord(
        version_id=version_id, chunk_id=c["chunk_id"], document_id=c["doc_id"], text=c["text"], search_text=c["text"],
        program=c["program"], authority=c["authority"], doc_date=str(c["date"]), embedding=vector,
        parent_id=c.get("parent_id"), page_start=min(pages), page_end=max(pages),
        section_path=_split_section(c.get("section")), content_types=list(c.get("content_types") or []),
        extraction=",".join(extraction) or None, figure_ids=list(c.get("figure_ids") or []),
        verification=c.get("verification"),
        metadata={"page": c["page"], "pages": pages, "doc_type": c.get("doc_type", ""),
                  "source_sha256": c.get("source_sha256"), "printed_pages": c.get("printed_pages") or [],
                  "bboxes": c.get("bboxes") or [], "extraction": extraction, "section": c.get("section")})


def parent_record(p: dict, version_id: str) -> ParentRecord:
    pages = p.get("pages") or [p["page"]]
    return ParentRecord(
        version_id=version_id, parent_id=p["parent_id"], document_id=p["doc_id"], text=p["text"],
        page_start=min(pages), page_end=max(pages), section_path=_split_section(p.get("section")),
        metadata={k: p.get(k) for k in ("page", "pages", "program", "doc_type", "authority", "source_sha256",
                                        "printed_pages", "content_types", "extraction", "figure_ids", "verification")
                  if k in p} | {"date": str(p.get("date", "")), "section": p.get("section")})


def figure_records(records: dict, doc_id: str, version_id: str) -> list[FigureRecord]:
    out = []
    for fid, r in sorted(records.items()):
        if r.get("doc_id") != doc_id:
            continue
        rec = r.get("record") or {}
        crop = Path(r["crop"]).name if r.get("crop") else None
        out.append(FigureRecord(version_id=version_id, figure_id=fid, document_id=doc_id, page=int(r["page"]),
                                kind=rec.get("kind") or "unknown", status=r["status"], record=r, title=rec.get("title"),
                                crop_s3_key=f"figures/{doc_id}/{crop}" if crop else None))
    return out


def table_rows(root: Path, table: str, version_id: str) -> list[TableRowRecord]:
    """The drug tables as rows. `row['drug']` is what `ContentRepo.table_rows(drug=...)` filters on:
    the Generic cell (VA) or the printed drug name (PDL)."""
    if table == "va_formulary":
        f = root / "index" / "tables" / "va_formulary_cells.json"
        if not f.exists():
            return []
        data = json.loads(f.read_text())
        rows = {int(k): v for k, v in data["rows"].items()}
        header = next((n for n, cells in rows.items() if [c.strip() for c in cells] == VA_HEADER), None)
        out = []
        for n in sorted(rows):
            cells = rows[n]
            drug = cells[2].strip() if header is not None and n > header and len(cells) > 2 and cells[2].strip() else None
            out.append(TableRowRecord(version_id=version_id, table_name=table, row_no=n,
                                      row={"sheet": data["sheet"], "row": n, "cells": cells, "drug": drug,
                                           "header_row": header}))
        return out
    f = root / "index" / "tables" / "ny_pdl_rows.jsonl"
    if not f.exists():
        return []
    return [TableRowRecord(version_id=version_id, table_name=table, row_no=i,
                           row={**json.loads(line), "row": i, "drug": json.loads(line).get("drug_name")})
            for i, line in enumerate(f.open(), 1)]


def plan(root: Path) -> list[dict]:
    """What would be loaded, per catalog document (also the --dry-run output)."""
    build = load_build(root)
    figures = load_figures(root)
    by_doc = {}
    for i, c in enumerate(build["chunks"]):
        by_doc.setdefault(c["doc_id"], []).append(i)
    parents_by_doc = {}
    for p in build["parents"]:
        parents_by_doc.setdefault(p["doc_id"], []).append(p)
    out = []
    for e in load_catalog(root):
        src = root / "docs" / e["file"]
        if not src.exists():
            raise SystemExit(f"missing source file {src}")
        sha = hashlib.sha256(src.read_bytes()).hexdigest()
        table = next((t for t, d in TABLE_DOCS.items() if d == e["id"]), None)
        out.append({"entry": e, "path": src, "sha256": sha, "version_id": sha[:16],
                    "s3_key": f"sources/{e['id']}/{sha[:16]}/{e['file']}",
                    "content_type": CONTENT_TYPES.get(src.suffix.lower(), "application/octet-stream"),
                    "bytes": src.stat().st_size, "chunk_rows": by_doc.get(e["id"], []),
                    "parents": parents_by_doc.get(e["id"], []),
                    "figures": figure_records(figures, e["id"], sha[:16]),
                    "table": table, "table_rows": table_rows(root, table, sha[:16]) if table else []})
    return out, build


# ---------------------------------------------------------------- loading

def migrate(store, root: Path = DEFAULT_ROOT, *, dry_run: bool = False, log=print) -> dict:
    """Load every catalog document; returns {doc_id: {chunks, parents, figures, table_rows, seconds, status}}."""
    t_all = time.perf_counter()
    items, build = plan(root)
    manifest = build["manifest"]
    report = {}
    for it in items:
        e, vid = it["entry"], it["version_id"]
        counts = {"chunks": len(it["chunk_rows"]), "parents": len(it["parents"]), "figures": len(it["figures"]),
                  "table_rows": len(it["table_rows"])}
        if dry_run:
            log(f"{e['id']:<40} {vid}  " + "  ".join(f"{k} {v:>5}" for k, v in counts.items()))
            report[e["id"]] = {**counts, "status": "dry_run", "seconds": 0.0}
            continue
        t0 = time.perf_counter()
        store.documents.upsert_document(Document(
            id=e["id"], title=e["title"], program=e["program"], doc_type=e.get("doc_type", ""),
            authority=e.get("authority", "advisory"), publisher=e.get("publisher", ""), doc_date=str(e.get("date", "unknown")),
            source_url=e.get("source_url")))
        existing = store.documents.version_by_sha(e["id"], it["sha256"])
        if existing and existing.status == "active":
            log(f"{e['id']:<40} {vid}  already active, skipped")
            report[e["id"]] = {**store.content.counts(vid), "status": "skipped", "seconds": 0.0}
            continue
        if existing:   # an interrupted run: reload from scratch
            store.content.delete_version_content(vid)
            store.documents.set_version_status(vid, "queued")
        else:
            store.documents.create_version(DocumentVersion(
                id=vid, document_id=e["id"], sha256=it["sha256"], s3_key=it["s3_key"], file_name=e["file"],
                content_type=it["content_type"], bytes=it["bytes"], pages=e.get("pages"), status="queued"))
        store.documents.set_version_status(vid, "parsing", pages=e.get("pages"), parser_version="docling",
                                           chunker_version=INDEX, embedder_model=manifest.get("model"),
                                           embedding_dim=manifest.get("dim", EXPECTED_DIM))
        store.documents.set_version_status(vid, "chunking")
        store.content.put_parents([parent_record(p, vid) for p in it["parents"]])
        rows = it["chunk_rows"]
        for i in range(0, len(rows), BATCH):
            batch = rows[i:i + BATCH]
            store.content.put_chunks([chunk_record(build["chunks"][j], vid, build["vectors"][j]) for j in batch])
        store.documents.set_version_status(vid, "extracting_figures")
        store.content.put_figures(it["figures"])
        store.content.put_table_rows(it["table_rows"])
        got = store.content.counts(vid)
        if got != counts:
            store.documents.set_version_status(vid, "failed", error=f"counts {got} != expected {counts}")
            raise SystemExit(f"{e['id']}: loaded {got}, expected {counts}")
        store.documents.set_version_status(vid, "verifying", chunk_count=counts["chunks"], figure_count=counts["figures"])
        gen = store.documents.activate(vid)
        secs = time.perf_counter() - t0
        log(f"{e['id']:<40} {vid}  " + "  ".join(f"{k} {v:>5}" for k, v in counts.items()) + f"  {secs:5.1f}s  gen {gen}")
        report[e["id"]] = {**counts, "status": "active", "seconds": round(secs, 2)}
    total = time.perf_counter() - t_all
    log(f"\n{len(items)} documents, {sum(r['chunks'] for r in report.values())} chunks, "
        f"{sum(r['parents'] for r in report.values())} parents, {sum(r['figures'] for r in report.values())} figures, "
        f"{sum(r['table_rows'] for r in report.values())} table rows in {total:.1f}s"
        + (" (dry run)" if dry_run else ""))
    report["_total_seconds"] = round(total, 2)
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--source-root", type=Path, default=DEFAULT_ROOT, help="the v1 project with docs/, index/, storage/")
    ap.add_argument("--dsn", default=None, help="PostgreSQL DSN (default: DATABASE_URL)")
    ap.add_argument("--dry-run", action="store_true", help="print what would be loaded; touch nothing")
    a = ap.parse_args(argv)
    if a.dry_run:
        migrate(None, a.source_root, dry_run=True)
        return
    from pharmassist.store.pg import PgStore
    store = PgStore.connect(a.dsn)
    try:
        store.migrate()
        migrate(store, a.source_root)
    finally:
        store.close()


if __name__ == "__main__":
    main()
