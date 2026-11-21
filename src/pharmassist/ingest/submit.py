"""Admin upload submission: validate the file, register the document and its version, store the
bytes, create the job and queue it. The API (POST /admin/documents) calls `submit_upload`.

Checks happen in cost order (size, sniffed type, page count) before anything is stored. A file is
accepted for what its bytes say it is, not for its declared content type or extension: a PDF starts
with %PDF-, an XLSX is a zip holding xl/workbook.xml. Everything stored is content-addressed by
sha256, so the same bytes uploaded twice never make a second version.
"""

import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath

from pharmassist import cloud
from pharmassist.store.protocols import Conflict, Document, DocumentVersion, IngestionJob

PDF = "application/pdf"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
EXTENSIONS = {PDF: ".pdf", XLSX: ".xlsx"}
IN_FLIGHT = ("queued", "running")   # job statuses that mean a worker will (or does) handle the version


class UploadRejected(Exception):
    """The upload is refused before anything is stored. `code` is one of upload_too_large,
    upload_type, upload_pages, duplicate_version; `message` is safe to show the admin."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass
class UploadResult:
    document: Document
    version: DocumentVersion
    job: IngestionJob | None
    reused: bool = False


def sniff(data: bytes) -> str | None:
    """The content type the bytes really are: PDF, XLSX or None."""
    if data[:1024].lstrip().startswith(b"%PDF-"):
        return PDF
    if data[:4] == b"PK\x03\x04":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                names = set(z.namelist())
        except zipfile.BadZipFile:
            return None
        if "xl/workbook.xml" in names and "[Content_Types].xml" in names:
            return XLSX
    return None


def safe_file_name(name: str, content_type: str) -> str:
    """The basename with path separators and odd characters removed, the right extension kept."""
    base = PurePosixPath(name.replace("\\", "/")).name
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._") or "upload"
    ext = EXTENSIONS[content_type]
    if not base.lower().endswith(ext):
        base += ext
    return base[:120]


def count_pages(data: bytes) -> int:
    import pymupdf
    try:
        with pymupdf.open(stream=data, filetype="pdf") as pdf:
            if pdf.needs_pass:
                raise UploadRejected("upload_type", "the PDF is password protected")
            return pdf.page_count
    except UploadRejected:
        raise
    except Exception as e:   # pymupdf raises its own error classes for damaged files
        raise UploadRejected("upload_type", f"the PDF cannot be opened ({type(e).__name__})") from None


def validate(file_bytes: bytes, file_name: str, content_type: str, cfg: dict) -> tuple[str, int | None]:
    """(real content type, page count or None for spreadsheets); raises UploadRejected."""
    u = cfg["uploads"]
    if len(file_bytes) > u["max_bytes"]:
        raise UploadRejected("upload_too_large", f"the file is {len(file_bytes):,} bytes; the limit is {u['max_bytes']:,}")
    if not file_bytes:
        raise UploadRejected("upload_type", "the file is empty")
    kind = sniff(file_bytes)
    if kind is None or kind not in u["content_types"]:
        raise UploadRejected("upload_type", "only PDF and XLSX files are accepted (checked by content, not by name)")
    if content_type and content_type.split(";")[0].strip() != kind:
        raise UploadRejected("upload_type", f"the file's declared type {content_type!r} doesn't match its content")
    ext = PurePosixPath(file_name).suffix.lower()
    if ext and ext != EXTENSIONS[kind]:
        raise UploadRejected("upload_type", f"the file name's extension {ext!r} doesn't match its content")
    pages = None
    if kind == PDF:
        pages = count_pages(file_bytes)
        if pages == 0:
            raise UploadRejected("upload_type", "the PDF has no pages")
        if pages > u["max_pages"]:
            raise UploadRejected("upload_pages", f"the PDF has {pages} pages; the limit is {u['max_pages']}")
    return kind, pages


def _latest_job(store, version_id: str) -> IngestionJob | None:
    page = store.documents.list_jobs(version_id=version_id, limit=1)
    return page.items[0] if page.items else None


def submit_upload(store, *, file_bytes: bytes, file_name: str, content_type: str, document: Document,
                  requested_by: str | None, cfg: dict, storage=None, queue=None, force: bool = False) -> UploadResult:
    """Register an admin upload and queue its build.

    - The document's metadata is upserted (an existing document keeps its active version).
    - The file goes to sources/<doc_id>/<sha16>/<file_name> unless that key already exists.
    - The version row is keyed by sha256: a row that isn't active is reused (status back to queued);
      an active one is a `duplicate_version` rejection unless `force`, which rebuilds it on a new job.
    - A version whose latest job is still queued or running isn't queued twice; that job is returned.

    `storage` is duck-typed: `put_bytes(key, data, content_type)` is required; `exists(key)` is used
    when present to skip a re-upload (the key is content-addressed, so a repeat put is harmless).
    `queue` needs `send(body)`.
    """
    kind, pages = validate(file_bytes, file_name, content_type, cfg)
    sha = cloud.sha256_bytes(file_bytes)
    version_id = sha[:16]
    name = safe_file_name(file_name, kind)
    key = cloud.source_key(document.id, version_id, name)

    existing_doc = store.documents.get_document(document.id)
    if existing_doc is not None:   # metadata changes; identity and the serving version don't
        document.active_version_id = existing_doc.active_version_id
        document.created_by = document.created_by or existing_doc.created_by
        document.created_at = existing_doc.created_at
    version = store.documents.version_by_sha(document.id, sha)
    if version is None and store.documents.get_version(version_id) is not None:
        other = store.documents.get_version(version_id).document_id
        raise UploadRejected("duplicate_version", f"this exact file is already registered as a version of {other!r}")
    if version is not None and version.status == "active" and not force:
        raise UploadRejected("duplicate_version", f"this exact file is already the active version ({version_id})")
    if version is not None and version.status != "active":
        job = _latest_job(store, version.id)
        if job is not None and job.status in IN_FLIGHT:
            document = store.documents.upsert_document(document)
            return UploadResult(document, version, job, reused=True)

    document = store.documents.upsert_document(document)
    if storage is None:
        from pharmassist.ingest.storage import storage_from_config
        storage = storage_from_config(cfg)
    if queue is None:
        from pharmassist.ingest.queue import queue_from_config
        queue = queue_from_config(cfg)
    present = getattr(storage, "exists", None)
    if present is None or not present(key):
        storage.put_bytes(key, file_bytes, content_type=kind)

    reused = version is not None
    if version is None:
        version = DocumentVersion(id=version_id, document_id=document.id, sha256=sha, s3_key=key, file_name=name,
                                  content_type=kind, bytes=len(file_bytes), status="queued", pages=pages,
                                  created_by=requested_by)
        try:
            version = store.documents.create_version(version)
        except Conflict:   # raced with another upload of the same bytes
            version, reused = store.documents.version_by_sha(document.id, sha), True
    if reused:
        store.documents.set_version_status(version.id, "queued", error=None)
        version = store.documents.get_version(version.id) or version
    job = store.documents.create_job(version.id, requested_by)
    queue.send({"job_id": job.id, "version_id": version.id, "document_id": document.id})
    return UploadResult(document, version, job, reused=reused)
