"""submit_upload: each rejection, idempotent reuse, in-flight jobs, force re-queue of an active version."""

import copy
import io
import zipfile

import pytest
import pymupdf

from pharmassist.config import PROJECT_ROOT, load_config
from pharmassist.ingest.submit import UploadRejected, sniff, submit_upload
from fakes_ingest import SMALL_PDF, document, world

PDF_BYTES = (PROJECT_ROOT / "docs" / SMALL_PDF).read_bytes()
XLSX_PATH = PROJECT_ROOT / "docs" / "va_national_formulary_2026_09.xlsx"


@pytest.fixture
def cfg():
    c = copy.deepcopy(load_config())
    c["queue"].update(backend="memory")
    c["storage"].update(backend="local")
    return c


def submit(w, data=PDF_BYTES, name=SMALL_PDF, ctype="application/pdf", doc=None, **kw):
    return submit_upload(w.store, file_bytes=data, file_name=name, content_type=ctype, document=doc or document(),
                         requested_by="admin-1", cfg=w.cfg, storage=w.storage, queue=w.queue, **kw)


def small_pdf(pages: int) -> bytes:
    doc = pymupdf.open()
    for i in range(pages):
        doc.new_page().insert_text((72, 72), f"page {i + 1}")
    return doc.tobytes()


def fake_xlsx() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/workbook.xml", "<workbook/>")
    return buf.getvalue()


# ---- validation ----

def test_sniffing_reads_the_bytes_not_the_name():
    assert sniff(PDF_BYTES) == "application/pdf"
    assert sniff(b"   \n%PDF-1.4 ...") == "application/pdf"
    assert sniff(fake_xlsx()).endswith("spreadsheetml.sheet")
    plain_zip = io.BytesIO()
    with zipfile.ZipFile(plain_zip, "w") as z:
        z.writestr("a.txt", "x")
    assert sniff(plain_zip.getvalue()) is None and sniff(b"hello") is None and sniff(b"") is None


@pytest.mark.parametrize("data,name,ctype,code,hint", [
    (b"x" * 60, "big.pdf", "application/pdf", "upload_too_large", "limit"),
    (b"", "empty.pdf", "application/pdf", "upload_type", "empty"),
    (b"MZ not a pdf", "exe.pdf", "application/pdf", "upload_type", "only PDF and XLSX"),
    (fake_xlsx(), "sheet.xlsx", "application/pdf", "upload_type", "declared type"),
    (PDF_BYTES, "report.docx", "application/pdf", "upload_type", "extension"),
    (b"%PDF-1.7 broken", "broken.pdf", "application/pdf", "upload_type", "cannot be opened"),
    (small_pdf(3), "long.pdf", "application/pdf", "upload_pages", "3 pages"),
])
def test_rejections_happen_before_anything_is_stored(tmp_path, cfg, data, name, ctype, code, hint):
    cfg["uploads"].update(max_bytes=50, max_pages=2) if code == "upload_too_large" else cfg["uploads"].update(max_pages=2)
    w = world(tmp_path, cfg)
    with pytest.raises(UploadRejected) as e:
        submit(w, data, name, ctype)
    assert e.value.code == code and hint in e.value.message
    assert not w.store.documents.docs and not w.store.documents.versions and w.queue.pending() == 0
    assert not (tmp_path / "objects").exists()


# ---- the happy path ----

def test_a_new_upload_registers_document_version_job_and_queues_a_message(tmp_path, cfg):
    w = world(tmp_path, cfg)
    r = submit(w)
    assert not r.reused and r.job is not None and r.job.status == "queued" and r.job.requested_by == "admin-1"
    v = r.version
    assert v.status == "queued" and v.pages == 2 and v.bytes == len(PDF_BYTES) and len(v.id) == 16
    assert v.s3_key == f"sources/{r.document.id}/{v.id}/{SMALL_PDF}" and w.storage.get_bytes(v.s3_key) == PDF_BYTES
    assert v.content_type == "application/pdf" and v.created_by == "admin-1"
    [msg] = w.queue.receive(wait_s=0)
    assert msg.body == {"job_id": r.job.id, "version_id": v.id, "document_id": r.document.id}
    assert w.store.documents.get_document(r.document.id).title == r.document.title


def test_file_names_are_sanitized_and_the_key_is_content_addressed(tmp_path, cfg):
    w = world(tmp_path, cfg)
    r = submit(w, name="../../etc/pass wd (final).PDF")
    assert r.version.file_name == "etc_pass_wd_final_.PDF" or r.version.file_name.endswith(".PDF")
    assert "/" not in r.version.file_name and ".." not in r.version.file_name
    assert r.version.s3_key.startswith(f"sources/{r.document.id}/{r.version.id}/")


def test_a_spreadsheet_has_no_page_count(tmp_path, cfg):
    w = world(tmp_path, cfg)
    r = submit(w, XLSX_PATH.read_bytes(), XLSX_PATH.name,
               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
               doc=document("va_national_formulary_2026_09", doc_type="formulary", program="VA", authority="binding"))
    assert r.version.pages is None and r.version.content_type.endswith("spreadsheetml.sheet")


def test_the_same_bytes_already_active_are_a_duplicate_unless_forced(tmp_path, cfg):
    w = world(tmp_path, cfg)
    r = submit(w)
    w.store.documents.set_version_status(r.version.id, "verifying")
    w.store.documents.activate(r.version.id)
    with pytest.raises(UploadRejected) as e:
        submit(w)
    assert e.value.code == "duplicate_version" and r.version.id in e.value.message
    assert w.queue.pending() == 1   # only the first job's message

    forced = submit(w, force=True)
    assert forced.reused and forced.job.id != r.job.id and forced.version.id == r.version.id
    assert forced.version.status == "queued" and w.queue.pending() == 2
    assert w.store.documents.get_document(r.document.id).active_version_id == r.version.id   # untouched until rebuilt


def test_a_failed_version_is_reused_with_a_new_job(tmp_path, cfg):
    w = world(tmp_path, cfg)
    r = submit(w)
    w.store.documents.update_job(r.job.id, status="dead_letter", error="transient: boom", finished=True)
    w.store.documents.set_version_status(r.version.id, "failed", error="transient: boom")
    again = submit(w)
    assert again.reused and again.version.id == r.version.id and again.job.id != r.job.id
    assert again.version.status == "queued" and again.version.error is None
    assert len(w.store.documents.versions) == 1 and w.queue.pending() == 2
    assert len(w.storage.list_keys("sources/")) == 1   # not re-uploaded


def test_a_superseded_version_removed_from_the_index_gets_a_fresh_job(tmp_path, cfg):
    """After DELETE /admin/documents/{id}/index the version is 'superseded' with the same sha256 and
    no active pointer; re-indexing (force) and a plain re-upload both queue a new job for it."""
    w = world(tmp_path, cfg)
    r = submit(w)
    w.store.documents.update_job(r.job.id, status="succeeded", finished=True)
    w.store.documents.set_version_status(r.version.id, "superseded")
    for force in (True, False):
        again = submit(w, force=force)
        assert again.reused and again.version.id == r.version.id and again.job.id != r.job.id
        assert again.version.status == "queued" and again.version.sha256 == r.version.sha256
        w.store.documents.update_job(again.job.id, status="succeeded", finished=True)
        w.store.documents.set_version_status(r.version.id, "superseded")
    assert w.queue.pending() == 3 and len(w.storage.list_keys("sources/")) == 1


def test_an_upload_with_a_job_in_flight_is_not_queued_twice(tmp_path, cfg):
    w = world(tmp_path, cfg)
    r = submit(w)
    again = submit(w)
    assert again.reused and again.job.id == r.job.id and w.queue.pending() == 1
    w.store.documents.update_job(r.job.id, status="running", started=True)
    assert submit(w).job.id == r.job.id and w.queue.pending() == 1


def test_metadata_changes_keep_the_active_version(tmp_path, cfg):
    w = world(tmp_path, cfg)
    r = submit(w)
    w.store.documents.set_version_status(r.version.id, "verifying")
    w.store.documents.activate(r.version.id)
    newer = submit(w, PDF_BYTES + b"\n% revised\n", doc=document(title="Renamed"))
    doc = w.store.documents.get_document(newer.document.id)
    assert doc.title == "Renamed" and doc.active_version_id == r.version.id
    assert newer.version.id != r.version.id and not newer.reused


def test_the_same_bytes_under_another_document_id_are_refused(tmp_path, cfg):
    w = world(tmp_path, cfg)
    submit(w)
    with pytest.raises(UploadRejected) as e:
        submit(w, doc=document("some_other_doc"))
    assert e.value.code == "duplicate_version" and "cms_partd_opioid_pharmacists_2022" in e.value.message


def test_storage_without_exists_is_accepted(tmp_path, cfg):
    """The API passes its own storage object (put_bytes/get_bytes/presign/ping, no exists)."""
    class ApiStorage:
        def __init__(self):
            self.puts = []

        def put_bytes(self, key, data, content_type):
            self.puts.append((key, len(data), content_type))

        def get_bytes(self, key):
            raise KeyError(key)
    w = world(tmp_path, cfg)
    w.storage = ApiStorage()
    r = submit(w)
    assert w.storage.puts == [(r.version.s3_key, len(PDF_BYTES), "application/pdf")]
