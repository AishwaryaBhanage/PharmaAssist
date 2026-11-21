"""POST /ask and the user's conversations (DESIGN.md, Architecture).

The pipeline: authenticate -> validate length -> usage limits (per user, global, spend cap) ->
normalize and embed the question once -> semantic cache lookup for the current index generation
(a hit returns the stored answer and citations, marked cached, and skips the model) -> otherwise the
agent on the bounded pool -> citations as the UI shows them -> persist the message in a conversation
(new, titled with the question, or the caller's own) -> settle spend -> cache the answer only when
it was answered with citations -> return.

The no-answer rule: whenever the agent's status isn't `answered` or no citation survived, the answer
text is exactly NO_ANSWER_TEXT. The agent enforces it; this layer asserts it and corrects a stray
wording rather than letting one through. Logs carry ids and outcomes, never question text.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid

from fastapi import APIRouter, Depends, Query, Request, Response

from app.answer_service import AnswerTimeout
from app.api import schemas as S
from app.api.schemas import NO_ANSWER_TEXT
from app.auth import current_user
from app.citations import citation_view
from app.deps import API, Deps, get_deps
from app.errors import ApiError, not_found, request_id_of
from app.limits import Refused
from app.views import answer_out, conversation_out, conversation_summary
from pharmassist.cache.base import CacheEntry, normalize_question
from pharmassist.store.protocols import Message, User

log = logging.getLogger("pharmassist.app")
router = APIRouter(prefix=API, tags=["ask"])

# The worker that activates a new document version can't reach the cache, so the first question
# after a generation change evicts the entries answered against older generations. Lookups already
# filter by generation, so this only reclaims space; a failure is logged and ignored.
_gen_lock = threading.Lock()
_gen_seen: dict[int, int] = {}   # id(cache) -> last generation seen


def _drop_stale_cache(deps: Deps, generation: int) -> None:
    key = id(deps.cache)
    with _gen_lock:
        last = _gen_seen.get(key)
        _gen_seen[key] = generation
    if last is not None and generation > last:
        try:
            removed = deps.cache.invalidate(before_generation=generation)
            log.info("cache: generation %s -> %s, %s stale entries removed", last, generation, removed)
        except Exception as e:
            log.warning("cache invalidation failed: %s", type(e).__name__)


def _settle(deps: Deps, user: User, cost: float | None, request_id: str, questions: int = 1) -> None:
    try:
        deps.limiter.settle(user.id, cost)
    except Exception as e:
        log.error("ask %s: usage settle failed: %s", request_id, type(e).__name__)
    try:  # the durable copy of the day's counters
        deps.store.stats.add_usage(deps.clock().date(), questions=questions, spend_usd=float(cost or 0))
    except Exception as e:
        log.error("ask %s: usage mirror failed: %s", request_id, type(e).__name__)


def _conversation(deps: Deps, user: User, conversation_id: str | None, question: str):
    if conversation_id:
        conv = deps.store.conversations.get(conversation_id, user_id=user.id)
        if conv is None:
            raise not_found("No such conversation.")
        return conv
    return None


def _title(question: str) -> str:
    return question if len(question) <= 80 else question[:77].rstrip() + "..."


@router.post("/ask", response_model=S.AnswerOut)
def ask(body: S.AskIn, request: Request, response: Response, user: User = Depends(current_user),
        deps: Deps = Depends(get_deps)):
    request_id = request_id_of(request) or str(uuid.uuid4())
    lo, hi = deps.app_cfg.get("question_chars", [3, 2000])
    text = normalize_question(body.question)
    if len(text) < lo:
        raise ApiError(422, "question_too_short", "Enter a question.")
    if len(text) > hi:
        raise ApiError(422, "question_too_long", f"Questions are limited to {hi} characters.")
    conv = _conversation(deps, user, body.conversation_id, text)

    try:
        deps.limiter.admit(user.id)
    except Refused as r:
        log.warning("ask %s refused: %s", request_id, r.code)
        raise ApiError(429, r.code, r.message, {"Retry-After": str(r.retry_after)})
    except Exception as e:  # the limiter's store is down: refuse rather than spend without limits
        log.error("ask %s: usage check failed: %s", request_id, type(e).__name__)
        raise ApiError(503, "limits_unavailable", "The assistant is unavailable right now. Please try again.",
                       {"Retry-After": "5"})

    started = time.perf_counter()
    embedding = None
    try:
        embedding = deps.answers.embed(text)
    except Exception as e:  # no embedding: skip the cache, the agent still answers
        log.error("ask %s: embedding failed: %s", request_id, type(e).__name__)
    try:
        generation = deps.store.documents.generation()
    except Exception as e:
        log.error("ask %s: generation lookup failed: %s", request_id, type(e).__name__)
        generation = None
    if generation is not None:
        _drop_stale_cache(deps, generation)

    hit = None
    if embedding is not None and generation is not None:
        try:
            hit = deps.cache.lookup(embedding, generation)
        except Exception as e:
            log.error("ask %s: cache lookup failed: %s", request_id, type(e).__name__)

    now = deps.clock()
    if conv is None:
        conv = deps.store.conversations.create(user.id, _title(text))

    if hit is not None:
        e = hit.entry
        msg = Message(id=str(uuid.uuid4()), conversation_id=conv.id, user_id=user.id, request_id=request_id,
                      question=text, status="answered", answer=e.answer, created_at=now, agent_status="cached",
                      assumption=e.assumption, citations=list(e.citations), conflicts=list(e.conflicts),
                      needs_review=False, provider="cache", model=e.model, fallback_used=False, cached=True,
                      cache_hit_id=e.id, cache_similarity=round(hit.similarity, 4),
                      latency_s=round(time.perf_counter() - started, 3), cost_usd=0.0, generation=generation)
        deps.store.conversations.add_message(msg)
        _settle(deps, user, 0.0, request_id)
        log.info("ask %s cached sim=%.3f %.2fs", request_id, hit.similarity, msg.latency_s)
        return answer_out(msg, matched_question=e.question)

    context = {"user_id": user.id, "conversation_id": conv.id, "generation": generation}
    try:
        result = deps.answers.answer(text, request_id=request_id, context=context)
    except AnswerTimeout:
        _settle(deps, user, 0.0, request_id)
        log.warning("ask %s timed out", request_id)
        raise ApiError(504, "timeout", "The assistant took too long to answer. Please try again.")
    except Exception as e:
        _settle(deps, user, 0.0, request_id)
        log.error("ask %s failed: %s", request_id, type(e).__name__)
        raise ApiError(502, "answer_failed", "The assistant could not answer right now. Please try again.")

    catalog = deps.store.documents.catalog()
    citations = [citation_view(c, catalog, deps.store.content.figures_for_page)
                 for c in result.get("citations") or []]
    status = "answered" if result.get("status") == "answered" and citations else "no_answer"
    answer = result.get("answer") or ""
    if status == "no_answer" and answer != NO_ANSWER_TEXT:
        log.warning("ask %s: agent returned a non-canonical no-answer text; replaced", request_id)
        answer = NO_ANSWER_TEXT
    if status == "no_answer":
        citations = []
    cost = result.get("cost_usd")
    timing = result.get("timing_s") or {}
    msg = Message(id=str(uuid.uuid4()), conversation_id=conv.id, user_id=user.id, request_id=request_id,
                  question=text, status=status, answer=answer, created_at=now,
                  agent_status=result.get("agent_status") or result.get("status"),
                  assumption=result.get("assumption"), citations=citations,
                  conflicts=list(result.get("conflicts_noted") or []), needs_review=bool(result.get("needs_review")),
                  provider=result.get("provider"), model=result.get("model") or result.get("answered_by"),
                  fallback_used=bool(result.get("fallback_used")), cached=False,
                  latency_s=timing.get("total") if timing.get("total") is not None else round(time.perf_counter() - started, 3),
                  cost_usd=cost, tokens=dict(result.get("tokens") or {}), trace_id=result.get("trace_id"),
                  generation=generation)
    deps.store.conversations.add_message(msg)
    _settle(deps, user, cost, request_id)
    if status == "answered" and embedding is not None and generation is not None:
        try:
            deps.cache.put(CacheEntry(id=uuid.uuid4().hex, question=text, answer=answer, status="answered",
                                      citations=citations, generation=generation, created_at=now,
                                      assumption=msg.assumption, conflicts=msg.conflicts, source_message_id=msg.id,
                                      model=msg.model, provider=msg.provider), embedding)
        except Exception as e:
            log.error("ask %s: cache put failed: %s", request_id, type(e).__name__)
    log.info("ask %s %s needs_review=%s provider=%s fallback=%s %.1fs", request_id, status, msg.needs_review,
             msg.provider, msg.fallback_used, msg.latency_s or 0)
    return answer_out(msg)


# ---------------------------------------------------------------- conversations

@router.get("/conversations", response_model=S.Page[S.ConversationSummaryOut])
def list_conversations(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
                       user: User = Depends(current_user), deps: Deps = Depends(get_deps)):
    page = deps.store.conversations.list_for_user(user.id, offset=offset, limit=limit)
    return S.Page(items=[conversation_summary(c) for c in page.items], total=page.total, offset=page.offset,
                  limit=page.limit)


@router.get("/conversations/{conversation_id}", response_model=S.ConversationOut)
def get_conversation(conversation_id: str, user: User = Depends(current_user), deps: Deps = Depends(get_deps)):
    conv = deps.store.conversations.get(conversation_id, user_id=user.id)
    if conv is None:
        raise not_found("No such conversation.")
    return conversation_out(conv, deps.store.conversations.messages(conv.id))


@router.delete("/conversations/{conversation_id}", status_code=204, response_class=Response)
def delete_conversation(conversation_id: str, user: User = Depends(current_user), deps: Deps = Depends(get_deps)):
    if not deps.store.conversations.delete(conversation_id, user.id):
        raise not_found("No such conversation.")
    return Response(status_code=204)
