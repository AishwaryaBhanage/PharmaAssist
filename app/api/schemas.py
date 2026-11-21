"""Request and response models for /api/v1 (v2). Field names are the wire format; the frontend's
TypeScript types are generated from the OpenAPI document these produce (`scripts/export_openapi.py`).

Errors: every non-2xx response is `ErrorOut`. Codes the frontend handles by name:
    unauthenticated, invalid_credentials, forbidden, token_expired, signup_disabled, email_taken,
    weak_password, question_too_short, question_too_long, rate_limited, daily_limit, spend_cap,
    not_ready, timeout, answer_failed, not_found, upload_too_large, upload_type, upload_pages,
    duplicate_version, validation_error.
Also raised by the API: limits_unavailable (503, the limit counters' store is down), too_large
    (413, a JSON body over app.max_body_bytes), server_error (500).
"""

from __future__ import annotations

from datetime import datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")

# A plain shape check rather than EmailStr: email-validator refuses special-use domains such as the
# seeded *.local accounts, and deliverability is not this API's concern (there is no email sending).
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"

Role = Literal["staff", "admin"]
NO_ANSWER_TEXT = "No answer found in knowledge base"


class ErrorOut(BaseModel):
    code: str
    message: str
    request_id: str | None = None


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    offset: int
    limit: int


# ---------------------------------------------------------------- auth

class SignupIn(BaseModel):
    email: str = Field(pattern=EMAIL_PATTERN, max_length=254)
    password: str = Field(min_length=10, max_length=256)
    display_name: str = Field(default="", max_length=80)


class LoginIn(BaseModel):
    email: str = Field(pattern=EMAIL_PATTERN, max_length=254)
    password: str = Field(max_length=256)


class UserOut(BaseModel):
    id: str
    email: str
    display_name: str
    role: Role
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None


class TokenOut(BaseModel):
    """The refresh token travels only in an HttpOnly cookie (`pa_refresh`), never in the body."""
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int                      # seconds
    user: UserOut


# ---------------------------------------------------------------- ask

class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = None   # omit to start a new conversation


class FigureOut(BaseModel):
    figure_id: str
    kind: str | None = None
    title: str | None = None
    status: str                          # machine_interpreted | ocr_checked | reviewed
    status_text: str
    crop_url: str | None = None          # /api/v1/figures/{doc_id}/{name} (authenticated redirect)


class CitationOut(BaseModel):
    id: str                              # locator, e.g. va_dod_cpg_opioids_2022:p27
    doc_id: str
    document: str                        # title
    label: str                           # "Page 27" | "<sheet> sheet, row 12"
    page: int | None = None
    sheet: str | None = None
    row: int | None = None
    url: str | None = None               # the publisher's own https link to that page, when valid
    local_url: str | None = None         # /api/v1/sources/{doc_id}/p{N}.pdf
    flagged: bool = False
    flag_reason: str | None = None
    figures: list[FigureOut] = []


class AnswerOut(BaseModel):
    request_id: str
    message_id: str
    conversation_id: str
    status: Literal["answered", "no_answer"]
    answer: str                          # markdown; exactly NO_ANSWER_TEXT when status == no_answer
    assumption: str | None = None
    citations: list[CitationOut] = []
    conflicts_noted: list[str] = []
    needs_review: bool = False
    cached: bool = False
    cache_similarity: float | None = None
    matched_question: str | None = None  # the stored question a cache hit matched
    provider: str | None = None          # openai | anthropic | cache
    model: str | None = None
    fallback_used: bool = False
    latency_seconds: float | None = None
    created_at: datetime


class FeedbackIn(BaseModel):
    rating: Literal["helpful", "unhelpful"]
    reason: Literal["wrong", "incomplete", "outdated", "unclear", "other"] | None = None
    comment: str | None = Field(default=None, max_length=1000)


class FeedbackOut(BaseModel):
    message_id: str
    rating: Literal["helpful", "unhelpful"]
    reason: str | None = None
    comment: str | None = None
    created_at: datetime
    updated_at: datetime


class MessageOut(AnswerOut):
    question: str
    feedback: FeedbackOut | None = None


class ConversationSummaryOut(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int


class ConversationOut(ConversationSummaryOut):
    messages: list[MessageOut]


# ---------------------------------------------------------------- admin

class AdminMessageOut(MessageOut):
    user_id: str
    user_email: str
    agent_status: str | None = None
    cost_usd: float | None = None
    tokens: dict = {}
    trace_id: str | None = None


class DayStatOut(BaseModel):
    day: str
    questions: int
    helpful: int
    unhelpful: int
    no_answer: int
    cached: int


class StatsOut(BaseModel):
    since: datetime
    until: datetime
    questions: int
    answered: int
    no_answer: int
    cached: int
    fallback: int
    helpful: int
    unhelpful: int
    latency_p50_s: float | None = None
    latency_p95_s: float | None = None
    spend_usd: float
    spend_cap_usd: float
    spend_today_usd: float
    active_users: int
    users_total: int
    documents_active: int
    cache: dict                          # SemanticCache.stats()
    per_day: list[DayStatOut]


class VersionOut(BaseModel):
    id: str
    document_id: str
    file_name: str
    content_type: str
    bytes: int
    pages: int | None = None
    status: str
    error: str | None = None
    chunk_count: int
    figure_count: int
    created_at: datetime | None = None
    activated_at: datetime | None = None


class DocumentOut(BaseModel):
    id: str
    title: str
    program: str
    doc_type: str
    authority: str
    publisher: str
    doc_date: str
    source_url: str | None = None
    active_version: VersionOut | None = None
    latest_version: VersionOut | None = None
    versions: int


class JobOut(BaseModel):
    id: str
    version_id: str
    document_id: str
    document_title: str | None = None
    status: str
    attempt: int
    stage: str | None = None
    error: str | None = None
    queued_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class UploadOut(BaseModel):
    """POST /admin/documents is multipart/form-data: file, doc_id (slug), title, program, doc_type,
    authority, publisher, doc_date, source_url. The response is the created (or reused) version and job."""
    document: DocumentOut
    version: VersionOut
    job: JobOut | None = None            # None when the identical file was already active
    reused: bool = False


class IndexRemovedOut(BaseModel):
    """DELETE /admin/documents/{doc_id}/index: the document stays, with its stored file, and can be
    re-indexed later; its active version's content is gone from the index."""
    document_id: str
    version_id: str
    removed: dict[str, int]              # chunks, parents, figures, table_rows deleted
    generation: int                      # the new index generation (cached answers before it are dropped)


class UserPatchIn(BaseModel):
    role: Role | None = None
    is_active: bool | None = None
    display_name: str | None = Field(default=None, max_length=80)


class CacheStatsOut(BaseModel):
    entries: int
    hits: int
    misses: int
    hit_rate: float
    threshold: float | None = None
    generation: int | None = None
    backend: str
    cleared_at: str | None = None      # ISO time of the last admin clear; hits/misses count since then


class CacheClearOut(BaseModel):
    """DELETE /admin/cache: how many entries were removed."""
    removed: int


# ---------------------------------------------------------------- health

class HealthOut(BaseModel):
    ready: bool
    checks: dict[str, bool]              # postgres, cache, storage, llm_config
    version: str | None = None
    generation: int | None = None
