"""Staff feedback on an answer: `POST /messages/{id}/feedback` rates one of the caller's own messages
(insert or replace). Comments are scrubbed of identifier-shaped text (long digit runs such as
prescription numbers, dates, phone numbers, email addresses) before they are stored, as in v1."""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Depends

from app.api import schemas as S
from app.auth import current_user
from app.deps import API, Deps, get_deps
from app.errors import not_found
from app.views import feedback_out
from pharmassist.store.protocols import NotFound, User

log = logging.getLogger("pharmassist.app")
router = APIRouter(prefix=API, tags=["feedback"])

IDENTIFIERS = [
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),                                   # email
    re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b"),    # dates (e.g. date of birth)
    re.compile(r"(?<!\w)\(?\d{3}\)?[-. ]?\d{3}[-. ]?\d{4}(?!\w)"),            # phone numbers
    re.compile(r"\b(?:rx|mrn|dob)\s*#?\s*[:\-]?\s*\w+", re.I),                 # labelled identifiers
    re.compile(r"\d{6,}"),                                                     # long digit runs (Rx / member ids)
]


def scrub_comment(text: str) -> str:
    for pattern in IDENTIFIERS:
        text = pattern.sub("[removed]", text)
    return text


@router.post("/messages/{message_id}/feedback", response_model=S.FeedbackOut)
def post_feedback(message_id: str, body: S.FeedbackIn, user: User = Depends(current_user),
                  deps: Deps = Depends(get_deps)):
    if deps.store.conversations.message(message_id, user_id=user.id) is None:
        raise not_found("No such answer to rate.")
    comment = scrub_comment(body.comment.strip()) if body.comment and body.comment.strip() else None
    try:
        saved = deps.store.feedback.save(message_id, user.id, body.rating, body.reason, comment)
    except NotFound:
        raise not_found("No such answer to rate.")
    log.info("feedback %s %s", message_id, saved.rating)
    return feedback_out(saved)
