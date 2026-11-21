"""The PostgreSQL (+pgvector) store: every protocol in `protocols.py` on psycopg 3.

One `ConnectionPool`; each repository method is one transaction (`with pool.connection()` commits on
success and rolls back on an exception). Readers see content of active versions only by joining
`documents.active_version_id`, so a half-ingested version is invisible until `activate()` moves the
pointer. Embeddings are `halfvec(3072)` (pgvector's HNSW limit is 2,000 dims for `vector`); the
dense half sets `hnsw.ef_search` per query and filters in the WHERE clause, so a program filter still
returns k results when the program has them (as v1 did).
"""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterator, Sequence

import numpy as np
import psycopg
from pgvector import HalfVector
from pgvector.psycopg import register_vector
from psycopg import errors, sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from pharmassist.store.protocols import (ChunkRecord, Conflict, Conversation, Document, DocumentVersion, Feedback,
                                         FigureRecord, IngestionJob, Message, NotFound, Page, ParentRecord,
                                         RefreshToken, SearchHit, TableRowRecord, User)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = PROJECT_ROOT / "db" / "alembic.ini"
VERSION_FIELDS = ("pages", "parser_version", "chunker_version", "embedder_model", "embedding_dim", "chunk_count",
                  "figure_count")
# chunk columns in ChunkRecord order, without the embedding (reads never load it unless asked)
CHUNK_COLS = ("version_id", "chunk_id", "document_id", "text", "search_text", "program", "authority", "doc_date",
              "parent_id", "page_start", "page_end", "section_path", "content_types", "extraction", "figure_ids",
              "verification", "metadata")
_ACTIVE_JOIN = "JOIN documents d ON d.id = c.document_id AND d.active_version_id = c.version_id"


def _s(v):
    return None if v is None else str(v)


def _like(prefix: str) -> str:
    return prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _user(r) -> User:
    return User(id=str(r["id"]), email=r["email"], display_name=r["display_name"], role=r["role"],
                is_active=r["is_active"], created_at=r["created_at"], last_login_at=r["last_login_at"],
                password_hash=r.get("password_hash"))


def _token(r) -> RefreshToken:
    return RefreshToken(id=str(r["id"]), user_id=str(r["user_id"]), token_hash=r["token_hash"],
                        expires_at=r["expires_at"], created_at=r["created_at"], revoked_at=r["revoked_at"],
                        replaced_by=_s(r["replaced_by"]))


def _document(r) -> Document:
    return Document(id=r["id"], title=r["title"], program=r["program"], doc_type=r["doc_type"],
                    authority=r["authority"], publisher=r["publisher"], doc_date=r["doc_date"],
                    source_url=r["source_url"], active_version_id=r["active_version_id"],
                    created_by=_s(r["created_by"]), created_at=r["created_at"], updated_at=r["updated_at"])


def _version(r) -> DocumentVersion:
    return DocumentVersion(id=r["id"], document_id=r["document_id"], sha256=r["sha256"], s3_key=r["s3_key"],
                           file_name=r["file_name"], content_type=r["content_type"], bytes=r["bytes"],
                           status=r["status"], pages=r["pages"], error=r["error"],
                           parser_version=r["parser_version"], chunker_version=r["chunker_version"],
                           embedder_model=r["embedder_model"], embedding_dim=r["embedding_dim"],
                           chunk_count=r["chunk_count"], figure_count=r["figure_count"],
                           created_by=_s(r["created_by"]), created_at=r["created_at"], activated_at=r["activated_at"])


def _job(r) -> IngestionJob:
    return IngestionJob(id=str(r["id"]), version_id=r["version_id"], status=r["status"], attempt=r["attempt"],
                        stage=r["stage"], error=r["error"], worker_id=r["worker_id"], queued_at=r["queued_at"],
                        started_at=r["started_at"], heartbeat_at=r["heartbeat_at"], finished_at=r["finished_at"],
                        requested_by=_s(r["requested_by"]))


def _chunk(r, embedding=None) -> ChunkRecord:
    return ChunkRecord(version_id=r["version_id"], chunk_id=r["chunk_id"], document_id=r["document_id"],
                       text=r["text"], search_text=r["search_text"], program=r["program"], authority=r["authority"],
                       doc_date=r["doc_date"], embedding=embedding, parent_id=r["parent_id"],
                       page_start=r["page_start"], page_end=r["page_end"], section_path=list(r["section_path"]),
                       content_types=list(r["content_types"]), extraction=r["extraction"],
                       figure_ids=list(r["figure_ids"]), verification=r["verification"], metadata=dict(r["metadata"]))


def _parent(r) -> ParentRecord:
    return ParentRecord(version_id=r["version_id"], parent_id=r["parent_id"], document_id=r["document_id"],
                        text=r["text"], page_start=r["page_start"], page_end=r["page_end"],
                        section_path=list(r["section_path"]), metadata=dict(r["metadata"]))


def _figure(r) -> FigureRecord:
    return FigureRecord(version_id=r["version_id"], figure_id=r["figure_id"], document_id=r["document_id"],
                        page=r["page"], kind=r["kind"], status=r["status"], record=r["record"], title=r["title"],
                        crop_s3_key=r["crop_s3_key"])


def _conversation(r) -> Conversation:
    return Conversation(id=str(r["id"]), user_id=str(r["user_id"]), title=r["title"], created_at=r["created_at"],
                        updated_at=r["updated_at"], message_count=r.get("message_count") or 0)


def _feedback(r) -> Feedback:
    return Feedback(id=str(r["id"]), message_id=str(r["message_id"]), user_id=str(r["user_id"]), rating=r["rating"],
                    created_at=r["created_at"], updated_at=r["updated_at"], reason=r["reason"], comment=r["comment"])


def _message(r) -> Message:
    fb = None
    if r.get("fb_id"):
        fb = Feedback(id=str(r["fb_id"]), message_id=str(r["id"]), user_id=str(r["fb_user_id"]), rating=r["fb_rating"],
                      created_at=r["fb_created_at"], updated_at=r["fb_updated_at"], reason=r["fb_reason"],
                      comment=r["fb_comment"])
    return Message(id=str(r["id"]), conversation_id=str(r["conversation_id"]), user_id=str(r["user_id"]),
                   request_id=r["request_id"], question=r["question"], status=r["status"], answer=r["answer"],
                   created_at=r["created_at"], agent_status=r["agent_status"], assumption=r["assumption"],
                   citations=list(r["citations"]), conflicts=list(r["conflicts"]), needs_review=r["needs_review"],
                   provider=r["provider"], model=r["model"], fallback_used=r["fallback_used"], cached=r["cached"],
                   cache_hit_id=r["cache_hit_id"], cache_similarity=r["cache_similarity"], latency_s=r["latency_s"],
                   cost_usd=r["cost_usd"], tokens=dict(r["tokens"]), trace_id=r["trace_id"],
                   generation=r["generation"], feedback=fb)


# every message column, plus its feedback (LEFT JOIN) so one query attaches it
_MESSAGE_SELECT = """
    SELECT m.*, f.id AS fb_id, f.user_id AS fb_user_id, f.rating AS fb_rating, f.reason AS fb_reason,
           f.comment AS fb_comment, f.created_at AS fb_created_at, f.updated_at AS fb_updated_at
    FROM messages m LEFT JOIN feedback f ON f.message_id = m.id
"""


class _Repo:
    def __init__(self, store: "PgStore"):
        self.store = store

    @contextmanager
    def _conn(self):
        with self.store.pool.connection() as conn:
            yield conn


# ---------------------------------------------------------------- users and tokens

class PgUsers(_Repo):
    def create(self, email, password_hash, role, display_name=""):
        with self._conn() as conn:
            try:
                r = conn.execute("INSERT INTO users (email, password_hash, role, display_name) VALUES (%s, %s, %s, %s) "
                                 "RETURNING *", (email, password_hash, role, display_name)).fetchone()
            except errors.UniqueViolation:
                raise Conflict(f"email already registered: {email.lower()}") from None
            except errors.CheckViolation:
                raise ValueError(f"invalid role {role!r}") from None
        u = _user(r)
        u.password_hash = None
        return u

    def by_id(self, user_id):
        with self._conn() as conn:
            r = conn.execute("SELECT * FROM users WHERE id = %s", (user_id,)).fetchone()
        if r is None:
            return None
        u = _user(r)
        u.password_hash = None
        return u

    def by_email_for_login(self, email):
        with self._conn() as conn:
            r = conn.execute("SELECT * FROM users WHERE lower(email) = lower(%s)", (email,)).fetchone()
        return _user(r) if r else None

    def touch_login(self, user_id):
        with self._conn() as conn:
            conn.execute("UPDATE users SET last_login_at = now() WHERE id = %s", (user_id,))

    def list(self, *, offset=0, limit=50, q=None):
        where = "WHERE (%(q)s::text IS NULL OR email ILIKE %(like)s OR display_name ILIKE %(like)s)"
        params = {"q": q, "like": f"%{q}%" if q else None, "offset": offset, "limit": limit}
        with self._conn() as conn:
            total = conn.execute(f"SELECT count(*) AS n FROM users {where}", params).fetchone()["n"]
            rows = conn.execute(f"SELECT * FROM users {where} ORDER BY created_at, email OFFSET %(offset)s LIMIT %(limit)s",
                                params).fetchall()
        items = []
        for r in rows:
            u = _user(r)
            u.password_hash = None
            items.append(u)
        return Page(items=items, total=total, offset=offset, limit=limit)

    def update(self, user_id, *, role=None, is_active=None, display_name=None):
        sets = {k: v for k, v in (("role", role), ("is_active", is_active), ("display_name", display_name)) if v is not None}
        with self._conn() as conn:
            if sets:
                q = sql.SQL("UPDATE users SET {} WHERE id = %s RETURNING *").format(
                    sql.SQL(", ").join(sql.SQL("{} = {}").format(sql.Identifier(k), sql.Placeholder()) for k in sets))
                r = conn.execute(q, (*sets.values(), user_id)).fetchone()
            else:
                r = conn.execute("SELECT * FROM users WHERE id = %s", (user_id,)).fetchone()
        if r is None:
            raise NotFound(f"user {user_id}")
        u = _user(r)
        u.password_hash = None
        return u

    def count(self, role=None):
        with self._conn() as conn:
            return conn.execute("SELECT count(*) AS n FROM users WHERE %s::text IS NULL OR role = %s",
                                (role, role)).fetchone()["n"]


class PgTokens(_Repo):
    def issue(self, user_id, token_hash, expires_at):
        with self._conn() as conn:
            r = conn.execute("INSERT INTO refresh_tokens (user_id, token_hash, expires_at) VALUES (%s, %s, %s) RETURNING *",
                             (user_id, token_hash, expires_at)).fetchone()
        return _token(r)

    def by_hash(self, token_hash):
        with self._conn() as conn:
            r = conn.execute("SELECT * FROM refresh_tokens WHERE token_hash = %s", (token_hash,)).fetchone()
        return _token(r) if r else None

    def rotate(self, old_id, new_token_hash, expires_at):
        with self._conn() as conn:
            old = conn.execute("SELECT * FROM refresh_tokens WHERE id = %s FOR UPDATE", (old_id,)).fetchone()
            if old is None:
                raise NotFound(f"refresh token {old_id}")
            new = conn.execute("INSERT INTO refresh_tokens (user_id, token_hash, expires_at) VALUES (%s, %s, %s) RETURNING *",
                               (old["user_id"], new_token_hash, expires_at)).fetchone()
            conn.execute("UPDATE refresh_tokens SET revoked_at = coalesce(revoked_at, now()), replaced_by = %s WHERE id = %s",
                         (new["id"], old_id))
        return _token(new)

    def revoke(self, token_id):
        with self._conn() as conn:
            conn.execute("UPDATE refresh_tokens SET revoked_at = now() WHERE id = %s AND revoked_at IS NULL", (token_id,))

    def revoke_all(self, user_id):
        with self._conn() as conn:
            cur = conn.execute("UPDATE refresh_tokens SET revoked_at = now() WHERE user_id = %s AND revoked_at IS NULL",
                               (user_id,))
            return cur.rowcount

    def purge_expired(self):
        with self._conn() as conn:
            return conn.execute("DELETE FROM refresh_tokens WHERE expires_at < now()").rowcount


# ---------------------------------------------------------------- documents, versions, jobs

class PgDocuments(_Repo):
    def upsert_document(self, doc):
        with self._conn() as conn:
            r = conn.execute("""
                INSERT INTO documents (id, title, program, doc_type, authority, publisher, doc_date, source_url, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET title = EXCLUDED.title, program = EXCLUDED.program,
                    doc_type = EXCLUDED.doc_type, authority = EXCLUDED.authority, publisher = EXCLUDED.publisher,
                    doc_date = EXCLUDED.doc_date, source_url = EXCLUDED.source_url, updated_at = now()
                RETURNING *""", (doc.id, doc.title, doc.program, doc.doc_type, doc.authority, doc.publisher,
                                 doc.doc_date, doc.source_url, doc.created_by)).fetchone()
        return _document(r)

    def get_document(self, doc_id):
        with self._conn() as conn:
            r = conn.execute("SELECT * FROM documents WHERE id = %s", (doc_id,)).fetchone()
        return _document(r) if r else None

    def list_documents(self, *, include_inactive=True):
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM documents WHERE %s OR active_version_id IS NOT NULL ORDER BY id",
                                (include_inactive,)).fetchall()
        return [_document(r) for r in rows]

    def catalog(self):
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT d.*, v.file_name, v.pages AS v_pages FROM documents d
                JOIN document_versions v ON v.id = d.active_version_id ORDER BY d.id""").fetchall()
        return {r["id"]: {"id": r["id"], "title": r["title"], "program": r["program"], "doc_type": r["doc_type"],
                          "authority": r["authority"], "publisher": r["publisher"], "date": r["doc_date"],
                          "source_url": r["source_url"], "file": r["file_name"], "pages": r["v_pages"],
                          "version": r["active_version_id"]} for r in rows}

    def create_version(self, v):
        with self._conn() as conn:
            try:
                r = conn.execute("""
                    INSERT INTO document_versions (id, document_id, sha256, s3_key, file_name, content_type, bytes, pages,
                        status, error, parser_version, chunker_version, embedder_model, embedding_dim, chunk_count,
                        figure_count, created_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *""",
                    (v.id, v.document_id, v.sha256, v.s3_key, v.file_name, v.content_type, v.bytes, v.pages, v.status,
                     v.error, v.parser_version, v.chunker_version, v.embedder_model, v.embedding_dim, v.chunk_count,
                     v.figure_count, v.created_by)).fetchone()
            except errors.UniqueViolation:
                raise Conflict(f"version {v.id} of {v.document_id} already exists") from None
            except errors.ForeignKeyViolation:
                raise NotFound(f"document {v.document_id}") from None
        return _version(r)

    def get_version(self, version_id):
        with self._conn() as conn:
            r = conn.execute("SELECT * FROM document_versions WHERE id = %s", (version_id,)).fetchone()
        return _version(r) if r else None

    def version_by_sha(self, document_id, sha256):
        with self._conn() as conn:
            r = conn.execute("SELECT * FROM document_versions WHERE document_id = %s AND sha256 = %s",
                             (document_id, sha256)).fetchone()
        return _version(r) if r else None

    def list_versions(self, document_id):
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM document_versions WHERE document_id = %s ORDER BY created_at DESC, id",
                                (document_id,)).fetchall()
        return [_version(r) for r in rows]

    def set_version_status(self, version_id, status, *, error=None, **fields):
        bad = set(fields) - set(VERSION_FIELDS)
        if bad:
            raise ValueError(f"unknown version fields: {sorted(bad)}")
        sets = {"status": status, "error": error, **fields}
        q = sql.SQL("UPDATE document_versions SET {} WHERE id = %s").format(
            sql.SQL(", ").join(sql.SQL("{} = {}").format(sql.Identifier(k), sql.Placeholder()) for k in sets))
        with self._conn() as conn:
            try:
                n = conn.execute(q, (*sets.values(), version_id)).rowcount
            except errors.CheckViolation:
                raise ValueError(f"invalid version status {status!r}") from None
        if n == 0:
            raise NotFound(f"version {version_id}")

    def activate(self, version_id):
        with self._conn() as conn:
            v = conn.execute("SELECT document_id, status FROM document_versions WHERE id = %s FOR UPDATE",
                             (version_id,)).fetchone()
            if v is None:
                raise NotFound(f"version {version_id}")
            if v["status"] != "verifying":
                raise Conflict(f"version {version_id} is {v['status']!r}, not 'verifying'")
            d = conn.execute("SELECT active_version_id FROM documents WHERE id = %s FOR UPDATE",
                             (v["document_id"],)).fetchone()
            prev = d["active_version_id"]
            if prev and prev != version_id:
                conn.execute("UPDATE document_versions SET status = 'superseded' WHERE id = %s", (prev,))
            conn.execute("UPDATE document_versions SET status = 'active', activated_at = now(), error = NULL WHERE id = %s",
                         (version_id,))
            conn.execute("UPDATE documents SET active_version_id = %s, updated_at = now() WHERE id = %s",
                         (version_id, v["document_id"]))
            gen = conn.execute("UPDATE index_state SET generation = generation + 1, updated_at = now() WHERE id = 1 "
                               "RETURNING generation").fetchone()["generation"]
        return gen

    def deactivate(self, doc_id):
        with self._conn() as conn:
            d = conn.execute("SELECT active_version_id FROM documents WHERE id = %s FOR UPDATE", (doc_id,)).fetchone()
            if d is None or d["active_version_id"] is None:
                raise NotFound(f"document {doc_id} has no active version")
            vid = d["active_version_id"]
            conn.execute("SELECT id FROM document_versions WHERE id = %s FOR UPDATE", (vid,))
            removed = {}
            for t in ("chunks", "parents", "figures", "table_rows"):
                removed[t] = conn.execute(f"DELETE FROM {t} WHERE version_id = %s", (vid,)).rowcount
            conn.execute("UPDATE document_versions SET status = 'superseded' WHERE id = %s", (vid,))
            conn.execute("UPDATE documents SET active_version_id = NULL, updated_at = now() WHERE id = %s", (doc_id,))
            gen = conn.execute("UPDATE index_state SET generation = generation + 1, updated_at = now() WHERE id = 1 "
                               "RETURNING generation").fetchone()["generation"]
        return {"document_id": doc_id, "version_id": vid, "removed": removed, "generation": gen}

    def active_versions(self):
        with self._conn() as conn:
            rows = conn.execute("SELECT id, active_version_id FROM documents WHERE active_version_id IS NOT NULL").fetchall()
        return {r["id"]: r["active_version_id"] for r in rows}

    def generation(self):
        with self._conn() as conn:
            return conn.execute("SELECT generation FROM index_state WHERE id = 1").fetchone()["generation"]

    def create_job(self, version_id, requested_by=None):
        with self._conn() as conn:
            try:
                r = conn.execute("INSERT INTO ingestion_jobs (version_id, status, requested_by) VALUES (%s, 'queued', %s) "
                                 "RETURNING *", (version_id, requested_by)).fetchone()
            except errors.ForeignKeyViolation:
                raise NotFound(f"version {version_id}") from None
        return _job(r)

    def get_job(self, job_id):
        with self._conn() as conn:
            r = conn.execute("SELECT * FROM ingestion_jobs WHERE id = %s", (job_id,)).fetchone()
        return _job(r) if r else None

    def update_job(self, job_id, *, status=None, attempt=None, stage=None, error=None, worker_id=None,
                   started=False, heartbeat=False, finished=False):
        sets = [sql.SQL("{} = {}").format(sql.Identifier(k), sql.Placeholder()) for k, v in
                (("status", status), ("attempt", attempt), ("stage", stage), ("error", error), ("worker_id", worker_id))
                if v is not None]
        params = [v for v in (status, attempt, stage, error, worker_id) if v is not None]
        for flag, col in ((started, "started_at"), (heartbeat, "heartbeat_at"), (finished, "finished_at")):
            if flag:
                sets.append(sql.SQL("{} = now()").format(sql.Identifier(col)))
        with self._conn() as conn:
            if sets:
                q = sql.SQL("UPDATE ingestion_jobs SET {} WHERE id = %s RETURNING *").format(sql.SQL(", ").join(sets))
                try:
                    r = conn.execute(q, (*params, job_id)).fetchone()
                except errors.CheckViolation:
                    raise ValueError(f"invalid job status {status!r}") from None
            else:
                r = conn.execute("SELECT * FROM ingestion_jobs WHERE id = %s", (job_id,)).fetchone()
        if r is None:
            raise NotFound(f"job {job_id}")
        return _job(r)

    def list_jobs(self, *, version_id=None, status=None, offset=0, limit=50):
        where = "WHERE (%(v)s::text IS NULL OR version_id = %(v)s) AND (%(s)s::text IS NULL OR status = %(s)s)"
        params = {"v": version_id, "s": status, "offset": offset, "limit": limit}
        with self._conn() as conn:
            total = conn.execute(f"SELECT count(*) AS n FROM ingestion_jobs {where}", params).fetchone()["n"]
            rows = conn.execute(f"SELECT * FROM ingestion_jobs {where} ORDER BY queued_at DESC, id "
                                f"OFFSET %(offset)s LIMIT %(limit)s", params).fetchall()
        return Page(items=[_job(r) for r in rows], total=total, offset=offset, limit=limit)


# ---------------------------------------------------------------- content

class PgContent(_Repo):
    def put_parents(self, rows):
        if not rows:
            return 0
        with self._conn() as conn, conn.cursor() as cur:
            cur.executemany("""
                INSERT INTO parents (version_id, parent_id, document_id, text, page_start, page_end, section_path, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (version_id, parent_id) DO UPDATE SET document_id = EXCLUDED.document_id,
                    text = EXCLUDED.text, page_start = EXCLUDED.page_start, page_end = EXCLUDED.page_end,
                    section_path = EXCLUDED.section_path, metadata = EXCLUDED.metadata""",
                [(p.version_id, p.parent_id, p.document_id, p.text, p.page_start, p.page_end, list(p.section_path),
                  Jsonb(p.metadata or {})) for p in rows])
        return len(rows)

    def put_chunks(self, rows):
        if not rows:
            return 0
        dim = self.store.dim
        for c in rows:
            if c.embedding is None or len(c.embedding) != dim:
                got = "none" if c.embedding is None else len(c.embedding)
                raise ValueError(f"chunk {c.chunk_id}: embedding dimension {got}, expected {dim}")
        params = [(c.version_id, c.chunk_id, c.parent_id, c.document_id, c.text, c.search_text, c.page_start, c.page_end,
                   list(c.section_path), list(c.content_types), c.extraction, list(c.figure_ids), c.verification,
                   c.program, c.authority, c.doc_date, Jsonb(c.metadata or {}),
                   HalfVector(np.asarray(c.embedding, dtype=np.float32))) for c in rows]
        # The cost is HNSW maintenance, not transport: ~22 ms per 3,072-d row on one connection (45 s for the
        # 1,983-chunk corpus), and it parallelises almost linearly (8 connections: 4.9 s). So a large batch
        # is split over several connections, each its own transaction; the version isn't visible until
        # `activate`, and the upsert is idempotent, so a partial failure is simply re-run.
        workers = max(1, min(self.store.put_parallel, self.store.pool.max_size - 1, len(params) // 64))
        if workers <= 1:
            self._insert_chunks(params)
        else:
            with ThreadPoolExecutor(workers) as ex:
                list(ex.map(self._insert_chunks, [params[i::workers] for i in range(workers)]))
        return len(rows)

    def _insert_chunks(self, params):
        with self._conn() as conn, conn.cursor() as cur:
            # %b: the vector travels in binary (6 KB per row), not as a 30 KB text literal
            cur.executemany("""
                INSERT INTO chunks (version_id, chunk_id, parent_id, document_id, text, search_text, page_start, page_end,
                    section_path, content_types, extraction, figure_ids, verification, program, authority, doc_date,
                    metadata, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %b)
                ON CONFLICT (version_id, chunk_id) DO UPDATE SET parent_id = EXCLUDED.parent_id,
                    document_id = EXCLUDED.document_id, text = EXCLUDED.text, search_text = EXCLUDED.search_text,
                    page_start = EXCLUDED.page_start, page_end = EXCLUDED.page_end, section_path = EXCLUDED.section_path,
                    content_types = EXCLUDED.content_types, extraction = EXCLUDED.extraction,
                    figure_ids = EXCLUDED.figure_ids, verification = EXCLUDED.verification, program = EXCLUDED.program,
                    authority = EXCLUDED.authority, doc_date = EXCLUDED.doc_date, metadata = EXCLUDED.metadata,
                    embedding = EXCLUDED.embedding""", params)

    def put_figures(self, rows):
        if not rows:
            return 0
        with self._conn() as conn, conn.cursor() as cur:
            cur.executemany("""
                INSERT INTO figures (version_id, figure_id, document_id, page, kind, title, status, crop_s3_key, record)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (version_id, figure_id) DO UPDATE SET document_id = EXCLUDED.document_id, page = EXCLUDED.page,
                    kind = EXCLUDED.kind, title = EXCLUDED.title, status = EXCLUDED.status,
                    crop_s3_key = EXCLUDED.crop_s3_key, record = EXCLUDED.record""",
                [(f.version_id, f.figure_id, f.document_id, f.page, f.kind, f.title, f.status, f.crop_s3_key,
                  Jsonb(f.record)) for f in rows])
        return len(rows)

    def put_table_rows(self, rows):
        if not rows:
            return 0
        with self._conn() as conn, conn.cursor() as cur:
            try:
                cur.executemany("""
                    INSERT INTO table_rows (version_id, table_name, row_no, row) VALUES (%s, %s, %s, %s)
                    ON CONFLICT (version_id, table_name, row_no) DO UPDATE SET row = EXCLUDED.row""",
                    [(t.version_id, t.table_name, t.row_no, Jsonb(t.row)) for t in rows])
            except errors.CheckViolation:
                raise ValueError("table_name must be va_formulary or ny_pdl") from None
        return len(rows)

    def delete_version_content(self, version_id):
        with self._conn() as conn:
            for t in ("chunks", "parents", "figures", "table_rows"):
                conn.execute(f"DELETE FROM {t} WHERE version_id = %s", (version_id,))

    def counts(self, version_id):
        with self._conn() as conn:
            return {t: conn.execute(f"SELECT count(*) AS n FROM {t} WHERE version_id = %s", (version_id,)).fetchone()["n"]
                    for t in ("chunks", "parents", "figures", "table_rows")}

    def chunks_by_ids(self, ids):
        if not ids:
            return {}
        with self._conn() as conn:
            rows = conn.execute(f"""
                SELECT {', '.join('c.' + col for col in CHUNK_COLS)} FROM chunks c
                JOIN unnest(%s::text[], %s::text[]) AS k(version_id, chunk_id)
                  ON k.version_id = c.version_id AND k.chunk_id = c.chunk_id""",
                ([v for v, _ in ids], [c for _, c in ids])).fetchall()
        return {(r["version_id"], r["chunk_id"]): _chunk(r) for r in rows}

    def parents_by_ids(self, ids):
        if not ids:
            return {}
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT p.* FROM parents p JOIN unnest(%s::text[], %s::text[]) AS k(version_id, parent_id)
                  ON k.version_id = p.version_id AND k.parent_id = p.parent_id""",
                ([v for v, _ in ids], [p for _, p in ids])).fetchall()
        return {(r["version_id"], r["parent_id"]): _parent(r) for r in rows}

    def figures_for_page(self, document_id, page):
        with self._conn() as conn:
            rows = conn.execute(f"""
                SELECT c.* FROM figures c {_ACTIVE_JOIN} WHERE c.document_id = %s AND c.page = %s ORDER BY c.figure_id""",
                (document_id, page)).fetchall()
        return [_figure(r) for r in rows]

    def figure(self, document_id, figure_id):
        with self._conn() as conn:
            r = conn.execute(f"SELECT c.* FROM figures c {_ACTIVE_JOIN} WHERE c.document_id = %s AND c.figure_id = %s",
                             (document_id, figure_id)).fetchone()
        return _figure(r) if r else None

    def table_rows(self, table_name, *, drug=None, limit=2000):
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT t.row FROM table_rows t JOIN document_versions v ON v.id = t.version_id
                JOIN documents d ON d.id = v.document_id AND d.active_version_id = v.id
                WHERE t.table_name = %s AND (%s::text IS NULL OR lower(t.row->>'drug') LIKE lower(%s))
                ORDER BY t.row_no LIMIT %s""", (table_name, drug, _like(drug) if drug else None, limit)).fetchall()
        return [r["row"] for r in rows]

    def iter_chunks(self, version_id, *, with_embeddings=False):
        cols = ", ".join(CHUNK_COLS) + (", embedding" if with_embeddings else "")
        with self._conn() as conn, conn.cursor(name=f"iter_chunks_{uuid.uuid4().hex}") as cur:
            cur.itersize = 200
            cur.execute(f"SELECT {cols} FROM chunks WHERE version_id = %s ORDER BY chunk_id", (version_id,))
            for r in cur:
                emb = r["embedding"].to_list() if with_embeddings else None
                yield _chunk(r, emb)


# ---------------------------------------------------------------- search

class PgSearch(_Repo):
    def _filters(self, program, document_ids):
        return ("AND (%(program)s::text IS NULL OR c.program = %(program)s) "
                "AND (%(docs)s::text[] IS NULL OR c.document_id = ANY(%(docs)s))",
                {"program": program, "docs": list(document_ids) if document_ids is not None else None})

    def dense(self, embedding, k, *, program=None, document_ids=None):
        if len(embedding) != self.store.dim:
            raise ValueError(f"query embedding dimension {len(embedding)}, expected {self.store.dim}")
        if k <= 0:
            return []
        where, params = self._filters(program, document_ids)
        params.update(q=HalfVector(np.asarray(embedding, dtype=np.float32)), k=k)
        with self._conn() as conn:
            conn.execute(f"SET LOCAL hnsw.ef_search = {int(self.store.ef_search)}")
            if self.store.iterative_scan:   # pgvector >= 0.8: keep scanning until k rows pass the filter
                conn.execute("SET LOCAL hnsw.iterative_scan = strict_order")
            rows = conn.execute(f"""
                SELECT {', '.join('c.' + col for col in CHUNK_COLS)}, 1 - (c.embedding <=> %(q)s::halfvec) AS score
                FROM chunks c {_ACTIVE_JOIN} WHERE true {where}
                ORDER BY c.embedding <=> %(q)s::halfvec, c.document_id, c.chunk_id LIMIT %(k)s""", params).fetchall()
        return [SearchHit(chunk=_chunk(r), score=float(r["score"]), rank=i) for i, r in enumerate(rows, 1)]

    def keyword(self, query, k, *, program=None, document_ids=None):
        """websearch_to_tsquery ANDs every term, so a long query can match nothing while v1's BM25 always
        filled its list; chunks matching all terms rank first, then any-term matches fill the rest."""
        if k <= 0 or not query.strip():
            return []
        where, params = self._filters(program, document_ids)
        params.update(query=query, k=k)
        select = f"SELECT {', '.join('c.' + col for col in CHUNK_COLS)}, ts_rank_cd(c.tsv, q.tsq) AS score FROM chunks c {_ACTIVE_JOIN}"
        with self._conn() as conn:
            rows = conn.execute(f"""
                {select}, websearch_to_tsquery('english', %(query)s) AS q(tsq)
                WHERE c.tsv @@ q.tsq {where} ORDER BY score DESC, c.document_id, c.chunk_id LIMIT %(k)s""", params).fetchall()
            if len(rows) < k:
                params.update(k=k - len(rows), seen_v=[r["version_id"] for r in rows], seen_c=[r["chunk_id"] for r in rows])
                rows += conn.execute(f"""
                    {select}, (SELECT replace(websearch_to_tsquery('english', %(query)s)::text, '&', '|')::tsquery AS tsq) AS q
                    WHERE c.tsv @@ q.tsq {where}
                      AND NOT (c.version_id = ANY(%(seen_v)s::text[]) AND c.chunk_id = ANY(%(seen_c)s::text[]))
                    ORDER BY score DESC, c.document_id, c.chunk_id LIMIT %(k)s""", params).fetchall()
        return [SearchHit(chunk=_chunk(r), score=float(r["score"]), rank=i) for i, r in enumerate(rows, 1)]


# ---------------------------------------------------------------- conversations, feedback, stats

class PgConversations(_Repo):
    def create(self, user_id, title):
        with self._conn() as conn:
            try:
                r = conn.execute("INSERT INTO conversations (user_id, title) VALUES (%s, %s) RETURNING *",
                                 (user_id, title)).fetchone()
            except errors.ForeignKeyViolation:
                raise NotFound(f"user {user_id}") from None
        return _conversation(r)

    def get(self, conversation_id, *, user_id=None):
        with self._conn() as conn:
            r = conn.execute("""
                SELECT c.*, (SELECT count(*) FROM messages m WHERE m.conversation_id = c.id) AS message_count
                FROM conversations c WHERE c.id = %s AND (%s::uuid IS NULL OR c.user_id = %s)""",
                (conversation_id, user_id, user_id)).fetchone()
        return _conversation(r) if r else None

    def list_for_user(self, user_id, *, offset=0, limit=50):
        with self._conn() as conn:
            total = conn.execute("SELECT count(*) AS n FROM conversations WHERE user_id = %s", (user_id,)).fetchone()["n"]
            rows = conn.execute("""
                SELECT c.*, (SELECT count(*) FROM messages m WHERE m.conversation_id = c.id) AS message_count
                FROM conversations c WHERE c.user_id = %s ORDER BY c.updated_at DESC, c.id OFFSET %s LIMIT %s""",
                (user_id, offset, limit)).fetchall()
        return Page(items=[_conversation(r) for r in rows], total=total, offset=offset, limit=limit)

    def delete(self, conversation_id, user_id):
        with self._conn() as conn:
            return conn.execute("DELETE FROM conversations WHERE id = %s AND user_id = %s",
                                (conversation_id, user_id)).rowcount > 0

    def add_message(self, m):
        mid = m.id or str(uuid.uuid4())
        with self._conn() as conn:
            try:
                r = conn.execute("""
                    INSERT INTO messages (id, conversation_id, user_id, request_id, question, status, agent_status, answer,
                        assumption, citations, conflicts, needs_review, provider, model, fallback_used, cached, cache_hit_id,
                        cache_similarity, latency_s, cost_usd, tokens, trace_id, generation, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            coalesce(%s, now())) RETURNING *""",
                    (mid, m.conversation_id, m.user_id, m.request_id, m.question, m.status, m.agent_status, m.answer,
                     m.assumption, Jsonb(m.citations or []), Jsonb(m.conflicts or []), m.needs_review, m.provider, m.model,
                     m.fallback_used, m.cached, m.cache_hit_id, m.cache_similarity, m.latency_s, m.cost_usd,
                     Jsonb(m.tokens or {}), m.trace_id, m.generation, m.created_at)).fetchone()
            except errors.UniqueViolation:
                raise Conflict(f"message {mid} / request {m.request_id} already stored") from None
            except errors.ForeignKeyViolation:
                raise NotFound(f"conversation {m.conversation_id} or user {m.user_id}") from None
            conn.execute("UPDATE conversations SET updated_at = now() WHERE id = %s", (m.conversation_id,))
        return _message(r)

    def message(self, message_id, *, user_id=None):
        with self._conn() as conn:
            r = conn.execute(_MESSAGE_SELECT + "WHERE m.id = %s AND (%s::uuid IS NULL OR m.user_id = %s)",
                             (message_id, user_id, user_id)).fetchone()
        return _message(r) if r else None

    def message_by_request(self, request_id):
        with self._conn() as conn:
            r = conn.execute(_MESSAGE_SELECT + "WHERE m.request_id = %s", (request_id,)).fetchone()
        return _message(r) if r else None

    def messages(self, conversation_id):
        with self._conn() as conn:
            rows = conn.execute(_MESSAGE_SELECT + "WHERE m.conversation_id = %s ORDER BY m.created_at, m.id",
                                (conversation_id,)).fetchall()
        return [_message(r) for r in rows]

    def search_messages(self, *, rating=None, status=None, user_id=None, q=None, cached=None, since=None, until=None,
                        offset=0, limit=50):
        where = """WHERE (%(rating)s::text IS NULL OR f.rating = %(rating)s)
                     AND (%(status)s::text IS NULL OR m.status = %(status)s)
                     AND (%(user)s::uuid IS NULL OR m.user_id = %(user)s)
                     AND (%(q)s::text IS NULL OR m.question ILIKE %(like)s OR m.answer ILIKE %(like)s)
                     AND (%(cached)s::boolean IS NULL OR m.cached = %(cached)s)
                     AND (%(since)s::timestamptz IS NULL OR m.created_at >= %(since)s)
                     AND (%(until)s::timestamptz IS NULL OR m.created_at < %(until)s)"""
        params = {"rating": rating, "status": status, "user": user_id, "q": q, "like": f"%{q}%" if q else None,
                  "cached": cached, "since": since, "until": until, "offset": offset, "limit": limit}
        with self._conn() as conn:
            total = conn.execute(f"SELECT count(*) AS n FROM messages m LEFT JOIN feedback f ON f.message_id = m.id {where}",
                                 params).fetchone()["n"]
            rows = conn.execute(_MESSAGE_SELECT + where + " ORDER BY m.created_at DESC, m.id OFFSET %(offset)s LIMIT %(limit)s",
                                params).fetchall()
        return Page(items=[_message(r) for r in rows], total=total, offset=offset, limit=limit)


class PgFeedback(_Repo):
    def save(self, message_id, user_id, rating, reason, comment):
        with self._conn() as conn:
            try:
                r = conn.execute("""
                    INSERT INTO feedback (message_id, user_id, rating, reason, comment) VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (message_id) DO UPDATE SET user_id = EXCLUDED.user_id, rating = EXCLUDED.rating,
                        reason = EXCLUDED.reason, comment = EXCLUDED.comment, updated_at = now()
                    RETURNING *""", (message_id, user_id, rating, reason, comment)).fetchone()
            except errors.ForeignKeyViolation:
                raise NotFound(f"message {message_id} or user {user_id}") from None
            except errors.CheckViolation:
                raise ValueError(f"invalid rating {rating!r}") from None
        return _feedback(r)

    def get(self, message_id):
        with self._conn() as conn:
            r = conn.execute("SELECT * FROM feedback WHERE message_id = %s", (message_id,)).fetchone()
        return _feedback(r) if r else None


class PgStats(_Repo):
    def overview(self, since, until):
        with self._conn() as conn:
            t = conn.execute("""
                SELECT count(*) AS questions,
                       count(*) FILTER (WHERE m.status = 'answered') AS answered,
                       count(*) FILTER (WHERE m.status = 'no_answer') AS no_answer,
                       count(*) FILTER (WHERE m.cached) AS cached,
                       count(*) FILTER (WHERE m.fallback_used) AS fallback,
                       count(*) FILTER (WHERE f.rating = 'helpful') AS helpful,
                       count(*) FILTER (WHERE f.rating = 'unhelpful') AS unhelpful,
                       percentile_cont(0.5) WITHIN GROUP (ORDER BY m.latency_s) AS p50,
                       percentile_cont(0.95) WITHIN GROUP (ORDER BY m.latency_s) AS p95,
                       coalesce(sum(m.cost_usd), 0) AS spend, count(DISTINCT m.user_id) AS active_users
                FROM messages m LEFT JOIN feedback f ON f.message_id = m.id
                WHERE m.created_at >= %s AND m.created_at < %s""", (since, until)).fetchone()
            days = conn.execute("""
                SELECT (m.created_at AT TIME ZONE 'UTC')::date AS day, count(*) AS questions,
                       count(*) FILTER (WHERE f.rating = 'helpful') AS helpful,
                       count(*) FILTER (WHERE f.rating = 'unhelpful') AS unhelpful,
                       count(*) FILTER (WHERE m.status = 'no_answer') AS no_answer,
                       count(*) FILTER (WHERE m.cached) AS cached
                FROM messages m LEFT JOIN feedback f ON f.message_id = m.id
                WHERE m.created_at >= %s AND m.created_at < %s GROUP BY 1 ORDER BY 1""", (since, until)).fetchall()
        return {"questions": t["questions"], "answered": t["answered"], "no_answer": t["no_answer"], "cached": t["cached"],
                "fallback": t["fallback"], "helpful": t["helpful"], "unhelpful": t["unhelpful"],
                "latency_p50_s": None if t["p50"] is None else float(t["p50"]),
                "latency_p95_s": None if t["p95"] is None else float(t["p95"]),
                "spend_usd": float(t["spend"]), "active_users": t["active_users"],
                "per_day": [{"day": d["day"].isoformat(), "questions": d["questions"], "helpful": d["helpful"],
                             "unhelpful": d["unhelpful"], "no_answer": d["no_answer"], "cached": d["cached"]} for d in days]}

    def usage_day(self, day):
        with self._conn() as conn:
            r = conn.execute("SELECT * FROM usage_days WHERE day = %s", (day,)).fetchone()
        return {"day": day.isoformat(), "questions": r["questions"] if r else 0,
                "spend_usd": float(r["spend_usd"]) if r else 0.0}

    def add_usage(self, day, questions=0, spend_usd=0.0):
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO usage_days (day, questions, spend_usd) VALUES (%s, %s, %s)
                ON CONFLICT (day) DO UPDATE SET questions = usage_days.questions + EXCLUDED.questions,
                    spend_usd = usage_days.spend_usd + EXCLUDED.spend_usd""", (day, questions, spend_usd))


# ---------------------------------------------------------------- the store

class PgStore:
    """`PgStore.connect(dsn)`; `open_store()` in `pharmassist.store` is the usual entry point."""

    def __init__(self, pool: ConnectionPool, dsn: str, *, dim: int = 3072, ef_search: int = 80, put_parallel: int = 8):
        self.pool, self.dsn, self.dim, self.ef_search = pool, dsn, dim, ef_search
        self.put_parallel = put_parallel     # connections a large put_chunks spreads over (HNSW inserts are CPU-bound)
        self.iterative_scan = False
        self.users, self.tokens, self.documents = PgUsers(self), PgTokens(self), PgDocuments(self)
        self.content, self.search = PgContent(self), PgSearch(self)
        self.conversations, self.feedback, self.stats = PgConversations(self), PgFeedback(self), PgStats(self)

    @classmethod
    def connect(cls, dsn: str | None = None, *, cfg: dict | None = None, min_size: int | None = None,
                max_size: int | None = None) -> "PgStore":
        """Open the pool for `dsn` (default: the environment variable named by config `database.url_env`).
        Pool sizes and statement_timeout come from config `database:`; the dimension from `llm.embedding`."""
        import os
        from pharmassist.config import load_config
        cfg = cfg or load_config()
        db = cfg.get("database", {})
        dsn = dsn or os.environ.get(db.get("url_env", "DATABASE_URL"))
        if not dsn:
            raise RuntimeError(f"no database DSN: set {db.get('url_env', 'DATABASE_URL')}")
        pool_args = dict(min_size=min_size or int(db.get("pool_min", 2)), max_size=max_size or int(db.get("pool_max", 10)),
                         timeout_ms=int(db.get("statement_timeout_ms", 20000)))
        store = cls(_open_pool(dsn, **pool_args), dsn, dim=int(cfg.get("llm", {}).get("embedding", {}).get("dimension", 3072)),
                    ef_search=int(cfg.get("search", {}).get("hnsw_ef_search", 80)))
        store._pool_args = pool_args
        store._detect_pgvector()
        return store

    def _detect_pgvector(self) -> None:
        """Iterative HNSW scans (filters keep scanning until k rows match) exist from pgvector 0.8."""
        try:
            with self.pool.connection() as conn:
                v = conn.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'").fetchone()
            if v:
                major, minor = (int(x) for x in v["extversion"].split(".")[:2])
                self.iterative_scan = (major, minor) >= (0, 8)
        except psycopg.Error:
            self.iterative_scan = False

    def ping(self) -> bool:
        try:
            with self.pool.connection(timeout=3) as conn:
                conn.execute("SET LOCAL statement_timeout = 3000")
                return conn.execute("SELECT 1 AS ok").fetchone()["ok"] == 1
        except Exception:
            return False

    def migrate(self) -> None:
        """`alembic upgrade head` in-process, against this store's DSN (db/alembic.ini, db/versions/)."""
        from alembic import command
        from alembic.config import Config
        cfg = Config(str(ALEMBIC_INI))
        cfg.attributes["dsn"] = self.dsn
        command.upgrade(cfg, "head")
        # connections opened before the baseline existed have no halfvec adapter: start the pool afresh
        self.pool.close()
        self.pool = _open_pool(self.dsn, **getattr(self, "_pool_args", {}))
        self._detect_pgvector()

    def close(self) -> None:
        self.pool.close()


def _configure(conn: psycopg.Connection) -> None:
    """Per-connection setup: pgvector's adapters (halfvec in and out). Before the baseline migration
    the type doesn't exist yet; those connections only ever run the migration."""
    try:
        register_vector(conn)
    except psycopg.ProgrammingError:
        pass
    conn.commit()   # register_vector queried pg_type; the pool refuses a connection left in a transaction


def _open_pool(dsn: str, *, min_size: int = 2, max_size: int = 10, timeout_ms: int = 20000) -> ConnectionPool:
    return ConnectionPool(dsn, min_size=min_size, max_size=max_size, configure=_configure, open=True,
                          kwargs={"row_factory": dict_row, "options": f"-c statement_timeout={timeout_ms}"})


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


__all__ = ["PgStore", "utcnow", "date"]
