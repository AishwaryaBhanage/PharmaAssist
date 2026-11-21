"""scripts/migrate_v1_to_pg.py on a tiny synthetic v1 build: mapping, counts, activation, idempotency."""

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest
import yaml

from pharmassist.search import hybrid
from test_store_fixtures import DIM, pg_dsn, pg_store, seeded_vectors, store  # noqa: F401

PROJECT_ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("migrate_v1_to_pg", PROJECT_ROOT / "scripts" / "migrate_v1_to_pg.py")
mig = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mig)

CATALOG = {"documents": [
    {"id": "va_dod_cpg_opioids_2022", "file": "va_dod_cpg_opioids_2022.pdf", "title": "Opioids CPG", "publisher": "VA/DoD",
     "program": "VA", "doc_type": "clinical guideline", "authority": "advisory", "date": "2022-05",
     "source_url": "https://example.org/opioids.pdf", "pages": 177},
    {"id": "ny_medicaid_pdl", "file": "ny_medicaid_pdl.pdf", "title": "NYRx PDL", "publisher": "NYS DOH", "program": "NY Medicaid",
     "doc_type": "preferred drug list", "authority": "binding", "date": "2026-09-14", "pages": 86},
    {"id": "va_national_formulary_2026_09", "file": "va_national_formulary_2026_09.xlsx", "title": "VHA National Formulary",
     "publisher": "VA PBM", "program": "VA", "doc_type": "formulary", "authority": "binding", "date": "2026-09", "pages": None},
]}


def chunk(doc, s, c, text, page, pages, **extra):
    e = next(d for d in CATALOG["documents"] if d["id"] == doc)
    return {"chunk_id": f"{doc}:s{s}:c{c}", "doc_id": doc, "page": page, "text": text, "program": e["program"],
            "doc_type": e["doc_type"], "authority": e["authority"], "date": e["date"], "pages": pages,
            "parent_id": f"{doc}:s{s}", "source_sha256": "deadbeef", "printed_pages": [str(p) for p in pages],
            "section": "Top > Sub", "content_types": ["text"], "extraction": ["docling_text"],
            "bboxes": [[page, 1.0, 2.0, 3.0, 4.0]], "figure_ids": [], "verification": None, **extra}


@pytest.fixture
def source_root(tmp_path):
    root = tmp_path / "v1"
    (root / "docs").mkdir(parents=True)
    (root / "index" / "docling_sections").mkdir(parents=True)
    (root / "index" / "tables").mkdir()
    (root / "storage" / "figures" / "va_dod_cpg_opioids_2022").mkdir(parents=True)
    (root / "docs" / "catalog.yaml").write_text(yaml.safe_dump(CATALOG))
    for d in CATALOG["documents"]:
        (root / "docs" / d["file"]).write_bytes(d["id"].encode() * 10)
    chunks = [
        chunk("va_dod_cpg_opioids_2022", 0, 0, "Naloxone should be offered to patients on opioids.", 27, [27]),
        chunk("va_dod_cpg_opioids_2022", 0, 1, "Buprenorphine is preferred over full agonists for chronic pain.", 27, [27, 28]),
        chunk("va_dod_cpg_opioids_2022", 1, 0, "Figure 1. Taper flowchart.", 30, [30, 32], content_types=["figure"],
              extraction=["docling_text", "vision"], figure_ids=["va_dod_cpg_opioids_2022:p30:f0"], verification="reviewed"),
        chunk("ny_medicaid_pdl", 0, 0, "Preferred buprenorphine films; NCPDP reject code 22.", 4, [4]),
    ]
    parents = [
        {"parent_id": "va_dod_cpg_opioids_2022:s0", "doc_id": "va_dod_cpg_opioids_2022", "page": 27, "pages": [27, 28],
         "section": "Top > Sub", "text": "Naloxone ... Buprenorphine ...", "program": "VA", "doc_type": "clinical guideline",
         "authority": "advisory", "date": "2022-05", "source_sha256": "deadbeef", "printed_pages": ["27", "28"],
         "content_types": ["text"], "extraction": ["docling_text"], "figure_ids": [], "verification": None},
        {"parent_id": "va_dod_cpg_opioids_2022:s1", "doc_id": "va_dod_cpg_opioids_2022", "page": 30, "pages": [30, 31, 32],
         "section": "Top > Figures", "text": "Figure 1. Taper flowchart.", "program": "VA", "doc_type": "clinical guideline",
         "authority": "advisory", "date": "2022-05", "source_sha256": "deadbeef", "printed_pages": [],
         "content_types": ["figure"], "extraction": ["docling_text", "vision"],
         "figure_ids": ["va_dod_cpg_opioids_2022:p30:f0"], "verification": "reviewed"},
        {"parent_id": "ny_medicaid_pdl:s0", "doc_id": "ny_medicaid_pdl", "page": 4, "pages": [4], "section": "PDL",
         "text": "Preferred buprenorphine films; NCPDP reject code 22.", "program": "NY Medicaid", "doc_type": "preferred drug list",
         "authority": "binding", "date": "2026-09-14", "source_sha256": "cafe", "printed_pages": [],
         "content_types": ["text"], "extraction": ["pdl_row_extractor"], "figure_ids": [], "verification": None},
    ]
    d = root / "index" / "docling_sections"
    (d / "chunks.jsonl").write_text("".join(json.dumps(c) + "\n" for c in chunks))
    (d / "parents.jsonl").write_text("".join(json.dumps(p) + "\n" for p in parents))
    np.save(d / "vectors.npy", seeded_vectors(len(chunks), 42))
    (d / "manifest.json").write_text(json.dumps({"setup": "docling_sections", "model": "text-embedding-3-large", "dim": DIM,
                                                 "n_chunks": len(chunks), "n_parents": len(parents)}))
    (root / "index" / "tables" / "va_formulary_cells.json").write_text(json.dumps({"sheet": "Formulary", "rows": {
        "7": ["The VANF is dosage form specific.", "", "", "", "", "", ""],
        "16": ["VA Class", "Restriction", "Generic", "Dosage Form", "Comments", "U/E Formulary", "Clinical Guidance"],
        "17": ["AM800", "PA-F", "ABACAVIR", "SOLN,ORAL", "Restricted", "", ""],
        "18": ["", "", "", "", "", "", ""],
        "19": ["BL110", "", "METFORMIN HCL", "TAB", "", "", ""]}}))
    (root / "index" / "tables" / "ny_pdl_rows.jsonl").write_text("".join(json.dumps(r) + "\n" for r in [
        {"row_id": "ny_medicaid_pdl#p4#row-1", "page": 4, "drug_name": "Celebrex®", "drug_name_norm": "celebrex", "status": "preferred"},
        {"row_id": "ny_medicaid_pdl#p4#row-2", "page": 4, "drug_name": "Suboxone® film", "drug_name_norm": "suboxone film", "status": "preferred"}]))
    (root / "storage" / "figures" / "records.json").write_text(json.dumps({
        "va_dod_cpg_opioids_2022:p30:f0": {"record": {"kind": "flowchart", "title": "Figure 1", "nodes": []}, "status": "reviewed",
                                           "page": 30, "bbox": [1, 2, 3, 4], "crop": "storage/figures/va_dod_cpg_opioids_2022/p030_f0.png",
                                           "doc_id": "va_dod_cpg_opioids_2022", "model": "m", "checks": {"passed": True}}}))
    return root


def test_dry_run_reports_counts_and_writes_nothing(source_root, store):
    lines = []
    rep = mig.migrate(store, source_root, dry_run=True, log=lines.append)
    assert rep["va_dod_cpg_opioids_2022"] == {"chunks": 3, "parents": 2, "figures": 1, "table_rows": 0, "status": "dry_run", "seconds": 0.0}
    assert rep["ny_medicaid_pdl"]["table_rows"] == 2 and rep["va_national_formulary_2026_09"]["table_rows"] == 5
    assert store.documents.list_documents() == [] and "dry run" in lines[-1]


def test_migration_loads_activates_and_is_idempotent(source_root, store):
    rep = mig.migrate(store, source_root, log=lambda s: None)
    sha = hashlib.sha256(b"va_dod_cpg_opioids_2022" * 10).hexdigest()
    vid = sha[:16]
    assert rep["va_dod_cpg_opioids_2022"]["status"] == "active" and rep["_total_seconds"] >= 0
    v = store.documents.get_version(vid)
    assert v.status == "active" and v.s3_key == f"sources/va_dod_cpg_opioids_2022/{vid}/va_dod_cpg_opioids_2022.pdf"
    assert v.content_type == "application/pdf" and v.pages == 177 and v.chunk_count == 3 and v.figure_count == 1
    assert v.embedder_model == "text-embedding-3-large" and v.embedding_dim == DIM and v.sha256 == sha
    assert store.documents.active_versions().keys() == {"va_dod_cpg_opioids_2022", "ny_medicaid_pdl", "va_national_formulary_2026_09"}
    assert store.documents.generation() == 4
    cat = store.documents.catalog()
    assert cat["va_dod_cpg_opioids_2022"]["source_url"] == "https://example.org/opioids.pdf" and cat["va_national_formulary_2026_09"]["pages"] is None
    assert store.content.counts(vid) == {"chunks": 3, "parents": 2, "figures": 1, "table_rows": 0}
    xlsx = store.documents.active_versions()["va_national_formulary_2026_09"]
    assert store.content.counts(xlsx) == {"chunks": 0, "parents": 0, "figures": 0, "table_rows": 5}
    assert store.documents.get_version(xlsx).content_type.endswith("spreadsheetml.sheet")

    # chunk mapping, including what only metadata keeps
    c = store.content.chunks_by_ids([(vid, "va_dod_cpg_opioids_2022:s1:c0")])[(vid, "va_dod_cpg_opioids_2022:s1:c0")]
    assert (c.page_start, c.page_end, c.section_path, c.content_types) == (30, 32, ["Top", "Sub"], ["figure"])
    assert c.extraction == "docling_text,vision" and c.metadata["extraction"] == ["docling_text", "vision"]
    assert c.metadata["pages"] == [30, 32] and c.metadata["bboxes"] == [[30, 1.0, 2.0, 3.0, 4.0]] and c.verification == "reviewed"
    assert c.figure_ids == ["va_dod_cpg_opioids_2022:p30:f0"] and c.search_text == c.text and c.doc_date == "2022-05"
    emb = next(store.content.iter_chunks(vid, with_embeddings=True))
    expected = seeded_vectors(4, 42)[[x["chunk_id"] for x in map(json.loads, (source_root / "index/docling_sections/chunks.jsonl").open())].index(emb.chunk_id)]
    assert np.allclose(np.asarray(emb.embedding), expected, atol=2e-3)    # row order of vectors.npy preserved
    p = store.content.parents_by_ids([(vid, "va_dod_cpg_opioids_2022:s1")])[(vid, "va_dod_cpg_opioids_2022:s1")]
    assert (p.page_start, p.page_end, p.metadata["program"], p.metadata["figure_ids"]) == (30, 32, "VA", ["va_dod_cpg_opioids_2022:p30:f0"])
    f = store.content.figure("va_dod_cpg_opioids_2022", "va_dod_cpg_opioids_2022:p30:f0")
    assert (f.page, f.kind, f.title, f.status, f.crop_s3_key) == (30, "flowchart", "Figure 1", "reviewed",
                                                                  "figures/va_dod_cpg_opioids_2022/p030_f0.png")
    assert f.record["checks"] == {"passed": True}
    # table rows keep their provenance and a 'drug' key for the prefix filter
    assert [r["drug"] for r in store.content.table_rows("va_formulary")] == [None, None, "ABACAVIR", None, "METFORMIN HCL"]
    assert store.content.table_rows("va_formulary", drug="metf")[0]["row"] == 19
    assert store.content.table_rows("va_formulary")[1]["header_row"] == 16
    assert [r["drug"] for r in store.content.table_rows("ny_pdl", drug="sub")] == ["Suboxone® film"]
    assert store.content.table_rows("ny_pdl")[0]["row_id"] == "ny_medicaid_pdl#p4#row-1"

    # the results v1 produced come back through the hybrid search with the same keys
    res = hybrid.search("naloxone", k=1, store=store, mode="keyword", cfg={"return_parents": False})
    assert res[0]["chunk_id"] == "va_dod_cpg_opioids_2022:s0:c0" and res[0]["printed_pages"] == ["27"] and res[0]["doc_type"] == "clinical guideline"
    res = hybrid.search("reject code 22", k=1, store=store, mode="keyword", cfg={"return_parents": True})
    assert res[0]["parent_id"] == "ny_medicaid_pdl:s0" and res[0]["extraction"] == ["pdl_row_extractor"] and res[0]["authority"] == "binding"

    # second run: everything is active already, nothing changes
    lines = []
    rep2 = mig.migrate(store, source_root, log=lines.append)
    assert all(r["status"] == "skipped" for k, r in rep2.items() if not k.startswith("_"))
    assert store.documents.generation() == 4 and sum("skipped" in l for l in lines) == 3


def test_an_interrupted_load_is_redone(source_root, store):
    plan, _ = mig.plan(source_root)
    it = plan[0]
    from pharmassist.store.protocols import Document, DocumentVersion
    store.documents.upsert_document(Document(id=it["entry"]["id"], title="t", program="VA"))
    store.documents.create_version(DocumentVersion(id=it["version_id"], document_id=it["entry"]["id"], sha256=it["sha256"],
                                                   s3_key=it["s3_key"], file_name="f", content_type="application/pdf", bytes=1,
                                                   status="chunking"))
    store.content.put_parents([mig.parent_record(it["parents"][0], it["version_id"])])     # half-loaded
    rep = mig.migrate(store, source_root, log=lambda s: None)
    assert rep[it["entry"]["id"]]["status"] == "active" and store.content.counts(it["version_id"])["parents"] == 2


def test_plan_refuses_a_vector_file_that_does_not_match(source_root):
    np.save(source_root / "index/docling_sections/vectors.npy", seeded_vectors(3, 1))
    with pytest.raises(SystemExit, match="vectors.npy"):
        mig.plan(source_root)
