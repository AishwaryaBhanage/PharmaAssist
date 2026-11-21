"""Test doubles for the v2 ingestion pipeline: an in-memory Store (the DocumentRepo and ContentRepo
methods the pipeline uses, with the protocol's rules), a parser that needs no Docling, a scripted
vision model, a deterministic 3,072-dim embedder, and a queue that records its calls."""

import hashlib
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pymupdf

from pharmassist.embedders.base import TransientError
from pharmassist.ingest.pipeline import Tools
from pharmassist.ingest.queue import MemoryQueue
from pharmassist.store.protocols import (Conflict, Document, DocumentVersion, IngestionJob, NotFound, Page)

DIM = 3072
SMALL_PDF = "cms_partd_opioid_pharmacists_2022.pdf"   # 2 pages: fast to chunk
FLOW = {"kind": "flowchart", "title": "Figure 1. Coverage decision", "unreadable": [],
        "nodes": [{"id": "1", "shape": "start", "text": "Prescription received"},
                  {"id": "2", "shape": "decision", "text": "Opioid over the limit?"},
                  {"id": "3", "shape": "end", "text": "Dispense"},
                  {"id": "4", "shape": "action", "text": "Contact prescriber"}],
        "edges": [{"from": "1", "to": "2"}, {"from": "2", "to": "3", "label": "No"}, {"from": "2", "to": "4", "label": "Yes"}]}
FLOW_OCR = ["Figure 1. Coverage decision", "Prescription received", "Opioid over the limit?", "Yes", "No", "Dispense",
            "Contact prescriber"]


def now():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- store

class FakeDocuments:
    def __init__(self, store):
        self.s = store
        self.docs: dict[str, Document] = {}
        self.versions: dict[str, DocumentVersion] = {}
        self.jobs: dict[str, IngestionJob] = {}
        self.history: dict[str, list[str]] = {}   # version id -> every status it was given
        self._generation = 1
        self._tick = 0

    def _ts(self):
        # strictly increasing timestamps, so "created later" is unambiguous within one test
        self._tick += 1
        return now() + timedelta(microseconds=self._tick)

    # documents
    def upsert_document(self, doc):
        with self.s.lock:
            old = self.docs.get(doc.id)
            doc.created_at = (old.created_at if old else None) or self._ts()
            doc.updated_at = self._ts()
            if old:
                doc.active_version_id = old.active_version_id
            self.docs[doc.id] = doc
            return doc

    def get_document(self, doc_id):
        return self.docs.get(doc_id)

    def list_documents(self, *, include_inactive=True):
        return [d for d in self.docs.values() if include_inactive or d.active_version_id]

    def catalog(self):
        raise NotImplementedError

    # versions
    def create_version(self, version):
        with self.s.lock:
            if version.id in self.versions or any(v.document_id == version.document_id and v.sha256 == version.sha256
                                                  for v in self.versions.values()):
                raise Conflict(f"version {version.id} exists")
            version.created_at = self._ts()
            self.versions[version.id] = version
            self.history[version.id] = [version.status]
            return version

    def get_version(self, version_id):
        return self.versions.get(version_id)

    def version_by_sha(self, document_id, sha256):
        return next((v for v in self.versions.values() if v.document_id == document_id and v.sha256 == sha256), None)

    def list_versions(self, document_id):
        return sorted((v for v in self.versions.values() if v.document_id == document_id), key=lambda v: v.created_at)

    def set_version_status(self, version_id, status, *, error=None, **fields):
        with self.s.lock:
            v = self.versions[version_id]
            v.status, v.error = status, error
            for k, val in fields.items():
                setattr(v, k, val)
            self.history[version_id].append(status)

    def activate(self, version_id):
        with self.s.lock:
            v = self.versions[version_id]
            if v.status != "verifying":
                raise Conflict(f"version {version_id} is {v.status}, not verifying")
            doc = self.docs[v.document_id]
            if doc.active_version_id and doc.active_version_id != version_id and doc.active_version_id in self.versions:
                prev = self.versions[doc.active_version_id]
                prev.status = "superseded"
                self.history[prev.id].append("superseded")
            v.status, v.activated_at = "active", now()
            self.history[version_id].append("active")
            doc.active_version_id = version_id
            self._generation += 1
            return self._generation

    def active_versions(self):
        return {d.id: d.active_version_id for d in self.docs.values() if d.active_version_id}

    def generation(self):
        return self._generation

    # jobs
    def create_job(self, version_id, requested_by=None):
        with self.s.lock:
            job = IngestionJob(id=uuid.uuid4().hex, version_id=version_id, status="queued", queued_at=self._ts(),
                               requested_by=requested_by)
            self.jobs[job.id] = job
            return job

    def get_job(self, job_id):
        return self.jobs.get(job_id)

    def update_job(self, job_id, *, status=None, attempt=None, stage=None, error=None, worker_id=None,
                   started=False, heartbeat=False, finished=False):
        with self.s.lock:
            j = self.jobs.get(job_id)
            if j is None:
                raise NotFound(job_id)
            if status is not None:
                j.status = status
            if attempt is not None:
                j.attempt = attempt
            if stage is not None:
                j.stage = stage
            if error is not None or status is not None:
                j.error = error
            if worker_id is not None:
                j.worker_id = worker_id
            if started:
                j.started_at = now()
            if heartbeat:
                j.heartbeat_at = now()
            if finished:
                j.finished_at = now()
            return j

    def list_jobs(self, *, version_id=None, status=None, offset=0, limit=50):
        items = [j for j in self.jobs.values() if (version_id is None or j.version_id == version_id)
                 and (status is None or j.status == status)]
        items.sort(key=lambda j: j.queued_at, reverse=True)   # newest first
        return Page(items[offset:offset + limit], len(items), offset, limit)


class FakeContent:
    def __init__(self, store):
        self.s = store
        self.parents, self.chunks, self.figures, self.table_rows = {}, {}, {}, {}
        self.fail_puts = False

    def _put(self, table, rows, key):
        if self.fail_puts:
            raise RuntimeError("simulated database error")
        with self.s.lock:
            for r in rows:
                table[key(r)] = r
        return len(rows)

    def put_parents(self, rows):
        return self._put(self.parents, rows, lambda r: (r.version_id, r.parent_id))

    def put_chunks(self, rows):
        for r in rows:
            if r.embedding is None or len(r.embedding) != DIM:
                raise ValueError(f"chunk {r.chunk_id}: embedding of dimension {len(r.embedding or [])}, expected {DIM}")
        return self._put(self.chunks, rows, lambda r: (r.version_id, r.chunk_id))

    def put_figures(self, rows):
        return self._put(self.figures, rows, lambda r: (r.version_id, r.figure_id))

    def put_table_rows(self, rows):
        return self._put(self.table_rows, rows, lambda r: (r.version_id, r.table_name, r.row_no))

    def delete_version_content(self, version_id):
        with self.s.lock:
            for table in (self.parents, self.chunks, self.figures, self.table_rows):
                for k in [k for k in table if k[0] == version_id]:
                    del table[k]

    def counts(self, version_id):
        return {name: sum(1 for k in table if k[0] == version_id) for name, table in
                (("chunks", self.chunks), ("parents", self.parents), ("figures", self.figures),
                 ("table_rows", self.table_rows))}

    def iter_chunks(self, version_id, *, with_embeddings=False):
        for (vid, _), c in self.chunks.items():
            if vid == version_id:
                yield c

    def figures_for_page(self, document_id, page):
        active = self.s.documents.active_versions().get(document_id)
        return [f for (vid, _), f in self.figures.items() if vid == active and f.page == page]

    def table_rows_of(self, version_id, table_name):
        return [r for (vid, t, _), r in sorted(self.table_rows.items()) if vid == version_id and t == table_name]


class FakeStore:
    def __init__(self):
        self.lock = threading.RLock()
        self.documents = FakeDocuments(self)
        self.content = FakeContent(self)

    def ping(self):
        return True

    def close(self):
        pass


# ---------------------------------------------------------------- pipeline doubles

def fake_parse(path, doc_id, figures_dir):
    """Blocks from the PDF's own text layer (no Docling) plus one synthetic flowchart figure on
    page 1 whose crop is rendered from the page, in the shape docling_parser.convert returns."""
    path, figures_dir = Path(path), Path(figures_dir)
    if path.suffix != ".pdf" or b"%PDF" not in path.read_bytes()[:1024]:
        raise ValueError("not a PDF")
    blocks, pages = [], 0
    with pymupdf.open(path) as pdf:
        pages = pdf.page_count
        for i, page in enumerate(pdf):
            for b in page.get_text("blocks"):
                text = " ".join(b[4].split())
                if text:
                    blocks.append({"page": i + 1, "type": "text", "text": text, "rows": None,
                                   "bbox": [round(x, 1) for x in b[:4]], "header_rows": 0, "caption": None,
                                   "footnotes": None, "label": "text", "extraction": "docling_text",
                                   "figure_id": None, "verification": None})
        figures_dir.mkdir(parents=True, exist_ok=True)
        crop = figures_dir / "p001_f0.png"
        pdf[0].get_pixmap(clip=pymupdf.Rect(50, 50, 300, 250), dpi=72).save(crop)
    fid = f"{doc_id}:p1:f0"
    blocks.append({"page": 1, "type": "figure", "text": None, "rows": None, "bbox": [50.0, 50.0, 300.0, 250.0],
                   "header_rows": 0, "caption": None, "footnotes": None, "label": None, "extraction": "pending",
                   "figure_id": fid, "verification": None})
    figures = [{"figure_id": fid, "page": 1, "bbox": [50.0, 50.0, 300.0, 250.0], "source": "docling",
                "classes": [["flow_chart", 0.95]], "caption": None, "ocr_text": list(FLOW_OCR),
                "crop": str(crop), "size_px": [250, 200]},
               {"figure_id": f"{doc_id}:p1:f1", "page": 1, "bbox": [500.0, 20.0, 540.0, 60.0], "source": "docling",
                "classes": [["logo", 0.99]], "caption": None, "ocr_text": [], "crop": None, "size_px": [40, 40]}]
    return {"blocks": blocks, "figures": figures, "seconds": 0.1, "pages": pages}


class FakeVision:
    def __init__(self, record=None, fail=None):
        self.record, self.fail, self.calls = record or FLOW, fail, []

    def __call__(self, fig, entry):
        self.calls.append(fig["figure_id"])
        if self.fail:
            raise self.fail
        return {"record": dict(self.record), "model": "fake-vision", "cached": False,
                "usage": {"input_tokens": 1000, "output_tokens": 500}}


def fake_ocr(crop):
    return list(FLOW_OCR)


def word_spans(text):
    return [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]


class HashEmbed:
    """Deterministic 3,072-dim unit vectors from hashed words; `fail_times` first calls raise a
    TransientError (what the OpenAI embedder raises once its own retries are spent)."""
    model_name = "fake-3072"

    def __init__(self, fail_times=0, always_fail=False):
        self.fail_times, self.always_fail, self.calls = fail_times, always_fail, 0

    def __call__(self, texts):
        self.calls += 1
        if self.always_fail or self.fail_times > 0:
            self.fail_times -= 1
            raise TransientError("RateLimitError after 6 attempts")
        out = []
        for t in texts:
            v = [0.0] * DIM
            for w in re.findall(r"[a-z0-9]+", t.lower()):
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % DIM] += 1.0
            n = sum(x * x for x in v) ** 0.5 or 1.0
            out.append([x / n for x in v])
        return out


def fake_tools(vision=None, parse=fake_parse, ocr=fake_ocr):
    return Tools(parse_fn=parse, vision_fn=vision or FakeVision(), ocr_fn=ocr, token_spans=word_spans,
                 sleep=lambda s: None)


class RecordingQueue(MemoryQueue):
    """MemoryQueue that records every call, for heartbeat and outcome assertions."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.calls = []

    def extend_visibility(self, msg, seconds):
        self.calls.append(("extend", seconds))
        super().extend_visibility(msg, seconds)

    def retry_later(self, msg, delay_s):
        self.calls.append(("retry", delay_s))
        super().retry_later(msg, delay_s)

    def dead_letter(self, msg, reason):
        self.calls.append(("dead_letter", reason))
        super().dead_letter(msg, reason)

    def ack(self, msg):
        self.calls.append(("ack", None))
        super().ack(msg)


def document(doc_id="cms_partd_opioid_pharmacists_2022", **kw):
    base = dict(id=doc_id, title="Medicare Part D Opioid Policies: Information for Pharmacists",
                program="Medicare Part D", doc_type="pharmacist guidance", authority="summary_of_binding_policy",
                publisher="CMS", doc_date="2022-12-19")
    base.update(kw)
    return Document(**base)


def world(tmp_path, cfg, **queue_kw):
    """A store, local storage, recording queue and fake tools wired together."""
    from pharmassist.ingest.storage import LocalStorage
    return SimpleNamespace(store=FakeStore(), storage=LocalStorage(tmp_path / "objects"),
                           queue=RecordingQueue(**queue_kw), tools=fake_tools(), embed=HashEmbed(), cfg=cfg)
