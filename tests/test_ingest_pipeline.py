"""build_version and the worker over fakes: stage progression, verification, activation, retries and
the dead-letter queue, permanent failures, stale jobs, heartbeats, shutdown. One end-to-end run
through the real Docling parser is behind RUN_DOCLING=1."""

import copy
import os
import threading
import time
from pathlib import Path

import pytest

from pharmassist.config import PROJECT_ROOT, load_config
from pharmassist.embedders.base import TransientError
from pharmassist.ingest import pipeline
from pharmassist.ingest.pipeline import PermanentError, build_version, chunker_sizes
from pharmassist.ingest.submit import submit_upload
from pharmassist.ingest.worker import Worker, run_forever
from pharmassist.parsers import docling_parser
from fakes_ingest import FLOW, SMALL_PDF, FakeVision, HashEmbed, document, fake_parse, fake_tools, world

PDF_BYTES = (PROJECT_ROOT / "docs" / SMALL_PDF).read_bytes()
XLSX_PATH = PROJECT_ROOT / "docs" / "va_national_formulary_2026_09.xlsx"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
STAGES = ["queued", "parsing", "extracting_figures", "chunking", "embedding", "verifying", "active"]


@pytest.fixture
def cfg():
    c = copy.deepcopy(load_config())
    c["queue"].update(backend="memory", max_attempts=3, retry_backoff_s=0, heartbeat_s=60, visibility_timeout_s=120,
                      shutdown_grace_s=60)
    c["storage"].update(backend="local")
    c["llm"]["embedding"].update(batch_size=16, max_retries=1)
    return c


@pytest.fixture(autouse=True)
def isolated_caches(tmp_path, monkeypatch):
    """The parse cache and figure crops stay in tmp: the fake parser must never seed the project's
    real caches, which the Docling run below (and v1 scripts) would trust."""
    monkeypatch.setattr(docling_parser, "cache_dir", lambda: tmp_path / "parse_cache")
    monkeypatch.setattr(pipeline, "figures_dir", lambda d, v: tmp_path / "figures" / d / v)


def submit(w, data=PDF_BYTES, name=SMALL_PDF, ctype="application/pdf", doc=None, **kw):
    return submit_upload(w.store, file_bytes=data, file_name=name, content_type=ctype, document=doc or document(),
                         requested_by=None, cfg=w.cfg, storage=w.storage, queue=w.queue, **kw)


def worker(w, **kw):
    return Worker(w.store, w.queue, embed_fn=w.embed, cfg=w.cfg, storage=w.storage, tools=w.tools, worker_id="w-test",
                  work_root=None, **kw)


def build(w, version, **kw):
    return build_version(w.store, version, work_dir=kw.pop("work_dir"), embed_fn=w.embed, cfg=w.cfg,
                         log=lambda m: None, storage=w.storage, tools=w.tools, **kw)


# ---- build_version ----

def test_a_pdf_moves_through_every_stage_and_is_activated_with_v1_ids(tmp_path, cfg):
    w = world(tmp_path, cfg)
    r = submit(w)
    stages = []
    stats = build(w, r.version, work_dir=tmp_path / "work", progress=stages.append)
    assert w.store.documents.history[r.version.id] == STAGES
    assert stages == STAGES[1:-1]
    assert w.store.documents.active_versions() == {r.document.id: r.version.id}
    v = w.store.documents.get_version(r.version.id)
    assert v.status == "active" and v.pages == 2 and v.chunk_count == stats["chunks"] > 0 and v.figure_count == 1
    assert v.embedder_model == "fake-3072" and v.embedding_dim == 3072 and v.chunker_version and v.parser_version
    assert stats["generation"] == 2 and set(stats["stage_s"]) == set(STAGES[1:-1])

    chunks = list(w.store.content.iter_chunks(r.version.id))
    assert all(c.chunk_id.startswith(f"{r.document.id}:s") and ":c" in c.chunk_id for c in chunks)
    assert all(c.parent_id and (r.version.id, c.parent_id) in w.store.content.parents for c in chunks)
    assert all(len(c.embedding) == 3072 and c.search_text == c.text for c in chunks)
    assert all(c.program == "Medicare Part D" and c.authority == "summary_of_binding_policy" and c.doc_date == "2022-12-19"
               for c in chunks)
    assert all(c.page_start and c.page_end >= c.page_start and c.metadata["source_sha256"] == r.version.sha256
               for c in chunks)
    fig_chunks = [c for c in chunks if c.figure_ids]
    assert fig_chunks and fig_chunks[0].figure_ids == [f"{r.document.id}:p1:f0"]
    assert fig_chunks[0].verification == "ocr_checked" and "figure" in fig_chunks[0].content_types
    assert "vision" in fig_chunks[0].extraction and "Box 2 (decision)" in fig_chunks[0].text


def test_figures_are_decided_checked_and_their_crops_stored(tmp_path, cfg):
    w = world(tmp_path, cfg)
    r = submit(w)
    stats = build(w, r.version, work_dir=tmp_path / "work")
    assert stats["figures_inventory"]["images"] == 2 and stats["figures_inventory"]["decorative"] == 1
    assert stats["figures_inventory"]["indexed"] == 1 and stats["figures_inventory"]["spent_usd"] > 0
    [fig] = w.store.content.figures_for_page(r.document.id, 1)
    assert fig.kind == "flowchart" and fig.status == "ocr_checked" and fig.title == FLOW["title"]
    assert fig.crop_s3_key == f"figures/{r.document.id}/{r.version.id}/p001_f0.png"
    assert w.storage.get_bytes(fig.crop_s3_key).startswith(b"\x89PNG")
    assert fig.record["checks"]["passed"] and fig.record["title_in_image"]
    assert w.tools.vision_fn.calls == [f"{r.document.id}:p1:f0"]   # the logo never reached the model


def test_an_unsupported_title_is_dropped_and_checks_fail_honestly(tmp_path, cfg):
    bad = {**FLOW, "title": "Invented title", "nodes": FLOW["nodes"] + [{"id": "9", "shape": "action", "text": "Start methadone"}]}
    w = world(tmp_path, cfg)
    w.tools = fake_tools(vision=FakeVision(record=bad))
    r = submit(w)
    build(w, r.version, work_dir=tmp_path / "work")
    [fig] = w.store.content.figures_for_page(r.document.id, 1)
    assert fig.title is None and fig.status == "machine_interpreted" and not fig.record["checks"]["passed"]


def test_the_vision_spend_cap_is_a_permanent_failure_before_any_call(tmp_path, cfg):
    cfg["figures"]["max_spend_usd"] = 0.0
    w = world(tmp_path, cfg)
    r = submit(w)
    with pytest.raises(PermanentError, match="max_spend_usd"):
        build(w, r.version, work_dir=tmp_path / "work")
    assert w.tools.vision_fn.calls == []


def test_the_parse_result_is_cached_locally_and_in_storage(tmp_path, cfg):
    w = world(tmp_path, cfg)
    r = submit(w)
    build(w, r.version, work_dir=tmp_path / "work")
    cached = w.storage.list_keys(f"cache/parse/{r.document.id}/")
    assert len(cached) == 1 and cached[0].startswith(f"cache/parse/{r.document.id}/{r.version.id}-")
    assert list((tmp_path / "parse_cache" / r.document.id).glob("*.json"))
    calls = []
    w.tools = fake_tools(parse=lambda *a: calls.append(a) or fake_parse(*a))
    w.store.documents.set_version_status(r.version.id, "queued")
    build(w, r.version, work_dir=tmp_path / "work2")
    assert calls == []   # the second build never converted


def test_a_hash_mismatch_or_missing_object_is_permanent(tmp_path, cfg):
    w = world(tmp_path, cfg)
    r = submit(w)
    w.storage.put_bytes(r.version.s3_key, PDF_BYTES + b"tampered")
    with pytest.raises(PermanentError, match="SHA-256"):
        build(w, r.version, work_dir=tmp_path / "work")
    (tmp_path / "objects" / r.version.s3_key).unlink()
    with pytest.raises(PermanentError, match="missing"):
        build(w, r.version, work_dir=tmp_path / "work")


def test_the_spreadsheet_becomes_va_formulary_rows_without_chunks(tmp_path, cfg):
    w = world(tmp_path, cfg)
    r = submit(w, XLSX_PATH.read_bytes(), XLSX_PATH.name, XLSX,
               doc=document("va_national_formulary_2026_09", title="VHA National Formulary", doc_type="formulary",
                            program="VA", authority="binding", doc_date="2026-09"))
    stats = build(w, r.version, work_dir=tmp_path / "work")
    assert stats["chunks"] == 0 and stats["figures"] == 0 and stats["table_rows"] > 1000
    rows = w.store.content.table_rows_of(r.version.id, "va_formulary")
    assert all(set(x.row) == {"sheet", "row", "cells", "drug", "header_row"} and len(x.row["cells"]) == 7 for x in rows)
    [header] = [x for x in rows if x.row["header_row"]]
    assert header.row["cells"][2] == "Generic" and header.row["drug"] == ""
    assert any(x.row["row"] < header.row["row"] and "PA-F" in x.row["cells"][0] for x in rows)   # note rows kept
    drug = next(x for x in rows if x.row["drug"].upper().startswith("METFORMIN"))
    assert drug.row["cells"][2] == drug.row["drug"] and drug.row_no == drug.row["row"] > header.row["row"]
    assert w.store.documents.get_version(r.version.id).status == "active"
    assert w.embed.calls == 0


def test_the_ny_pdl_also_gets_structured_rows(tmp_path, cfg):
    """Decided by document id, as v1's build_tables did; the extractor runs on the downloaded copy."""
    pdl = PROJECT_ROOT / "docs" / "ny_medicaid_pdl.pdf"
    w = world(tmp_path, cfg)
    from pharmassist.tables import ny_pdl
    calls = []
    real = ny_pdl.extract
    rows_out = real(range(4, 6), path=pdl)
    pytest.MonkeyPatch().setattr(ny_pdl, "extract", lambda pages=None, path=None: calls.append(path) or rows_out)
    try:
        r = submit(w, pdl.read_bytes(), pdl.name, doc=document("ny_medicaid_pdl", program="NY Medicaid",
                                                               doc_type="preferred drug list", authority="binding"))
        stats = build(w, r.version, work_dir=tmp_path / "work")
    finally:
        ny_pdl.extract = real
    assert stats["table_rows"] == len(rows_out) > 0
    assert all(Path(c).parent == tmp_path / "work" for c in calls)   # never docs/
    row = w.store.content.table_rows_of(r.version.id, "ny_pdl")[0].row
    assert {"row", "drug", "drug_name", "status", "drug_class", "page", "coverage_parameters"} <= set(row)
    assert row["row"] == 1 and row["drug"] == row["drug_name"]


def test_counts_that_differ_from_what_was_built_block_activation(tmp_path, cfg):
    w = world(tmp_path, cfg)
    r = submit(w)
    real = w.store.content.counts
    w.store.content.counts = lambda vid: {**real(vid), "chunks": 0}
    with pytest.raises(TransientError, match="counts"):
        build(w, r.version, work_dir=tmp_path / "work")
    assert w.store.documents.active_versions() == {} and w.store.documents.get_version(r.version.id).status == "verifying"


def test_embedding_batches_retry_transient_failures_then_give_up(tmp_path, cfg):
    w = world(tmp_path, cfg)
    w.embed = HashEmbed(fail_times=1)
    r = submit(w)
    build(w, r.version, work_dir=tmp_path / "work")
    assert w.embed.calls >= 2 and w.store.documents.get_version(r.version.id).status == "active"
    w.embed = HashEmbed(always_fail=True)
    r2 = submit(w, PDF_BYTES + b"\n%2\n")
    with pytest.raises(TransientError, match="embedding failed after 2 attempts"):
        build(w, r2.version, work_dir=tmp_path / "work2")


def test_a_wrong_embedding_dimension_is_permanent(tmp_path, cfg):
    w = world(tmp_path, cfg)
    w.embed = lambda texts: [[0.1] * 8 for _ in texts]
    r = submit(w)
    with pytest.raises(PermanentError, match="dimension 8"):
        build(w, r.version, work_dir=tmp_path / "work")


def test_chunker_sizes_follow_the_docling_sections_setup(cfg):
    assert chunker_sizes(cfg) == {"child_tokens": 350, "overlap_tokens": 100, "parent_max_tokens": 1500}


# ---- the worker ----

def test_the_worker_claims_builds_acks_and_records_the_job(tmp_path, cfg):
    w = world(tmp_path, cfg)
    r = submit(w)
    assert worker(w).run(once=True) == 1
    job = w.store.documents.get_job(r.job.id)
    assert job.status == "succeeded" and job.attempt == 1 and job.worker_id == "w-test" and job.stage == "active"
    assert job.started_at and job.heartbeat_at and job.finished_at
    assert w.queue.pending() == 0 and w.queue.calls[-1] == ("ack", None)
    assert w.store.documents.active_versions() == {r.document.id: r.version.id}


def test_a_changed_file_supersedes_the_active_version_and_bumps_the_generation(tmp_path, cfg):
    w = world(tmp_path, cfg)
    first = submit(w)
    worker(w).run(once=True)
    g = w.store.documents.generation()
    second = submit(w, PDF_BYTES + b"\n% revised\n")
    worker(w).run(once=True)
    assert w.store.documents.active_versions() == {first.document.id: second.version.id}
    assert w.store.documents.get_version(first.version.id).status == "superseded"
    assert w.store.documents.generation() == g + 1
    assert w.store.content.counts(first.version.id)["chunks"] > 0   # the old rows stay until cleaned up


def test_transient_failures_retry_with_backoff_then_dead_letter_and_clean_up(tmp_path, cfg):
    cfg["queue"].update(max_attempts=3, retry_backoff_s=30)
    w = world(tmp_path, cfg)
    w.embed = HashEmbed(always_fail=True)
    r = submit(w)
    wk = worker(w)
    [msg] = w.queue.receive(wait_s=0)
    assert wk.handle(msg) == "retry"
    v, job = w.store.documents.get_version(r.version.id), w.store.documents.get_job(r.job.id)
    assert v.status == "queued" and "transient" in v.error and job.status == "queued" and job.attempt == 1
    assert ("retry", 30) in w.queue.calls
    [msg] = w.queue.receive(wait_s=0) or [msg]
    w.queue.retry_later(msg, 0)
    [msg] = w.queue.receive(wait_s=0)
    assert wk.handle(msg) == "retry" and ("retry", 60) in w.queue.calls
    w.queue.retry_later(msg, 0)
    [msg] = w.queue.receive(wait_s=0)
    assert wk.handle(msg) == "dead_letter"
    v, job = w.store.documents.get_version(r.version.id), w.store.documents.get_job(r.job.id)
    assert v.status == "failed" and "after 3 attempts" in v.error and job.status == "dead_letter" and job.attempt == 3
    assert w.queue.pending() == 0 and [d["body"]["job_id"] for d in w.queue.dead_letters()] == [r.job.id]
    assert w.store.content.counts(r.version.id) == {"chunks": 0, "parents": 0, "figures": 0, "table_rows": 0}
    assert w.store.documents.active_versions() == {}


def test_store_errors_count_as_transient(tmp_path, cfg):
    w = world(tmp_path, cfg)
    w.store.content.fail_puts = True
    r = submit(w)
    [msg] = w.queue.receive(wait_s=0)
    assert worker(w).handle(msg) == "retry"
    assert "RuntimeError" in w.store.documents.get_job(r.job.id).error


def test_permanent_failures_dead_letter_at_once_with_a_readable_error(tmp_path, cfg):
    w = world(tmp_path, cfg)

    def refuse(*a):
        raise ValueError("unreadable layout")
    w.tools = fake_tools(parse=refuse)
    r = submit(w)
    assert worker(w).run(once=True) == 1
    v, job = w.store.documents.get_version(r.version.id), w.store.documents.get_job(r.job.id)
    assert v.status == "failed" and v.error == "parse failed: ValueError: unreadable layout"
    assert job.status == "failed" and job.error == v.error and job.attempt == 1
    assert w.queue.pending() == 0 and w.queue.dead_letters()[0]["reason"] == v.error
    assert w.store.documents.active_versions() == {}


def test_a_permanent_failure_after_partial_writes_removes_them(tmp_path, cfg):
    w = world(tmp_path, cfg)
    r = submit(w)
    real_put = w.store.content.put_figures

    def put_then_fail(rows):
        real_put(rows)
        raise PermanentError("simulated failure after figures were written")
    w.store.content.put_figures = put_then_fail
    worker(w).run(once=True)
    assert w.store.content.counts(r.version.id) == {"chunks": 0, "parents": 0, "figures": 0, "table_rows": 0}
    assert w.store.documents.get_version(r.version.id).status == "failed"


def test_a_stale_job_is_skipped_when_a_newer_upload_exists(tmp_path, cfg):
    w = world(tmp_path, cfg)
    old = submit(w)
    new = submit(w, PDF_BYTES + b"\n% newer\n")
    wk = worker(w)
    assert wk.run(max_jobs=2) == 2
    assert w.store.documents.get_job(old.job.id).status == "skipped"
    assert "stale" in w.store.documents.get_job(old.job.id).error
    assert w.store.documents.get_version(old.version.id).status == "superseded"
    assert w.store.documents.get_job(new.job.id).status == "succeeded"
    assert w.store.documents.active_versions() == {old.document.id: new.version.id}
    assert w.embed.calls > 0 and w.queue.pending() == 0


def test_duplicate_deliveries_and_unknown_jobs_are_acknowledged(tmp_path, cfg):
    w = world(tmp_path, cfg)
    r = submit(w)
    wk = worker(w)
    wk.run(once=True)
    calls = w.embed.calls
    w.queue.send({"job_id": r.job.id, "version_id": r.version.id, "document_id": r.document.id})
    w.queue.send({"job_id": "nope", "version_id": "x", "document_id": "y"})
    assert wk.run(max_jobs=2) == 2
    assert w.embed.calls == calls and w.queue.pending() == 0 and not w.queue.dead_letters()


def test_the_heartbeat_extends_visibility_while_a_job_runs(tmp_path, cfg):
    cfg["queue"].update(heartbeat_s=0.05, visibility_timeout_s=777)
    w = world(tmp_path, cfg)
    r = submit(w)

    def slow_build(store, version, **kw):
        kw["progress"]("parsing")
        time.sleep(0.3)
        store.documents.set_version_status(version.id, "verifying")
        store.documents.activate(version.id)
        return {"chunks": 0}
    wk = worker(w, build=slow_build)
    wk.run(once=True)
    extends = [c for c in w.queue.calls if c[0] == "extend"]
    assert len(extends) >= 3 and all(c == ("extend", 777) for c in extends) and wk.heartbeats == len(extends)
    job = w.store.documents.get_job(r.job.id)
    assert job.status == "succeeded" and job.heartbeat_at is not None


def test_the_stage_callback_mirrors_progress_on_the_job(tmp_path, cfg):
    w = world(tmp_path, cfg)
    r = submit(w)
    seen = []
    real = w.store.documents.update_job

    def spy(job_id, **kw):
        if kw.get("stage"):
            seen.append(kw["stage"])
        return real(job_id, **kw)
    w.store.documents.update_job = spy
    worker(w).run(once=True)
    assert seen == ["claimed", "parsing", "extracting_figures", "chunking", "embedding", "verifying", "active"]


def test_shutdown_waits_for_the_grace_period_then_releases_the_message(tmp_path, cfg):
    cfg["queue"].update(heartbeat_s=0.02, shutdown_grace_s=0.2)
    w = world(tmp_path, cfg)
    r = submit(w)
    started = threading.Event()

    def long_build(store, version, **kw):
        started.set()
        time.sleep(5)
        return {}
    wk = worker(w, build=long_build)
    threading.Thread(target=lambda: (started.wait(), wk.request_stop()), daemon=True).start()
    t0 = time.perf_counter()
    assert wk.run() == 1
    assert time.perf_counter() - t0 < 3   # not the build's 5 s
    job, v = w.store.documents.get_job(r.job.id), w.store.documents.get_version(r.version.id)
    assert job.status == "queued" and "interrupted" in job.error and v.status == "queued"
    assert ("retry", 0) in w.queue.calls and w.queue.receive(wait_s=0)   # visible again at once


def test_shutdown_lets_a_short_job_finish(tmp_path, cfg):
    cfg["queue"].update(shutdown_grace_s=5)
    w = world(tmp_path, cfg)
    r = submit(w)
    wk = worker(w)
    wk.request_stop()
    assert wk.run() == 0   # stop before receiving
    wk2 = worker(w)
    [msg] = w.queue.receive(wait_s=0)
    wk2.request_stop()
    assert wk2.handle(msg) == "succeeded"
    assert w.store.documents.get_job(r.job.id).status == "succeeded"


def test_run_forever_once_with_an_empty_queue_returns_zero(tmp_path, cfg):
    w = world(tmp_path, cfg)
    assert run_forever(w.store, w.queue, embed_fn=w.embed, cfg=cfg, once=True, storage=w.storage, tools=w.tools,
                       signals=False) == 0


# ---- end to end through the real Docling parser (RUN_DOCLING=1) ----

@pytest.mark.integration
@pytest.mark.skipif(not os.environ.get("RUN_DOCLING"), reason="set RUN_DOCLING=1 to convert a PDF with Docling")
def test_a_small_pdf_through_the_real_parser(tmp_path, cfg, monkeypatch):
    """va_pbm_bup_oud (4 pages): real Docling conversion and bge tokenizer, fake vision/OCR/embeddings.
    Crops must live under the project root (the figure helpers address them that way), so this test
    uses the real figures dir and removes it afterwards; the parse cache goes to tmp."""
    monkeypatch.setattr(pipeline, "figures_dir", lambda d, v: PROJECT_ROOT / "storage" / "figures" / d / v)
    pdf = PROJECT_ROOT / "docs" / "va_pbm_bup_oud.pdf"
    w = world(tmp_path, cfg)
    w.tools = pipeline.Tools(vision_fn=FakeVision(), ocr_fn=lambda crop: [], sleep=lambda s: None)
    r = submit(w, pdf.read_bytes(), pdf.name, doc=document("va_pbm_bup_oud", title="Buprenorphine for Opioid Use Disorder",
                                                           program="VA", doc_type="clinician guide", authority="advisory",
                                                           doc_date="2023-03"))
    try:
        t0 = time.perf_counter()
        assert worker(w).run(once=True) == 1
        seconds = time.perf_counter() - t0
    finally:
        import shutil
        shutil.rmtree(PROJECT_ROOT / "storage" / "figures" / "va_pbm_bup_oud" / r.version.id, ignore_errors=True)
    v = w.store.documents.get_version(r.version.id)
    assert v.status == "active" and v.pages == 4 and v.chunk_count >= 20
    chunks = list(w.store.content.iter_chunks(r.version.id))
    assert any("buprenorphine" in c.text.lower() for c in chunks)
    assert any("table" in c.content_types for c in chunks)
    print(f"\nDocling end-to-end: {v.chunk_count} chunks, {v.figure_count} figures, {seconds:.0f}s")


def test_font_anchors_handle_an_image_only_pdf():
    """A scanned PDF has no text spans: the font-size histogram is empty and must not raise (an upload
    failed at the chunking stage with IndexError before this guard)."""
    from types import SimpleNamespace
    from pharmassist.chunkers.sections import _font_anchors
    doc = SimpleNamespace(page_count=4)
    assert _font_anchors(doc, [[], [], [], []], [1, 2, 3, 4]) == []
