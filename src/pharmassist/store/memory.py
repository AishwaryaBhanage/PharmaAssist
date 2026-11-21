"""An in-memory store with PgStore's behaviour, for unit tests in every stream.

Same protocols, same error types, same visibility rule (readers see active versions only), same
transactional outcomes (an `activate` either moves everything or nothing). Dense search is exact
cosine with numpy; keyword search is a token-overlap rank that mimics `websearch_to_tsquery` (every
query term must occur) with idf weights in place of `ts_rank_cd`. Nothing here is persisted.
"""

from __future__ import annotations

import math
import re
import uuid
from dataclasses import replace
from datetime import datetime, timezone

import numpy as np

from pharmassist.store.protocols import (ChunkRecord, Conflict, Conversation, Document, DocumentVersion, Feedback,
                                         IngestionJob, Message, NotFound, Page, RefreshToken, SearchHit, User)

VERSION_STATUSES = ("queued", "parsing", "extracting_figures", "chunking", "embedding", "verifying", "active", "failed",
                    "superseded")
JOB_STATUSES = ("queued", "running", "succeeded", "failed", "dead_letter", "skipped")
VERSION_FIELDS = ("pages", "parser_version", "chunker_version", "embedder_model", "embedding_dim", "chunk_count",
                  "figure_count")
_TOKEN = re.compile(r"[a-z0-9]+")
# the common words PostgreSQL's 'english' configuration drops; enough for the rank to behave alike
STOPWORDS = set("a an and are as at be but by for from has have if in into is it its no not of on or such that the "
                "their then there these they this to was were will with what which who whom how when where why "
                "does do did can could should would may might must shall".split())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


def _stem(tok: str) -> str:
    """A crude stand-in for the Snowball stemmer: plural and -ing/-ed endings."""
    for suffix in ("ing", "ies", "es", "ed", "s"):
        if tok.endswith(suffix) and len(tok) - len(suffix) >= 3:
            return tok[:-len(suffix)] + ("y" if suffix == "ies" else "")
    return tok


def tokens(text: str) -> list[str]:
    return [_stem(t) for t in _TOKEN.findall(text.lower()) if t not in STOPWORDS]


class _Repo:
    def __init__(self, store: "MemoryStore"):
        self.s = store


# ---------------------------------------------------------------- users and tokens

class MemUsers(_Repo):
    def create(self, email, password_hash, role, display_name=""):
        if role not in ("staff", "admin"):
            raise ValueError(f"invalid role {role!r}")
        if any(u.email.lower() == email.lower() for u in self.s.users_.values()):
            raise Conflict(f"email already registered: {email.lower()}")
        u = User(id=_uuid(), email=email, display_name=display_name, role=role, is_active=True, created_at=utcnow(),
                 password_hash=password_hash)
        self.s.users_[u.id] = u
        return replace(u, password_hash=None)

    def by_id(self, user_id):
        u = self.s.users_.get(user_id)
        return replace(u, password_hash=None) if u else None

    def by_email_for_login(self, email):
        return next((replace(u) for u in self.s.users_.values() if u.email.lower() == email.lower()), None)

    def touch_login(self, user_id):
        if user_id in self.s.users_:
            self.s.users_[user_id].last_login_at = utcnow()

    def list(self, *, offset=0, limit=50, q=None):
        us = [u for u in self.s.users_.values()
              if q is None or q.lower() in u.email.lower() or q.lower() in u.display_name.lower()]
        us.sort(key=lambda u: (u.created_at, u.email))
        return Page(items=[replace(u, password_hash=None) for u in us[offset:offset + limit]], total=len(us),
                    offset=offset, limit=limit)

    def update(self, user_id, *, role=None, is_active=None, display_name=None):
        u = self.s.users_.get(user_id)
        if u is None:
            raise NotFound(f"user {user_id}")
        if role is not None:
            u.role = role
        if is_active is not None:
            u.is_active = is_active
        if display_name is not None:
            u.display_name = display_name
        return replace(u, password_hash=None)

    def count(self, role=None):
        return sum(1 for u in self.s.users_.values() if role is None or u.role == role)


class MemTokens(_Repo):
    def issue(self, user_id, token_hash, expires_at):
        t = RefreshToken(id=_uuid(), user_id=user_id, token_hash=token_hash, expires_at=expires_at, created_at=utcnow())
        self.s.tokens_[t.id] = t
        return replace(t)

    def by_hash(self, token_hash):
        return next((replace(t) for t in self.s.tokens_.values() if t.token_hash == token_hash), None)

    def rotate(self, old_id, new_token_hash, expires_at):
        old = self.s.tokens_.get(old_id)
        if old is None:
            raise NotFound(f"refresh token {old_id}")
        new = self.issue(old.user_id, new_token_hash, expires_at)
        old.revoked_at, old.replaced_by = old.revoked_at or utcnow(), new.id
        return new

    def revoke(self, token_id):
        t = self.s.tokens_.get(token_id)
        if t and t.revoked_at is None:
            t.revoked_at = utcnow()

    def revoke_all(self, user_id):
        n = 0
        for t in self.s.tokens_.values():
            if t.user_id == user_id and t.revoked_at is None:
                t.revoked_at, n = utcnow(), n + 1
        return n

    def purge_expired(self):
        now = utcnow()
        gone = [i for i, t in self.s.tokens_.items() if t.expires_at < now]
        for i in gone:
            del self.s.tokens_[i]
        return len(gone)


# ---------------------------------------------------------------- documents, versions, jobs

class MemDocuments(_Repo):
    def upsert_document(self, doc):
        cur = self.s.documents_.get(doc.id)
        now = utcnow()
        if cur is None:
            cur = replace(doc, created_at=now, updated_at=now, active_version_id=None)
        else:
            cur = replace(cur, title=doc.title, program=doc.program, doc_type=doc.doc_type, authority=doc.authority,
                          publisher=doc.publisher, doc_date=doc.doc_date, source_url=doc.source_url, updated_at=now)
        self.s.documents_[doc.id] = cur
        return replace(cur)

    def get_document(self, doc_id):
        d = self.s.documents_.get(doc_id)
        return replace(d) if d else None

    def list_documents(self, *, include_inactive=True):
        return [replace(d) for i, d in sorted(self.s.documents_.items())
                if include_inactive or d.active_version_id is not None]

    def catalog(self):
        out = {}
        for i, d in sorted(self.s.documents_.items()):
            v = self.s.versions_.get(d.active_version_id) if d.active_version_id else None
            if v:
                out[i] = {"id": i, "title": d.title, "program": d.program, "doc_type": d.doc_type,
                          "authority": d.authority, "publisher": d.publisher, "date": d.doc_date,
                          "source_url": d.source_url, "file": v.file_name, "pages": v.pages, "version": v.id}
        return out

    def create_version(self, v):
        if v.document_id not in self.s.documents_:
            raise NotFound(f"document {v.document_id}")
        if v.id in self.s.versions_ or any(x.document_id == v.document_id and x.sha256 == v.sha256
                                           for x in self.s.versions_.values()):
            raise Conflict(f"version {v.id} of {v.document_id} already exists")
        if v.status not in VERSION_STATUSES:
            raise ValueError(f"invalid version status {v.status!r}")
        v = replace(v, created_at=utcnow())
        self.s.versions_[v.id] = v
        return replace(v)

    def get_version(self, version_id):
        v = self.s.versions_.get(version_id)
        return replace(v) if v else None

    def version_by_sha(self, document_id, sha256):
        return next((replace(v) for v in self.s.versions_.values() if v.document_id == document_id and v.sha256 == sha256),
                    None)

    def list_versions(self, document_id):
        vs = [v for v in self.s.versions_.values() if v.document_id == document_id]
        return [replace(v) for v in sorted(vs, key=lambda v: (v.created_at, v.id), reverse=True)]

    def set_version_status(self, version_id, status, *, error=None, **fields):
        bad = set(fields) - set(VERSION_FIELDS)
        if bad:
            raise ValueError(f"unknown version fields: {sorted(bad)}")
        if status not in VERSION_STATUSES:
            raise ValueError(f"invalid version status {status!r}")
        v = self.s.versions_.get(version_id)
        if v is None:
            raise NotFound(f"version {version_id}")
        self.s.versions_[version_id] = replace(v, status=status, error=error, **fields)

    def activate(self, version_id):
        v = self.s.versions_.get(version_id)
        if v is None:
            raise NotFound(f"version {version_id}")
        if v.status != "verifying":
            raise Conflict(f"version {version_id} is {v.status!r}, not 'verifying'")
        d = self.s.documents_[v.document_id]
        prev = d.active_version_id
        if prev and prev != version_id and prev in self.s.versions_:
            self.s.versions_[prev] = replace(self.s.versions_[prev], status="superseded")
        now = utcnow()
        self.s.versions_[version_id] = replace(v, status="active", activated_at=now, error=None)
        self.s.documents_[d.id] = replace(d, active_version_id=version_id, updated_at=now)
        self.s.generation_ += 1
        return self.s.generation_

    def deactivate(self, doc_id):
        d = self.s.documents_.get(doc_id)
        if d is None or d.active_version_id is None or d.active_version_id not in self.s.versions_:
            raise NotFound(f"document {doc_id} has no active version")
        vid = d.active_version_id
        removed = self.s.content.counts(vid)
        self.s.content.delete_version_content(vid)
        self.s.versions_[vid] = replace(self.s.versions_[vid], status="superseded")
        self.s.documents_[doc_id] = replace(d, active_version_id=None, updated_at=utcnow())
        self.s.generation_ += 1
        return {"document_id": doc_id, "version_id": vid, "removed": removed, "generation": self.s.generation_}

    def active_versions(self):
        return {i: d.active_version_id for i, d in self.s.documents_.items() if d.active_version_id}

    def generation(self):
        return self.s.generation_

    def create_job(self, version_id, requested_by=None):
        if version_id not in self.s.versions_:
            raise NotFound(f"version {version_id}")
        j = IngestionJob(id=_uuid(), version_id=version_id, status="queued", queued_at=utcnow(), requested_by=requested_by)
        self.s.jobs_[j.id] = j
        return replace(j)

    def get_job(self, job_id):
        j = self.s.jobs_.get(job_id)
        return replace(j) if j else None

    def update_job(self, job_id, *, status=None, attempt=None, stage=None, error=None, worker_id=None,
                   started=False, heartbeat=False, finished=False):
        j = self.s.jobs_.get(job_id)
        if j is None:
            raise NotFound(f"job {job_id}")
        if status is not None and status not in JOB_STATUSES:
            raise ValueError(f"invalid job status {status!r}")
        now = utcnow()
        for k, v in (("status", status), ("attempt", attempt), ("stage", stage), ("error", error), ("worker_id", worker_id)):
            if v is not None:
                setattr(j, k, v)
        for flag, k in ((started, "started_at"), (heartbeat, "heartbeat_at"), (finished, "finished_at")):
            if flag:
                setattr(j, k, now)
        return replace(j)

    def list_jobs(self, *, version_id=None, status=None, offset=0, limit=50):
        js = [j for j in self.s.jobs_.values() if (version_id is None or j.version_id == version_id)
              and (status is None or j.status == status)]
        js.sort(key=lambda j: (j.queued_at, j.id), reverse=True)
        return Page(items=[replace(j) for j in js[offset:offset + limit]], total=len(js), offset=offset, limit=limit)


# ---------------------------------------------------------------- content

class MemContent(_Repo):
    def put_parents(self, rows):
        for p in rows:
            self.s.parents_[(p.version_id, p.parent_id)] = replace(p, section_path=list(p.section_path),
                                                                  metadata=dict(p.metadata or {}))
        return len(rows)

    def put_chunks(self, rows):
        dim = self.s.dim
        for c in rows:
            if c.embedding is None or len(c.embedding) != dim:
                got = "none" if c.embedding is None else len(c.embedding)
                raise ValueError(f"chunk {c.chunk_id}: embedding dimension {got}, expected {dim}")
        for c in rows:
            self.s.chunks_[(c.version_id, c.chunk_id)] = replace(
                c, embedding=np.asarray(c.embedding, dtype=np.float32), section_path=list(c.section_path),
                content_types=list(c.content_types), figure_ids=list(c.figure_ids), metadata=dict(c.metadata or {}))
        return len(rows)

    def put_figures(self, rows):
        for f in rows:
            self.s.figures_[(f.version_id, f.figure_id)] = replace(f, record=dict(f.record))
        return len(rows)

    def put_table_rows(self, rows):
        for t in rows:
            if t.table_name not in ("va_formulary", "ny_pdl"):
                raise ValueError("table_name must be va_formulary or ny_pdl")
            self.s.table_rows_[(t.version_id, t.table_name, t.row_no)] = replace(t, row=dict(t.row))
        return len(rows)

    def delete_version_content(self, version_id):
        for table in (self.s.chunks_, self.s.parents_, self.s.figures_, self.s.table_rows_):
            for k in [k for k in table if k[0] == version_id]:
                del table[k]

    def counts(self, version_id):
        return {"chunks": sum(1 for k in self.s.chunks_ if k[0] == version_id),
                "parents": sum(1 for k in self.s.parents_ if k[0] == version_id),
                "figures": sum(1 for k in self.s.figures_ if k[0] == version_id),
                "table_rows": sum(1 for k in self.s.table_rows_ if k[0] == version_id)}

    def chunks_by_ids(self, ids):
        return {k: replace(self.s.chunks_[k], embedding=None) for k in ids if k in self.s.chunks_}

    def parents_by_ids(self, ids):
        return {k: replace(self.s.parents_[k]) for k in ids if k in self.s.parents_}

    def _active_chunks(self):
        active = self.s.documents.active_versions()
        return [c for c in self.s.chunks_.values() if active.get(c.document_id) == c.version_id]

    def figures_for_page(self, document_id, page):
        active = self.s.documents.active_versions().get(document_id)
        fs = [f for f in self.s.figures_.values() if f.document_id == document_id and f.version_id == active and f.page == page]
        return [replace(f) for f in sorted(fs, key=lambda f: f.figure_id)]

    def figure(self, document_id, figure_id):
        active = self.s.documents.active_versions().get(document_id)
        f = self.s.figures_.get((active, figure_id)) if active else None
        return replace(f) if f and f.document_id == document_id else None

    def table_rows(self, table_name, *, drug=None, limit=2000):
        active = set(self.s.documents.active_versions().values())
        rows = [t for t in self.s.table_rows_.values() if t.table_name == table_name and t.version_id in active]
        if drug is not None:
            rows = [t for t in rows if isinstance(t.row.get("drug"), str) and t.row["drug"].lower().startswith(drug.lower())]
        rows.sort(key=lambda t: t.row_no)
        return [dict(t.row) for t in rows[:limit]]

    def iter_chunks(self, version_id, *, with_embeddings=False):
        cs = sorted((c for c in self.s.chunks_.values() if c.version_id == version_id), key=lambda c: c.chunk_id)
        for c in cs:
            yield replace(c, embedding=c.embedding.tolist() if with_embeddings else None)


# ---------------------------------------------------------------- search

class MemSearch(_Repo):
    def _candidates(self, program, document_ids):
        docs = set(document_ids) if document_ids is not None else None
        return [c for c in self.s.content._active_chunks()
                if (program is None or c.program == program) and (docs is None or c.document_id in docs)]

    def dense(self, embedding, k, *, program=None, document_ids=None):
        if len(embedding) != self.s.dim:
            raise ValueError(f"query embedding dimension {len(embedding)}, expected {self.s.dim}")
        cands = self._candidates(program, document_ids)
        if k <= 0 or not cands:
            return []
        q = np.asarray(embedding, dtype=np.float32)
        q = q / (np.linalg.norm(q) or 1.0)
        m = np.stack([c.embedding for c in cands])
        sims = (m @ q) / (np.linalg.norm(m, axis=1) + 1e-12)
        order = sorted(range(len(cands)), key=lambda i: (-float(sims[i]), cands[i].document_id, cands[i].chunk_id))[:k]
        return [SearchHit(chunk=replace(cands[i], embedding=None), score=float(sims[i]), rank=r)
                for r, i in enumerate(order, 1)]

    def keyword(self, query, k, *, program=None, document_ids=None):
        terms = set(tokens(query))
        cands = self._candidates(program, document_ids)
        if k <= 0 or not terms or not cands:
            return []
        docs = [tokens(c.search_text) for c in cands]
        df = {t: sum(1 for d in docs if t in d) for t in terms}
        n = len(cands)
        every, some = [], []                   # all terms present (websearch_to_tsquery ANDs them) first, then any
        for c, d in zip(cands, docs):
            hit = {t for t in terms if t in d}
            if not hit:
                continue
            score = sum(math.log(1 + n / df[t]) * (1 + math.log(d.count(t))) for t in hit) / (1 + math.log(1 + len(d)))
            (every if hit == terms else some).append((score, c))
        order = lambda x: (-x[0], x[1].document_id, x[1].chunk_id)  # noqa: E731
        scored = sorted(every, key=order) + sorted(some, key=order)
        return [SearchHit(chunk=replace(c, embedding=None), score=float(s), rank=r)
                for r, (s, c) in enumerate(scored[:k], 1)]


# ---------------------------------------------------------------- conversations, feedback, stats

class MemConversations(_Repo):
    def create(self, user_id, title):
        if user_id not in self.s.users_:
            raise NotFound(f"user {user_id}")
        now = utcnow()
        c = Conversation(id=_uuid(), user_id=user_id, title=title, created_at=now, updated_at=now)
        self.s.conversations_[c.id] = c
        return replace(c)

    def _with_count(self, c):
        return replace(c, message_count=sum(1 for m in self.s.messages_.values() if m.conversation_id == c.id))

    def get(self, conversation_id, *, user_id=None):
        c = self.s.conversations_.get(conversation_id)
        if c is None or (user_id is not None and c.user_id != user_id):
            return None
        return self._with_count(c)

    def list_for_user(self, user_id, *, offset=0, limit=50):
        cs = [c for c in self.s.conversations_.values() if c.user_id == user_id]
        cs.sort(key=lambda c: (c.updated_at, c.id), reverse=True)
        return Page(items=[self._with_count(c) for c in cs[offset:offset + limit]], total=len(cs), offset=offset,
                    limit=limit)

    def delete(self, conversation_id, user_id):
        c = self.s.conversations_.get(conversation_id)
        if c is None or c.user_id != user_id:
            return False
        del self.s.conversations_[conversation_id]
        for mid in [m.id for m in self.s.messages_.values() if m.conversation_id == conversation_id]:
            del self.s.messages_[mid]
            self.s.feedback_.pop(mid, None)
        return True

    def add_message(self, m):
        mid = m.id or _uuid()
        if mid in self.s.messages_ or any(x.request_id == m.request_id for x in self.s.messages_.values()):
            raise Conflict(f"message {mid} / request {m.request_id} already stored")
        if m.conversation_id not in self.s.conversations_ or m.user_id not in self.s.users_:
            raise NotFound(f"conversation {m.conversation_id} or user {m.user_id}")
        now = utcnow()
        stored = replace(m, id=mid, created_at=m.created_at or now, citations=list(m.citations or []),
                         conflicts=list(m.conflicts or []), tokens=dict(m.tokens or {}), feedback=None)
        self.s.messages_[mid] = stored
        self.s.conversations_[m.conversation_id].updated_at = now
        return replace(stored)

    def _attach(self, m):
        return replace(m, feedback=replace(self.s.feedback_[m.id]) if m.id in self.s.feedback_ else None)

    def message(self, message_id, *, user_id=None):
        m = self.s.messages_.get(message_id)
        if m is None or (user_id is not None and m.user_id != user_id):
            return None
        return self._attach(m)

    def message_by_request(self, request_id):
        m = next((m for m in self.s.messages_.values() if m.request_id == request_id), None)
        return self._attach(m) if m else None

    def messages(self, conversation_id):
        ms = [m for m in self.s.messages_.values() if m.conversation_id == conversation_id]
        return [self._attach(m) for m in sorted(ms, key=lambda m: m.created_at)]

    def search_messages(self, *, rating=None, status=None, user_id=None, q=None, cached=None, since=None, until=None,
                        offset=0, limit=50):
        def ok(m):
            fb = self.s.feedback_.get(m.id)
            return ((rating is None or (fb is not None and fb.rating == rating))
                    and (status is None or m.status == status) and (user_id is None or m.user_id == user_id)
                    and (q is None or q.lower() in m.question.lower() or q.lower() in m.answer.lower())
                    and (cached is None or m.cached == cached)
                    and (since is None or m.created_at >= since) and (until is None or m.created_at < until))
        ms = sorted((m for m in self.s.messages_.values() if ok(m)), key=lambda m: m.created_at, reverse=True)
        return Page(items=[self._attach(m) for m in ms[offset:offset + limit]], total=len(ms), offset=offset, limit=limit)


class MemFeedback(_Repo):
    def save(self, message_id, user_id, rating, reason, comment):
        if message_id not in self.s.messages_ or user_id not in self.s.users_:
            raise NotFound(f"message {message_id} or user {user_id}")
        if rating not in ("helpful", "unhelpful"):
            raise ValueError(f"invalid rating {rating!r}")
        now = utcnow()
        cur = self.s.feedback_.get(message_id)
        fb = Feedback(id=cur.id if cur else _uuid(), message_id=message_id, user_id=user_id, rating=rating,
                      created_at=cur.created_at if cur else now, updated_at=now, reason=reason, comment=comment)
        self.s.feedback_[message_id] = fb
        return replace(fb)

    def get(self, message_id):
        fb = self.s.feedback_.get(message_id)
        return replace(fb) if fb else None


class MemStats(_Repo):
    def overview(self, since, until):
        ms = [m for m in self.s.messages_.values() if since <= m.created_at < until]
        fbs = [self.s.feedback_.get(m.id) for m in ms]
        lat = [m.latency_s for m in ms if m.latency_s is not None]
        days = {}
        for m, fb in zip(ms, fbs):
            d = days.setdefault(m.created_at.astimezone(timezone.utc).date().isoformat(),
                                {"questions": 0, "helpful": 0, "unhelpful": 0, "no_answer": 0, "cached": 0})
            d["questions"] += 1
            d["no_answer"] += m.status == "no_answer"
            d["cached"] += bool(m.cached)
            if fb:
                d[fb.rating] += 1
        return {"questions": len(ms), "answered": sum(m.status == "answered" for m in ms),
                "no_answer": sum(m.status == "no_answer" for m in ms), "cached": sum(bool(m.cached) for m in ms),
                "fallback": sum(bool(m.fallback_used) for m in ms),
                "helpful": sum(1 for fb in fbs if fb and fb.rating == "helpful"),
                "unhelpful": sum(1 for fb in fbs if fb and fb.rating == "unhelpful"),
                "latency_p50_s": float(np.percentile(lat, 50)) if lat else None,
                "latency_p95_s": float(np.percentile(lat, 95)) if lat else None,
                "spend_usd": float(sum(m.cost_usd or 0.0 for m in ms)), "active_users": len({m.user_id for m in ms}),
                "per_day": [{"day": day, **d} for day, d in sorted(days.items())]}

    def usage_day(self, day):
        q, spend = self.s.usage_.get(day, (0, 0.0))
        return {"day": day.isoformat(), "questions": q, "spend_usd": float(spend)}

    def add_usage(self, day, questions=0, spend_usd=0.0):
        q, spend = self.s.usage_.get(day, (0, 0.0))
        self.s.usage_[day] = (q + questions, spend + spend_usd)


# ---------------------------------------------------------------- the store

class MemoryStore:
    def __init__(self, dim: int = 3072):
        self.dim = dim
        self.users_: dict[str, User] = {}
        self.tokens_: dict[str, RefreshToken] = {}
        self.documents_: dict[str, Document] = {}
        self.versions_: dict[str, DocumentVersion] = {}
        self.parents_, self.chunks_, self.figures_, self.table_rows_ = {}, {}, {}, {}
        self.jobs_: dict[str, IngestionJob] = {}
        self.conversations_: dict[str, Conversation] = {}
        self.messages_: dict[str, Message] = {}
        self.feedback_: dict[str, Feedback] = {}       # by message id
        self.usage_: dict = {}
        self.generation_ = 1
        self.users, self.tokens, self.documents = MemUsers(self), MemTokens(self), MemDocuments(self)
        self.content, self.search = MemContent(self), MemSearch(self)
        self.conversations, self.feedback, self.stats = MemConversations(self), MemFeedback(self), MemStats(self)

    def ping(self) -> bool:
        return True

    def migrate(self) -> None:
        pass

    def close(self) -> None:
        pass
