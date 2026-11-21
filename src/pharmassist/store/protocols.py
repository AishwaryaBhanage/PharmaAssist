"""Storage contracts (v2). Every stream codes against these; stream A implements them on PostgreSQL
(`store/pg.py`) and in memory (`store/memory.py`, for unit tests elsewhere).

Rules shared by both implementations:
- All methods are synchronous. The API runs them in FastAPI's thread pool, as v1 did.
- Ids: users, conversations, messages, feedback, jobs are UUID strings; documents are doc_id slugs;
  versions, parents, chunks, figures are the deterministic text ids from the pipeline (see
  db/migrations/0001_init.sql).
- Readers only ever see content of versions whose status is 'active' (search, read helpers,
  figures, table rows). Writers stage a version and `activate` it in one transaction.
- Nothing here logs or returns secrets. `password_hash` is argon2id; `token_hash` is sha256.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Iterator, Literal, Protocol, Sequence

Role = Literal["staff", "admin"]
VersionStatus = Literal["queued", "parsing", "extracting_figures", "chunking", "embedding", "verifying",
                        "active", "failed", "superseded"]
JobStatus = Literal["queued", "running", "succeeded", "failed", "dead_letter", "skipped"]
Rating = Literal["helpful", "unhelpful"]

NO_ANSWER_TEXT = "No answer found in knowledge base"   # the only wording the API returns for a miss


# ---------------------------------------------------------------- records

@dataclass
class User:
    id: str
    email: str
    display_name: str
    role: Role
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None
    password_hash: str | None = None     # only populated by UserRepo.by_email_for_login


@dataclass
class RefreshToken:
    id: str
    user_id: str
    token_hash: str
    expires_at: datetime
    created_at: datetime
    revoked_at: datetime | None = None
    replaced_by: str | None = None


@dataclass
class Document:
    id: str
    title: str
    program: str
    doc_type: str = ""
    authority: str = "advisory"
    publisher: str = ""
    doc_date: str = "unknown"
    source_url: str | None = None
    active_version_id: str | None = None
    created_by: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class DocumentVersion:
    id: str
    document_id: str
    sha256: str
    s3_key: str
    file_name: str
    content_type: str
    bytes: int
    status: VersionStatus
    pages: int | None = None
    error: str | None = None
    parser_version: str | None = None
    chunker_version: str | None = None
    embedder_model: str | None = None
    embedding_dim: int | None = None
    chunk_count: int = 0
    figure_count: int = 0
    created_by: str | None = None
    created_at: datetime | None = None
    activated_at: datetime | None = None


@dataclass
class ParentRecord:
    version_id: str
    parent_id: str
    document_id: str
    text: str
    page_start: int | None = None
    page_end: int | None = None
    section_path: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)   # v1 parent-result fields (program, date, content_types, ...)


@dataclass
class ChunkRecord:
    version_id: str
    chunk_id: str
    document_id: str
    text: str
    search_text: str
    program: str
    authority: str
    doc_date: str
    embedding: Sequence[float] | None = None     # 3,072 floats; None only when reading without vectors
    parent_id: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    section_path: list[str] = field(default_factory=list)
    content_types: list[str] = field(default_factory=list)
    extraction: str | None = None
    figure_ids: list[str] = field(default_factory=list)
    verification: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class FigureRecord:
    version_id: str
    figure_id: str
    document_id: str
    page: int
    kind: str
    status: str
    record: dict
    title: str | None = None
    crop_s3_key: str | None = None


@dataclass
class TableRowRecord:
    version_id: str
    table_name: Literal["va_formulary", "ny_pdl"]
    row_no: int
    row: dict


@dataclass
class IngestionJob:
    id: str
    version_id: str
    status: JobStatus
    attempt: int = 0
    stage: str | None = None
    error: str | None = None
    worker_id: str | None = None
    queued_at: datetime | None = None
    started_at: datetime | None = None
    heartbeat_at: datetime | None = None
    finished_at: datetime | None = None
    requested_by: str | None = None


@dataclass
class Conversation:
    id: str
    user_id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


@dataclass
class Message:
    id: str
    conversation_id: str
    user_id: str
    request_id: str
    question: str
    status: Literal["answered", "no_answer"]
    answer: str
    created_at: datetime
    agent_status: str | None = None
    assumption: str | None = None
    citations: list[dict] = field(default_factory=list)   # CitationOut dicts (app/api/schemas.py)
    conflicts: list[str] = field(default_factory=list)
    needs_review: bool = False
    provider: str | None = None
    model: str | None = None
    fallback_used: bool = False
    cached: bool = False
    cache_hit_id: str | None = None
    cache_similarity: float | None = None
    latency_s: float | None = None
    cost_usd: float | None = None
    tokens: dict = field(default_factory=dict)
    trace_id: str | None = None
    generation: int | None = None
    feedback: "Feedback | None" = None


@dataclass
class Feedback:
    id: str
    message_id: str
    user_id: str
    rating: Rating
    created_at: datetime
    updated_at: datetime
    reason: str | None = None
    comment: str | None = None


@dataclass
class SearchHit:
    """One chunk from dense or keyword search. `score` is cosine similarity for dense, ts_rank for
    keyword; callers fuse by rank (RRF), never by raw score."""
    chunk: ChunkRecord
    score: float
    rank: int


@dataclass
class Page:
    items: list
    total: int
    offset: int
    limit: int


class NotFound(LookupError):
    """The row doesn't exist (or isn't visible to this caller)."""


class Conflict(ValueError):
    """A uniqueness or state rule was violated (duplicate email, inactive version activation, ...)."""


# ---------------------------------------------------------------- repositories

class UserRepo(Protocol):
    def create(self, email: str, password_hash: str, role: Role, display_name: str = "") -> User:
        """Raises Conflict on a duplicate email (case-insensitive)."""
    def by_id(self, user_id: str) -> User | None: ...
    def by_email_for_login(self, email: str) -> User | None:
        """Includes password_hash. Case-insensitive match."""
    def touch_login(self, user_id: str) -> None: ...
    def list(self, *, offset: int = 0, limit: int = 50, q: str | None = None) -> Page: ...
    def update(self, user_id: str, *, role: Role | None = None, is_active: bool | None = None,
               display_name: str | None = None) -> User: ...
    def count(self, role: Role | None = None) -> int: ...


class TokenRepo(Protocol):
    def issue(self, user_id: str, token_hash: str, expires_at: datetime) -> RefreshToken: ...
    def by_hash(self, token_hash: str) -> RefreshToken | None: ...
    def rotate(self, old_id: str, new_token_hash: str, expires_at: datetime) -> RefreshToken:
        """Marks `old_id` revoked with replaced_by = the new token; returns the new token."""
    def revoke(self, token_id: str) -> None: ...
    def revoke_all(self, user_id: str) -> int: ...
    def purge_expired(self) -> int: ...


class DocumentRepo(Protocol):
    # documents
    def upsert_document(self, doc: Document) -> Document: ...
    def get_document(self, doc_id: str) -> Document | None: ...
    def list_documents(self, *, include_inactive: bool = True) -> list[Document]: ...
    def catalog(self) -> dict[str, dict]:
        """{doc_id: {title, program, doc_type, authority, publisher, date, source_url, file, pages,
        version}} for documents with an active version: the shape v1's catalog() returned."""
    # versions
    def create_version(self, version: DocumentVersion) -> DocumentVersion:
        """Raises Conflict when (document_id, sha256) already exists; callers then reuse that version."""
    def get_version(self, version_id: str) -> DocumentVersion | None: ...
    def version_by_sha(self, document_id: str, sha256: str) -> DocumentVersion | None: ...
    def list_versions(self, document_id: str) -> list[DocumentVersion]: ...
    def set_version_status(self, version_id: str, status: VersionStatus, *, error: str | None = None,
                           **fields) -> None:
        """`fields` may set pages, parser_version, chunker_version, embedder_model, embedding_dim,
        chunk_count, figure_count."""
    def activate(self, version_id: str) -> int:
        """In one transaction: the document's previous active version becomes 'superseded', this one
        'active', documents.active_version_id moves, index_state.generation += 1. Returns the new
        generation. Raises Conflict unless the version is in 'verifying'."""
    def deactivate(self, doc_id: str) -> dict:
        """Remove a document from the index, keeping the document and its stored file. In one
        transaction: the active version's chunks, parents, figures and table rows are deleted, that
        version becomes 'superseded', documents.active_version_id is cleared, index_state.generation
        += 1. Returns {"document_id", "version_id", "removed": {chunks, parents, figures, table_rows},
        "generation"}. Raises NotFound when the document is missing or has no active version."""
    def active_versions(self) -> dict[str, str]:
        """{document_id: active version_id}."""
    def generation(self) -> int: ...
    # jobs
    def create_job(self, version_id: str, requested_by: str | None = None) -> IngestionJob: ...
    def get_job(self, job_id: str) -> IngestionJob | None: ...
    def update_job(self, job_id: str, *, status: JobStatus | None = None, attempt: int | None = None,
                   stage: str | None = None, error: str | None = None, worker_id: str | None = None,
                   started: bool = False, heartbeat: bool = False, finished: bool = False) -> IngestionJob: ...
    def list_jobs(self, *, version_id: str | None = None, status: JobStatus | None = None,
                  offset: int = 0, limit: int = 50) -> Page: ...


class ContentRepo(Protocol):
    """Chunks, parents, figures and table rows. Writes are per version and idempotent (upsert on the
    deterministic ids). Reads see active versions only unless `version_id` is given."""
    def put_parents(self, rows: Sequence[ParentRecord]) -> int: ...
    def put_chunks(self, rows: Sequence[ChunkRecord]) -> int:
        """Every row needs an embedding of the configured dimension; raises ValueError otherwise."""
    def put_figures(self, rows: Sequence[FigureRecord]) -> int: ...
    def put_table_rows(self, rows: Sequence[TableRowRecord]) -> int: ...
    def delete_version_content(self, version_id: str) -> None: ...
    def counts(self, version_id: str) -> dict[str, int]:
        """{"chunks": n, "parents": n, "figures": n, "table_rows": n} for verification before activation."""

    def chunks_by_ids(self, ids: Sequence[tuple[str, str]]) -> dict[tuple[str, str], ChunkRecord]:
        """Keys are (version_id, chunk_id); embeddings are not loaded."""
    def parents_by_ids(self, ids: Sequence[tuple[str, str]]) -> dict[tuple[str, str], ParentRecord]: ...
    def figures_for_page(self, document_id: str, page: int) -> list[FigureRecord]: ...
    def figure(self, document_id: str, figure_id: str) -> FigureRecord | None: ...
    def table_rows(self, table_name: str, *, drug: str | None = None, limit: int = 2000) -> list[dict]:
        """Rows of the active version; `drug` filters by case-insensitive prefix on row['drug']."""
    def iter_chunks(self, version_id: str, *, with_embeddings: bool = False) -> Iterator[ChunkRecord]: ...


class SearchRepo(Protocol):
    """The two halves of hybrid search over active chunks. Fusion, parent expansion and the optional
    reranker live in `pharmassist.search.hybrid` (stream A), which keeps v1's `search()` signature."""
    def dense(self, embedding: Sequence[float], k: int, *, program: str | None = None,
              document_ids: Sequence[str] | None = None) -> list[SearchHit]: ...
    def keyword(self, query: str, k: int, *, program: str | None = None,
                document_ids: Sequence[str] | None = None) -> list[SearchHit]:
        """websearch_to_tsquery('english', query) ranked with ts_rank_cd."""


class ConversationRepo(Protocol):
    def create(self, user_id: str, title: str) -> Conversation: ...
    def get(self, conversation_id: str, *, user_id: str | None = None) -> Conversation | None:
        """With `user_id`, only that user's conversation is returned."""
    def list_for_user(self, user_id: str, *, offset: int = 0, limit: int = 50) -> Page: ...
    def delete(self, conversation_id: str, user_id: str) -> bool: ...
    def add_message(self, message: Message) -> Message:
        """Also bumps conversations.updated_at."""
    def message(self, message_id: str, *, user_id: str | None = None) -> Message | None: ...
    def message_by_request(self, request_id: str) -> Message | None: ...
    def messages(self, conversation_id: str) -> list[Message]:
        """Oldest first, with feedback attached."""
    def search_messages(self, *, rating: Rating | None = None, status: str | None = None,
                        user_id: str | None = None, q: str | None = None, cached: bool | None = None,
                        since: datetime | None = None, until: datetime | None = None,
                        offset: int = 0, limit: int = 50) -> Page:
        """Admin listing across all users, newest first; `q` matches question or answer text."""


class FeedbackRepo(Protocol):
    def save(self, message_id: str, user_id: str, rating: Rating, reason: str | None,
             comment: str | None) -> Feedback:
        """Insert or replace the rating on that message. Raises NotFound for an unknown message."""
    def get(self, message_id: str) -> Feedback | None: ...


class StatsRepo(Protocol):
    def overview(self, since: datetime, until: datetime) -> dict:
        """{questions, answered, no_answer, cached, fallback, helpful, unhelpful, latency_p50_s,
        latency_p95_s, spend_usd, active_users, per_day: [{day, questions, helpful, unhelpful,
        no_answer, cached}]}"""
    def usage_day(self, day: date) -> dict: ...
    def add_usage(self, day: date, questions: int = 0, spend_usd: float = 0.0) -> None: ...


class Store(Protocol):
    users: UserRepo
    tokens: TokenRepo
    documents: DocumentRepo
    content: ContentRepo
    search: SearchRepo
    conversations: ConversationRepo
    feedback: FeedbackRepo
    stats: StatsRepo

    def ping(self) -> bool:
        """SELECT 1 within a short timeout; False instead of raising."""
    def migrate(self) -> None:
        """Apply pending Alembic migrations (used by the deploy's migration task and by tests)."""
    def close(self) -> None: ...
