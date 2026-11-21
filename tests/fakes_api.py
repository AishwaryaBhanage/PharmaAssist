"""Fakes for the API tests: an in-memory `Store` with the behaviour `pharmassist.store.protocols`
specifies (stream A's MemoryStore replaces it at integration), a semantic cache keyed on exact
embedding similarity, a scripted agent, and `build_app()` to assemble a TestClient-ready app.
Nothing here talks to a network, a database, a model or AWS."""

from __future__ import annotations

import math
import uuid
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.answer_service import AnswerService
from app.deps import Deps, LocalStorage
from app.limits import Limits, MemoryGuard
from app.server import create_app
from pharmassist.cache.base import CacheEntry, CacheHit
from pharmassist.config import load_config
from pharmassist.store.protocols import (Conflict, Conversation, Document, DocumentVersion, Feedback, FigureRecord,
                                         IngestionJob, Message, NotFound, Page, RefreshToken, User)

JWT_SECRET = "test-secret-" + "x" * 40
QUESTION = "Is Trulicity preferred under NY Medicaid for a new start?"
ANSWER = ("Assuming NY Medicaid: **Trulicity is preferred.** <script>alert(1)</script>\n\n"
          "1. Check the PDL.\n2. No PA needed.\n\n| Drug | Status |\n|---|---|\n| Trulicity | Preferred |")
PDL_URL = "https://newyork.fhsc.com/downloads/providers/NYRx_PDP_PDL.pdf"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Clock:
    """A settable clock (aware UTC) for token expiry and limits."""
    def __init__(self, start: datetime | None = None):
        self.now = start or utcnow()

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw) -> None:
        self.now += timedelta(**kw)

    def time(self) -> float:
        return self.now.timestamp()


# ---------------------------------------------------------------- store

class _Users:
    def __init__(self, store):
        self.s = store
        self.rows: dict[str, User] = {}

    def create(self, email, password_hash, role, display_name=""):
        if any(u.email.lower() == email.lower() for u in self.rows.values()):
            raise Conflict("email taken")
        u = User(id=str(uuid.uuid4()), email=email, display_name=display_name, role=role, is_active=True,
                 created_at=self.s.clock(), password_hash=password_hash)
        self.rows[u.id] = u
        return self._public(u)

    def _public(self, u):
        return replace(u, password_hash=None)

    def by_id(self, user_id):
        u = self.rows.get(user_id)
        return self._public(u) if u else None

    def by_email_for_login(self, email):
        return next((u for u in self.rows.values() if u.email.lower() == email.lower()), None)

    def touch_login(self, user_id):
        self.rows[user_id] = replace(self.rows[user_id], last_login_at=self.s.clock())

    def list(self, *, offset=0, limit=50, q=None):
        rows = sorted(self.rows.values(), key=lambda u: u.created_at)
        if q:
            rows = [u for u in rows if q.lower() in u.email.lower() or q.lower() in u.display_name.lower()]
        return Page(items=[self._public(u) for u in rows[offset:offset + limit]], total=len(rows), offset=offset,
                    limit=limit)

    def update(self, user_id, *, role=None, is_active=None, display_name=None):
        if user_id not in self.rows:
            raise NotFound(user_id)
        u = self.rows[user_id]
        u = replace(u, role=role if role is not None else u.role,
                    is_active=is_active if is_active is not None else u.is_active,
                    display_name=display_name if display_name is not None else u.display_name)
        self.rows[user_id] = u
        return self._public(u)

    def count(self, role=None):
        return sum(1 for u in self.rows.values() if role is None or u.role == role)


class _Tokens:
    def __init__(self, store):
        self.s = store
        self.rows: dict[str, RefreshToken] = {}

    def issue(self, user_id, token_hash, expires_at):
        t = RefreshToken(id=str(uuid.uuid4()), user_id=user_id, token_hash=token_hash, expires_at=expires_at,
                         created_at=self.s.clock())
        self.rows[t.id] = t
        return t

    def by_hash(self, token_hash):
        return next((t for t in self.rows.values() if t.token_hash == token_hash), None)

    def rotate(self, old_id, new_token_hash, expires_at):
        old = self.rows[old_id]
        new = self.issue(old.user_id, new_token_hash, expires_at)
        self.rows[old_id] = replace(old, revoked_at=self.s.clock(), replaced_by=new.id)
        return new

    def revoke(self, token_id):
        if token_id in self.rows and self.rows[token_id].revoked_at is None:
            self.rows[token_id] = replace(self.rows[token_id], revoked_at=self.s.clock())

    def revoke_all(self, user_id):
        n = 0
        for t in list(self.rows.values()):
            if t.user_id == user_id and t.revoked_at is None:
                self.revoke(t.id)
                n += 1
        return n

    def purge_expired(self):
        gone = [k for k, t in self.rows.items() if t.expires_at <= self.s.clock()]
        for k in gone:
            del self.rows[k]
        return len(gone)


class _Documents:
    def __init__(self, store):
        self.s = store
        self.docs: dict[str, Document] = {}
        self.versions: dict[str, DocumentVersion] = {}
        self.jobs: dict[str, IngestionJob] = {}
        self._generation = 1

    def upsert_document(self, doc):
        old = self.docs.get(doc.id)
        doc = replace(doc, created_at=old.created_at if old else self.s.clock(), updated_at=self.s.clock(),
                      active_version_id=doc.active_version_id if doc.active_version_id else (old.active_version_id if old else None))
        self.docs[doc.id] = doc
        return doc

    def get_document(self, doc_id):
        return self.docs.get(doc_id)

    def list_documents(self, *, include_inactive=True):
        docs = sorted(self.docs.values(), key=lambda d: d.id)
        return docs if include_inactive else [d for d in docs if d.active_version_id]

    def catalog(self):
        out = {}
        for d in self.docs.values():
            v = self.versions.get(d.active_version_id) if d.active_version_id else None
            if v is None:
                continue
            out[d.id] = {"title": d.title, "program": d.program, "doc_type": d.doc_type, "authority": d.authority,
                         "publisher": d.publisher, "date": d.doc_date, "source_url": d.source_url,
                         "file": v.file_name, "pages": v.pages, "version": v.id}
        return out

    def create_version(self, version):
        if self.version_by_sha(version.document_id, version.sha256):
            raise Conflict("duplicate version")
        version = replace(version, created_at=version.created_at or self.s.clock())
        self.versions[version.id] = version
        return version

    def get_version(self, version_id):
        return self.versions.get(version_id)

    def version_by_sha(self, document_id, sha256):
        return next((v for v in self.versions.values() if v.document_id == document_id and v.sha256 == sha256), None)

    def list_versions(self, document_id):
        return sorted((v for v in self.versions.values() if v.document_id == document_id),
                      key=lambda v: v.created_at or self.s.clock())

    def set_version_status(self, version_id, status, *, error=None, **fields):
        self.versions[version_id] = replace(self.versions[version_id], status=status, error=error, **fields)

    def activate(self, version_id):
        v = self.versions[version_id]
        if v.status != "verifying":
            raise Conflict("not verifying")
        doc = self.docs[v.document_id]
        if doc.active_version_id and doc.active_version_id in self.versions:
            self.versions[doc.active_version_id] = replace(self.versions[doc.active_version_id], status="superseded")
        self.versions[version_id] = replace(v, status="active", activated_at=self.s.clock())
        self.docs[doc.id] = replace(doc, active_version_id=version_id)
        self._generation += 1
        return self._generation

    def deactivate(self, doc_id):
        doc = self.docs.get(doc_id)
        if doc is None or not doc.active_version_id or doc.active_version_id not in self.versions:
            raise NotFound(doc_id)
        vid = doc.active_version_id
        removed = self.s.content.counts(vid)
        self.s.content.delete_version_content(vid)
        self.versions[vid] = replace(self.versions[vid], status="superseded")
        self.docs[doc_id] = replace(doc, active_version_id=None, updated_at=self.s.clock())
        self._generation += 1
        return {"document_id": doc_id, "version_id": vid, "removed": removed, "generation": self._generation}

    def active_versions(self):
        return {d.id: d.active_version_id for d in self.docs.values() if d.active_version_id}

    def generation(self):
        return self._generation

    def create_job(self, version_id, requested_by=None):
        j = IngestionJob(id=str(uuid.uuid4()), version_id=version_id, status="queued", queued_at=self.s.clock(),
                         requested_by=requested_by)
        self.jobs[j.id] = j
        return j

    def get_job(self, job_id):
        return self.jobs.get(job_id)

    def update_job(self, job_id, *, status=None, attempt=None, stage=None, error=None, worker_id=None,
                   started=False, heartbeat=False, finished=False):
        j = self.jobs[job_id]
        now = self.s.clock()
        j = replace(j, status=status or j.status, attempt=attempt if attempt is not None else j.attempt,
                    stage=stage if stage is not None else j.stage, error=error if error is not None else j.error,
                    worker_id=worker_id or j.worker_id, started_at=now if started else j.started_at,
                    heartbeat_at=now if heartbeat else j.heartbeat_at, finished_at=now if finished else j.finished_at)
        self.jobs[job_id] = j
        return j

    def list_jobs(self, *, version_id=None, status=None, offset=0, limit=50):
        rows = [j for j in self.jobs.values() if (version_id is None or j.version_id == version_id)
                and (status is None or j.status == status)]
        rows.sort(key=lambda j: j.queued_at or self.s.clock(), reverse=True)
        return Page(items=rows[offset:offset + limit], total=len(rows), offset=offset, limit=limit)


class _Content:
    """Only what the API reads: figures."""
    def __init__(self, store):
        self.s = store
        self.figures: list[FigureRecord] = []

    def _active(self, f):
        return self.s.documents.active_versions().get(f.document_id) == f.version_id

    def figures_for_page(self, document_id, page):
        return [f for f in self.figures if f.document_id == document_id and f.page == page and self._active(f)]

    def figure(self, document_id, figure_id):
        return next((f for f in self.figures if f.document_id == document_id and f.figure_id == figure_id
                     and self._active(f)), None)

    def counts(self, version_id):
        return {"chunks": 0, "parents": 0, "figures": sum(1 for f in self.figures if f.version_id == version_id),
                "table_rows": 0}

    def delete_version_content(self, version_id):
        self.figures = [f for f in self.figures if f.version_id != version_id]


class _Conversations:
    def __init__(self, store):
        self.s = store
        self.rows: dict[str, Conversation] = {}
        self.msgs: dict[str, Message] = {}

    def create(self, user_id, title):
        now = self.s.clock()
        c = Conversation(id=str(uuid.uuid4()), user_id=user_id, title=title, created_at=now, updated_at=now)
        self.rows[c.id] = c
        return c

    def _with_count(self, c):
        return replace(c, message_count=sum(1 for m in self.msgs.values() if m.conversation_id == c.id))

    def get(self, conversation_id, *, user_id=None):
        c = self.rows.get(conversation_id)
        if c is None or (user_id is not None and c.user_id != user_id):
            return None
        return self._with_count(c)

    def list_for_user(self, user_id, *, offset=0, limit=50):
        rows = sorted((c for c in self.rows.values() if c.user_id == user_id), key=lambda c: c.updated_at, reverse=True)
        return Page(items=[self._with_count(c) for c in rows[offset:offset + limit]], total=len(rows), offset=offset,
                    limit=limit)

    def delete(self, conversation_id, user_id):
        c = self.rows.get(conversation_id)
        if c is None or c.user_id != user_id:
            return False
        del self.rows[conversation_id]
        for k in [k for k, m in self.msgs.items() if m.conversation_id == conversation_id]:
            del self.msgs[k]
        return True

    def add_message(self, message):
        self.msgs[message.id] = message
        c = self.rows[message.conversation_id]
        self.rows[c.id] = replace(c, updated_at=self.s.clock())
        return message

    def _attach(self, m):
        return replace(m, feedback=self.s.feedback.get(m.id))

    def message(self, message_id, *, user_id=None):
        m = self.msgs.get(message_id)
        if m is None or (user_id is not None and m.user_id != user_id):
            return None
        return self._attach(m)

    def message_by_request(self, request_id):
        m = next((m for m in self.msgs.values() if m.request_id == request_id), None)
        return self._attach(m) if m else None

    def messages(self, conversation_id):
        rows = sorted((m for m in self.msgs.values() if m.conversation_id == conversation_id), key=lambda m: m.created_at)
        return [self._attach(m) for m in rows]

    def search_messages(self, *, rating=None, status=None, user_id=None, q=None, cached=None, since=None, until=None,
                        offset=0, limit=50):
        rows = [self._attach(m) for m in self.msgs.values()]
        if rating is not None:
            rows = [m for m in rows if m.feedback and m.feedback.rating == rating]
        if status is not None:
            rows = [m for m in rows if m.status == status]
        if user_id is not None:
            rows = [m for m in rows if m.user_id == user_id]
        if cached is not None:
            rows = [m for m in rows if m.cached == cached]
        if q:
            rows = [m for m in rows if q.lower() in m.question.lower() or q.lower() in m.answer.lower()]
        if since is not None:
            rows = [m for m in rows if m.created_at >= since]
        if until is not None:
            rows = [m for m in rows if m.created_at < until]
        rows.sort(key=lambda m: m.created_at, reverse=True)
        return Page(items=rows[offset:offset + limit], total=len(rows), offset=offset, limit=limit)


class _Feedback:
    def __init__(self, store):
        self.s = store
        self.rows: dict[str, Feedback] = {}

    def save(self, message_id, user_id, rating, reason, comment):
        if message_id not in self.s.conversations.msgs:
            raise NotFound(message_id)
        now = self.s.clock()
        old = self.rows.get(message_id)
        f = Feedback(id=old.id if old else str(uuid.uuid4()), message_id=message_id, user_id=user_id, rating=rating,
                     created_at=old.created_at if old else now, updated_at=now, reason=reason, comment=comment)
        self.rows[message_id] = f
        return f

    def get(self, message_id):
        return self.rows.get(message_id)


class _Stats:
    def __init__(self, store):
        self.s = store
        self.usage: dict[date, dict] = {}

    def overview(self, since, until):
        msgs = [m for m in self.s.conversations.msgs.values() if since <= m.created_at <= until]
        fb = [self.s.feedback.get(m.id) for m in msgs]
        fb = [f for f in fb if f]
        lat = sorted(m.latency_s for m in msgs if m.latency_s is not None)

        def pct(p):
            return lat[min(len(lat) - 1, int(p * len(lat)))] if lat else None
        per_day: dict[str, dict] = {}
        for m in msgs:
            d = per_day.setdefault(m.created_at.strftime("%Y-%m-%d"),
                                   {"day": m.created_at.strftime("%Y-%m-%d"), "questions": 0, "helpful": 0,
                                    "unhelpful": 0, "no_answer": 0, "cached": 0})
            d["questions"] += 1
            d["no_answer"] += m.status == "no_answer"
            d["cached"] += m.cached
            f = self.s.feedback.get(m.id)
            if f:
                d[f.rating] += 1
        return {"questions": len(msgs), "answered": sum(m.status == "answered" for m in msgs),
                "no_answer": sum(m.status == "no_answer" for m in msgs), "cached": sum(m.cached for m in msgs),
                "fallback": sum(m.fallback_used for m in msgs), "helpful": sum(f.rating == "helpful" for f in fb),
                "unhelpful": sum(f.rating == "unhelpful" for f in fb), "latency_p50_s": pct(0.5),
                "latency_p95_s": pct(0.95), "spend_usd": round(sum(m.cost_usd or 0 for m in msgs), 6),
                "active_users": len({m.user_id for m in msgs}), "per_day": sorted(per_day.values(), key=lambda d: d["day"])}

    def usage_day(self, day):
        return dict(self.usage.get(day, {"day": str(day), "questions": 0, "spend_usd": 0.0}))

    def add_usage(self, day, questions=0, spend_usd=0.0):
        u = self.usage.setdefault(day, {"day": str(day), "questions": 0, "spend_usd": 0.0})
        u["questions"] += questions
        u["spend_usd"] = round(u["spend_usd"] + spend_usd, 6)


class MemoryStore:
    def __init__(self, clock=utcnow):
        self.clock = clock
        self.users, self.tokens, self.documents = _Users(self), _Tokens(self), _Documents(self)
        self.content, self.conversations, self.feedback, self.stats = (_Content(self), _Conversations(self),
                                                                       _Feedback(self), _Stats(self))
        self.search = None
        self.alive, self.closed = True, False

    def ping(self):
        return self.alive

    def migrate(self):
        pass

    def close(self):
        self.closed = True

    # ---- test helpers ----
    def add_document(self, doc_id="ny_medicaid_pdl", title="NYRx Medicaid Preferred Drug List", program="NY Medicaid",
                     file_name=None, pages=120, source_url=PDL_URL, sha="a" * 64, status="active", **kw) -> Document:
        doc = self.documents.upsert_document(Document(id=doc_id, title=title, program=program, doc_type="formulary",
                                                      authority="binding", publisher="NYS DOH", doc_date="2026-01",
                                                      source_url=source_url, **kw))
        file_name = file_name or f"{doc_id}.pdf"
        v = self.documents.create_version(DocumentVersion(
            id=f"{doc_id}:{sha[:16]}", document_id=doc_id, sha256=sha, s3_key=f"sources/{doc_id}/{sha[:16]}/{file_name}",
            file_name=file_name, content_type="application/pdf", bytes=1234, status="verifying", pages=pages))
        if status == "active":
            self.documents.activate(v.id)
        else:
            self.documents.set_version_status(v.id, status)
        return self.documents.get_document(doc_id)

    def add_figure(self, doc_id, page, name="p034_f1.png", figure_id=None, status="ocr_checked") -> FigureRecord:
        vid = self.documents.active_versions()[doc_id]
        f = FigureRecord(version_id=vid, figure_id=figure_id or f"{doc_id}:p{page:03d}_f1", document_id=doc_id,
                         page=page, kind="flowchart", status=status, record={}, title="Step therapy",
                         crop_s3_key=f"figures/{doc_id}/{name}")
        self.content.figures.append(f)
        return f


# ---------------------------------------------------------------- cache, agent, storage

def cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class FakeCache:
    name = "memory-fake"

    def __init__(self, threshold=0.90, clock=utcnow):
        self.threshold, self.clock = threshold, clock
        self.entries: dict[str, tuple[CacheEntry, list[float]]] = {}
        self.hits = self.misses = 0
        self.alive = True
        self.fail = False

    def lookup(self, embedding, generation):
        if self.fail:
            raise RuntimeError("cache down")
        best = None
        for e, emb in self.entries.values():
            if e.generation != generation:
                continue
            sim = cosine(embedding, emb)
            if sim >= self.threshold and (best is None or sim > best[1]):
                best = (e, sim)
        if best is None:
            self.misses += 1
            return None
        e, sim = best
        e.hits += 1
        e.last_hit_at = self.clock()
        self.hits += 1
        return CacheHit(entry=e, similarity=sim)

    def put(self, entry, embedding):
        if entry.status != "answered" or not entry.citations:
            raise ValueError("only answered, cited answers are cached")
        self.entries[entry.id] = (entry, list(embedding))
        return entry.id

    def get(self, entry_id):
        e = self.entries.get(entry_id)
        return e[0] if e else None

    def delete(self, entry_id):
        return self.entries.pop(entry_id, None) is not None

    def invalidate(self, *, before_generation=None):
        gone = [k for k, (e, _) in self.entries.items() if before_generation is None or e.generation < before_generation]
        for k in gone:
            del self.entries[k]
        return len(gone)

    def stats(self):
        total = self.hits + self.misses
        return {"entries": len(self.entries), "hits": self.hits, "misses": self.misses,
                "hit_rate": round(self.hits / total, 4) if total else 0.0, "threshold": self.threshold,
                "generation": None, "backend": self.name, "cleared_at": getattr(self, "cleared_at", None)}

    def reset_stats(self):
        self.hits = self.misses = 0
        self.cleared_at = self.clock().isoformat(timespec="seconds")

    def ping(self):
        return self.alive


def agent_result(status="answered", citations=None, needs_review=False, **kw) -> dict:
    """What stream B's loop.ask returns."""
    cites = citations if citations is not None else [
        {"doc_id": "ny_medicaid_pdl", "page": 34, "link": f"{PDL_URL}#page=34", "flag": None, "locator": "ny_medicaid_pdl:p34"},
        {"doc_id": "va_national_formulary_2026_09", "page": None, "link": None, "flag": None,
         "locator": "va_national_formulary_2026_09:r1697", "row": 1697},
        {"doc_id": "ny_medicaid_pdl", "page": 99, "link": f"{PDL_URL}#page=99",
         "flag": "not returned by any tool during this question", "locator": "ny_medicaid_pdl:p99"}]
    out = {"question": QUESTION, "status": status, "agent_status": status,
           "answer": ANSWER if status == "answered" else "No answer found in knowledge base",
           "assumption": "Assuming NY Medicaid" if status == "answered" else None,
           "citations": cites if status == "answered" else [], "conflicts_noted": [], "flags": [],
           "needs_review": needs_review, "provider": "openai", "model": "gpt-5.5", "fallback_used": False,
           "trace_id": "trace-1", "cost_usd": 0.05, "tokens": {"input": 1200, "output": 300},
           "timing_s": {"total": 12.34}, "answered_by": "gpt-5.5"}
    out.update(kw)
    return out


class FakeAgent:
    def __init__(self, result=None, delay=0.0, error=None):
        self.calls, self.result, self.delay, self.error = [], result or agent_result(), delay, error

    def __call__(self, question, **kw):
        self.calls.append({"question": question, **kw})
        if self.delay:
            import time
            time.sleep(self.delay)
        if self.error:
            raise self.error
        return self.result


def embed_words(text: str) -> list[float]:
    """A deterministic bag-of-words embedding: identical texts are identical, unrelated texts far apart."""
    import hashlib
    dims = 64
    v = [0.0] * dims
    for w in text.lower().split():
        v[int(hashlib.md5(w.encode()).hexdigest(), 16) % dims] += 1.0
    return v


class FakeStorage(LocalStorage):
    """Local objects, plus a switch to behave like S3 (presigned URLs) without AWS."""
    def __init__(self, root: Path, presign_base: str | None = None):
        super().__init__(root)
        self.presign_base = presign_base
        self.presigned: list[str] = []

    def presign(self, key, *, content_type=None, fragment=None):
        if not self.presign_base:
            return None
        self.presigned.append(key)
        url = f"{self.presign_base}/{key}?X-Amz-Signature=fake"
        return f"{url}#{fragment}" if fragment else url


# ---------------------------------------------------------------- app builder

def test_config(**overrides) -> dict:
    cfg = dict(load_config())
    cfg["app"] = {**cfg["app"], "timeout_s": 2, "max_concurrent": 2, "question_chars": [3, 2000],
                  "max_body_bytes": 16384}
    cfg["limits_v2"] = {"per_user_per_minute": 10, "per_user_per_day": 100, "questions_per_day": 500,
                        "spend_usd_per_day": 10.0, "estimate_usd": 0.08}
    cfg["auth"] = {**cfg["auth"], "access_token_minutes": 15, "refresh_token_days": 14}
    for k, v in overrides.items():
        cfg[k] = {**cfg.get(k, {}), **v} if isinstance(v, dict) else v
    return cfg


def build_deps(tmp_path: Path | None = None, *, agent=None, cache=None, store=None, clock=None, cfg=None,
               storage=None, limiter=None, embed=embed_words, submit_upload=None, frontend_dir=None) -> Deps:
    clock = clock or Clock()
    cfg = cfg or test_config()
    store = store or MemoryStore(clock)
    cache = cache if cache is not None else FakeCache(clock=clock)
    agent = agent or FakeAgent()
    root = Path(tmp_path) if tmp_path else Path("/nonexistent")
    answers = AnswerService(cfg, ask_fn=agent, embed_fn=embed, store=store)
    limiter = limiter or MemoryGuard(Limits.from_config(cfg["limits_v2"]), salt="s", clock=clock.time)
    return Deps(cfg=cfg, store=store, cache=cache, answers=answers, limiter=limiter,
                storage=storage or FakeStorage(root / "objects"), jwt_secret=JWT_SECRET, clock=clock,
                submit_upload=submit_upload, insecure_cookies=False,
                frontend_dir=frontend_dir or root / "frontend-missing", docs_dir=root / "docs",
                figures_dir=root / "figures")


def build_app(tmp_path=None, **kw):
    deps = build_deps(tmp_path, **kw)
    return create_app(deps), deps


# ---------------------------------------------------------------- client helpers

def client(app, raise_server_exceptions=True):
    """An https base URL, so the Secure refresh cookie is sent back."""
    from fastapi.testclient import TestClient
    return TestClient(app, base_url="https://testserver", raise_server_exceptions=raise_server_exceptions)


def make_user(deps: Deps, email: str, password: str = "correct horse battery", role: str = "staff",
              display_name: str = "") -> User:
    from app.auth import hash_password
    return deps.store.users.create(email, hash_password(password), role, display_name)


def login(http, email: str, password: str = "correct horse battery") -> dict:
    r = http.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def staff_and_admin(deps: Deps, http) -> tuple[dict, dict]:
    make_user(deps, "staff@example.com")
    make_user(deps, "admin@example.com", role="admin")
    return login(http, "staff@example.com"), login(http, "admin@example.com")
