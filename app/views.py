"""Store records -> wire models (app/api/schemas.py). Kept in one place so every router returns the
same shape for the same record, and so nothing but these functions decides what leaves the server
(password hashes and token hashes never do)."""

from __future__ import annotations

from app.api import schemas as S
from pharmassist.store.protocols import (Conversation, Document, DocumentVersion, Feedback, IngestionJob, Message,
                                         User)


def user_out(u: User) -> S.UserOut:
    return S.UserOut(id=u.id, email=u.email, display_name=u.display_name or "", role=u.role, is_active=u.is_active,
                     created_at=u.created_at, last_login_at=u.last_login_at)


def feedback_out(f: Feedback | None) -> S.FeedbackOut | None:
    if f is None:
        return None
    return S.FeedbackOut(message_id=f.message_id, rating=f.rating, reason=f.reason, comment=f.comment,
                         created_at=f.created_at, updated_at=f.updated_at)


def _answer_fields(m: Message) -> dict:
    return dict(request_id=m.request_id, message_id=m.id, conversation_id=m.conversation_id, status=m.status,
                answer=m.answer, assumption=m.assumption, citations=m.citations or [],
                conflicts_noted=m.conflicts or [], needs_review=m.needs_review, cached=m.cached,
                cache_similarity=m.cache_similarity, matched_question=None, provider=m.provider, model=m.model,
                fallback_used=m.fallback_used, latency_seconds=m.latency_s, created_at=m.created_at)


def answer_out(m: Message, matched_question: str | None = None) -> S.AnswerOut:
    return S.AnswerOut(**{**_answer_fields(m), "matched_question": matched_question})


def message_out(m: Message) -> S.MessageOut:
    return S.MessageOut(**_answer_fields(m), question=m.question, feedback=feedback_out(m.feedback))


def admin_message_out(m: Message, email: str) -> S.AdminMessageOut:
    return S.AdminMessageOut(**_answer_fields(m), question=m.question, feedback=feedback_out(m.feedback),
                             user_id=m.user_id, user_email=email, agent_status=m.agent_status, cost_usd=m.cost_usd,
                             tokens=m.tokens or {}, trace_id=m.trace_id)


def conversation_summary(c: Conversation) -> S.ConversationSummaryOut:
    return S.ConversationSummaryOut(id=c.id, title=c.title, created_at=c.created_at, updated_at=c.updated_at,
                                    message_count=c.message_count)


def conversation_out(c: Conversation, messages: list[Message]) -> S.ConversationOut:
    return S.ConversationOut(id=c.id, title=c.title, created_at=c.created_at, updated_at=c.updated_at,
                             message_count=len(messages), messages=[message_out(m) for m in messages])


def version_out(v: DocumentVersion | None) -> S.VersionOut | None:
    if v is None:
        return None
    return S.VersionOut(id=v.id, document_id=v.document_id, file_name=v.file_name, content_type=v.content_type,
                        bytes=v.bytes, pages=v.pages, status=v.status, error=v.error, chunk_count=v.chunk_count,
                        figure_count=v.figure_count, created_at=v.created_at, activated_at=v.activated_at)


def document_out(d: Document, versions: list[DocumentVersion]) -> S.DocumentOut:
    active = next((v for v in versions if v.id == d.active_version_id), None)
    latest = max(versions, key=lambda v: (v.created_at is not None, v.created_at), default=None)
    return S.DocumentOut(id=d.id, title=d.title, program=d.program, doc_type=d.doc_type, authority=d.authority,
                         publisher=d.publisher, doc_date=d.doc_date, source_url=d.source_url,
                         active_version=version_out(active), latest_version=version_out(latest), versions=len(versions))


def job_out(j: IngestionJob, document_id: str, document_title: str | None = None) -> S.JobOut:
    return S.JobOut(id=j.id, version_id=j.version_id, document_id=document_id, document_title=document_title,
                    status=j.status, attempt=j.attempt, stage=j.stage, error=j.error, queued_at=j.queued_at,
                    started_at=j.started_at, finished_at=j.finished_at)
