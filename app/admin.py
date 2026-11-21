"""Administration (`require_admin`): the dashboard numbers, every user's conversations with ratings
and comments, documents with their versions, uploads and re-indexing, ingestion jobs, users and the
semantic cache. Uploads are handed to stream E's `pharmassist.ingest.submit.submit_upload`, which
stores the file, records the version and queues the job; this layer only validates the form and maps
its rejections to error codes."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile

from app.api import schemas as S
from app.auth import require_admin
from app.deps import API, Deps, get_deps
from app.errors import ApiError, forbidden, not_found
from app.views import admin_message_out, document_out, job_out, user_out, version_out
from pharmassist.store.protocols import Document, NotFound, User

log = logging.getLogger("pharmassist.app")
router = APIRouter(prefix=f"{API}/admin", tags=["admin"], dependencies=[Depends(require_admin)])

SLUG = re.compile(r"^[a-z0-9_]{1,80}$")
PROGRAMS = ("VA", "Medicare Part D", "NY Medicaid")
AUTHORITIES = ("binding", "advisory", "summary_of_binding_policy")
DOC_DATE = re.compile(r"^(unknown|\d{4}-\d{2}(-\d{2})?)$")
REJECTION_STATUS = {"upload_too_large": 413, "upload_type": 400, "upload_pages": 400, "duplicate_version": 409}


# ---------------------------------------------------------------- stats and conversations

@router.get("/stats", response_model=S.StatsOut)
def stats(days: int = Query(30, ge=1, le=366), deps: Deps = Depends(get_deps)):
    until = deps.clock()
    since = (until - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
    o = deps.store.stats.overview(since, until)
    try:
        usage = deps.limiter.usage()
    except Exception as e:
        log.error("admin stats: limiter usage failed: %s", type(e).__name__)
        usage = {"spend_usd": 0.0, "spend_cap_usd": float((deps.cfg.get("limits_v2") or {}).get("spend_usd_per_day", 0))}
    try:
        cache = deps.cache.stats()
    except Exception as e:
        log.error("admin stats: cache stats failed: %s", type(e).__name__)
        cache = {}
    return S.StatsOut(
        since=since, until=until, questions=o.get("questions", 0), answered=o.get("answered", 0),
        no_answer=o.get("no_answer", 0), cached=o.get("cached", 0), fallback=o.get("fallback", 0),
        helpful=o.get("helpful", 0), unhelpful=o.get("unhelpful", 0), latency_p50_s=o.get("latency_p50_s"),
        latency_p95_s=o.get("latency_p95_s"), spend_usd=float(o.get("spend_usd") or 0),
        spend_cap_usd=float(usage.get("spend_cap_usd") or 0), spend_today_usd=float(usage.get("spend_usd") or 0),
        active_users=o.get("active_users", 0), users_total=deps.store.users.count(),
        documents_active=len(deps.store.documents.active_versions()), cache=cache,
        per_day=[S.DayStatOut(**d) for d in o.get("per_day") or []])


def _emails(deps: Deps):
    memo: dict[str, str] = {}

    def email(user_id: str) -> str:
        if user_id not in memo:
            u = deps.store.users.by_id(user_id)
            memo[user_id] = u.email if u else "(deleted)"
        return memo[user_id]
    return email


def _user_filter(deps: Deps, user: str | None) -> str | None:
    """`user` is a user id, or an email (exact, case-insensitive)."""
    if not user:
        return None
    if "@" in user:
        u = deps.store.users.by_email_for_login(user.lower())
        return u.id if u else "no-such-user"
    return user


def _date(value: str | None, name: str, end: bool = False) -> datetime | None:
    if not value:
        return None
    try:
        d = datetime.fromisoformat(value)
    except ValueError:
        raise ApiError(422, "validation_error", f"Check the request fields: {name}.")
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    if end and len(value) == 10:   # a bare date as `to` means the whole day
        d += timedelta(days=1)
    return d


@router.get("/conversations", response_model=S.Page[S.AdminMessageOut])
def admin_conversations(request: Request, rating: Literal["helpful", "unhelpful"] | None = None,
                        status: str | None = Query(None, pattern="^(answered|no_answer)$"),
                        user: str | None = None, q: str | None = Query(None, max_length=200),
                        cached: bool | None = None, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
                        deps: Deps = Depends(get_deps)):
    since = _date(request.query_params.get("from"), "from")
    until = _date(request.query_params.get("to"), "to", end=True)
    page = deps.store.conversations.search_messages(rating=rating, status=status, user_id=_user_filter(deps, user),
                                                    q=q or None, cached=cached, since=since, until=until,
                                                    offset=offset, limit=limit)
    email = _emails(deps)
    return S.Page(items=[admin_message_out(m, email(m.user_id)) for m in page.items], total=page.total,
                  offset=page.offset, limit=page.limit)


@router.get("/messages/{message_id}", response_model=S.AdminMessageOut)
def admin_message(message_id: str, deps: Deps = Depends(get_deps)):
    m = deps.store.conversations.message(message_id)
    if m is None:
        raise not_found("No such message.")
    return admin_message_out(m, _emails(deps)(m.user_id))


# ---------------------------------------------------------------- documents

@router.get("/documents", response_model=list[S.DocumentOut])
def documents(deps: Deps = Depends(get_deps)):
    docs = deps.store.documents.list_documents(include_inactive=True)
    return [document_out(d, deps.store.documents.list_versions(d.id)) for d in docs]


def _submit(deps: Deps):
    if deps.submit_upload is not None:
        return deps.submit_upload
    from pharmassist.ingest.submit import submit_upload
    return submit_upload


def _upload_out(deps: Deps, result) -> S.UploadOut:
    doc = result.document
    versions = deps.store.documents.list_versions(doc.id)
    return S.UploadOut(document=document_out(doc, versions), version=version_out(result.version),
                       job=job_out(result.job, doc.id, doc.title) if result.job else None, reused=bool(result.reused))


def _call_submit(deps: Deps, **kw) -> S.UploadOut:
    try:
        result = _submit(deps)(deps.store, cfg=deps.cfg, storage=deps.storage, queue=deps.queue, **kw)
    except Exception as e:
        code = getattr(e, "code", None)
        if type(e).__name__ == "UploadRejected" and code in REJECTION_STATUS:
            raise ApiError(REJECTION_STATUS[code], code, getattr(e, "message", None) or str(e))
        raise
    return _upload_out(deps, result)


@router.post("/documents", response_model=S.UploadOut, status_code=201)
async def upload_document(file: UploadFile = File(...), doc_id: str = Form(...), title: str = Form(...),
                          program: str = Form(...), doc_type: str = Form(""), authority: str = Form("advisory"),
                          publisher: str = Form(""), doc_date: str = Form("unknown"), source_url: str = Form(""),
                          admin: User = Depends(require_admin), deps: Deps = Depends(get_deps)):
    problems = []
    if not SLUG.match(doc_id):
        problems.append("doc_id")
    if program not in PROGRAMS:
        problems.append("program")
    if authority not in AUTHORITIES:
        problems.append("authority")
    if not title.strip() or len(title) > 300:
        problems.append("title")
    if not DOC_DATE.match(doc_date.strip() or "unknown"):
        problems.append("doc_date")
    if source_url and not source_url.startswith("https://"):
        problems.append("source_url")
    if problems:
        raise ApiError(422, "validation_error", "Check the request fields: " + ", ".join(sorted(problems)) + ".")
    max_bytes = int((deps.cfg.get("uploads") or {}).get("max_bytes", 50 * 1024 * 1024))
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ApiError(413, "upload_too_large", f"Uploads are limited to {max_bytes // (1024 * 1024)} MB.")
    existing = deps.store.documents.get_document(doc_id)
    document = Document(id=doc_id, title=title.strip(), program=program, doc_type=doc_type.strip(), authority=authority,
                        publisher=publisher.strip(), doc_date=doc_date.strip() or "unknown",
                        source_url=source_url.strip() or None,
                        active_version_id=existing.active_version_id if existing else None,
                        created_by=existing.created_by if existing else admin.id)
    out = _call_submit(deps, file_bytes=data, file_name=file.filename or f"{doc_id}.bin",
                       content_type=file.content_type or "application/octet-stream", document=document,
                       requested_by=admin.id)
    log.info("upload %s version=%s reused=%s by %s", doc_id, out.version.id, out.reused, admin.id)
    return out


def _reindex_source(deps: Deps, doc: Document | None):
    """The version whose stored file a re-index rebuilds from: the active one, else the newest version
    that has a file (any status), so a document removed from the index can come back."""
    if doc is None:
        return None
    if doc.active_version_id:
        return deps.store.documents.get_version(doc.active_version_id)
    versions = [v for v in deps.store.documents.list_versions(doc.id) if v.s3_key]
    return max(versions, key=lambda v: (v.created_at is not None, v.created_at), default=None)


@router.post("/documents/{doc_id}/reindex", response_model=S.UploadOut)
def reindex_document(doc_id: str, admin: User = Depends(require_admin), deps: Deps = Depends(get_deps)):
    doc = deps.store.documents.get_document(doc_id) if SLUG.match(doc_id) else None
    version = _reindex_source(deps, doc)
    if version is None:
        raise not_found("No version to re-index.")
    try:
        data = deps.storage.get_bytes(version.s3_key)
    except Exception as e:
        log.error("reindex %s: file fetch failed: %s", doc_id, type(e).__name__)
        raise ApiError(404, "not_found", "The version's file is not available.")
    out = _call_submit(deps, file_bytes=data, file_name=version.file_name, content_type=version.content_type,
                       document=doc, requested_by=admin.id, force=True)
    log.info("reindex %s from=%s version=%s by %s", doc_id, version.id, out.version.id, admin.id)
    return out


def _open_job(deps: Deps, doc_id: str):
    """A queued or running job on any version of the document, or None."""
    for v in deps.store.documents.list_versions(doc_id):
        for status in ("queued", "running"):
            if deps.store.documents.list_jobs(version_id=v.id, status=status, limit=1).items:
                return v.id
    return None


@router.delete("/documents/{doc_id}/index", response_model=S.IndexRemovedOut)
def remove_from_index(doc_id: str, admin: User = Depends(require_admin), deps: Deps = Depends(get_deps)):
    doc = deps.store.documents.get_document(doc_id) if SLUG.match(doc_id) else None
    if doc is None or not doc.active_version_id:
        raise not_found("No indexed version to remove.")
    busy = _open_job(deps, doc_id)
    if busy:
        raise ApiError(409, "conflict", "A job for this document is queued or running.")
    try:
        result = deps.store.documents.deactivate(doc_id)
    except NotFound:
        raise not_found("No indexed version to remove.")
    try:   # answers that cited this document were cached under an older generation
        removed = deps.cache.invalidate(before_generation=result["generation"])
        log.info("cache: %s stale entries removed after %s left the index", removed, doc_id)
    except Exception as e:
        log.warning("cache invalidation failed: %s", type(e).__name__)
    log.info("index removal %s version=%s removed=%s generation=%s by %s", doc_id, result["version_id"],
             result["removed"], result["generation"], admin.id)
    return S.IndexRemovedOut(**result)


@router.get("/jobs", response_model=S.Page[S.JobOut])
def jobs(status: str | None = Query(None, pattern="^(queued|running|succeeded|failed|dead_letter|skipped)$"),
         version_id: str | None = None, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
         deps: Deps = Depends(get_deps)):
    page = deps.store.documents.list_jobs(version_id=version_id, status=status, offset=offset, limit=limit)
    memo: dict[str, tuple[str, str | None]] = {}

    def document(vid: str) -> tuple[str, str | None]:
        if vid not in memo:
            v = deps.store.documents.get_version(vid)
            d = deps.store.documents.get_document(v.document_id) if v else None
            memo[vid] = (v.document_id if v else "", d.title if d else None)
        return memo[vid]
    return S.Page(items=[job_out(j, *document(j.version_id)) for j in page.items], total=page.total,
                  offset=page.offset, limit=page.limit)


# ---------------------------------------------------------------- users

@router.get("/users", response_model=S.Page[S.UserOut])
def users(q: str | None = Query(None, max_length=200), offset: int = Query(0, ge=0),
          limit: int = Query(50, ge=1, le=200), deps: Deps = Depends(get_deps)):
    page = deps.store.users.list(offset=offset, limit=limit, q=q or None)
    return S.Page(items=[user_out(u) for u in page.items], total=page.total, offset=page.offset, limit=page.limit)


@router.patch("/users/{user_id}", response_model=S.UserOut)
def patch_user(user_id: str, body: S.UserPatchIn, admin: User = Depends(require_admin),
               deps: Deps = Depends(get_deps)):
    if user_id == admin.id and (body.role == "staff" or body.is_active is False):
        raise forbidden("You can't demote or deactivate your own account.")
    try:
        user = deps.store.users.update(user_id, role=body.role, is_active=body.is_active,
                                       display_name=body.display_name.strip() if body.display_name is not None else None)
    except NotFound:
        raise not_found("No such user.")
    if body.is_active is False or body.role is not None:
        deps.store.tokens.revoke_all(user_id)      # a role or access change takes effect at the next refresh
    log.info("user %s updated by %s", user_id, admin.id)
    return user_out(user)


# ---------------------------------------------------------------- cache

@router.get("/cache/stats", response_model=S.CacheStatsOut)
def cache_stats(deps: Deps = Depends(get_deps)):
    return S.CacheStatsOut(**deps.cache.stats())


@router.delete("/cache", response_model=S.CacheClearOut)
def clear_cache(admin: User = Depends(require_admin), deps: Deps = Depends(get_deps)):
    removed = deps.cache.invalidate()
    deps.cache.reset_stats()        # the hit rate shown afterwards is the rate since this clear
    log.info("cache cleared (%d entries) by %s", removed, admin.id)
    return S.CacheClearOut(removed=removed)
