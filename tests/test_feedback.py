"""Conversations (list, get, delete: own only) and feedback on own messages (insert, replace,
scrubbed comments, ownership, validation)."""

import pytest

from app.feedback import scrub_comment
from fakes_api import QUESTION, build_app, client, make_user, login


@pytest.fixture
def http(tmp_path):
    app, deps = build_app(tmp_path)
    deps.store.add_document()
    make_user(deps, "s@example.com")
    make_user(deps, "other@example.com")
    with client(app) as c:
        c.deps, c.hdrs, c.other = deps, login(c, "s@example.com"), login(c, "other@example.com")
        yield c


def ask(http, question=QUESTION, headers=None):
    r = http.post("/api/v1/ask", json={"question": question}, headers=headers or http.hdrs)
    assert r.status_code == 200, r.text
    return r.json()


def test_conversations_are_listed_newest_first_and_only_the_owners(http):
    a = ask(http)
    http.deps.clock.advance(seconds=5)
    b = ask(http, "Second question about Ozempic")
    ask(http, "Someone else's question", headers=http.other)
    page = http.get("/api/v1/conversations", headers=http.hdrs).json()
    assert page["total"] == 2 and [c["id"] for c in page["items"]] == [b["conversation_id"], a["conversation_id"]]
    assert page["items"][0]["title"] == "Second question about Ozempic" and page["items"][0]["message_count"] == 1
    assert set(page["items"][0]) == {"id", "title", "created_at", "updated_at", "message_count"}
    paged = http.get("/api/v1/conversations?offset=1&limit=1", headers=http.hdrs).json()
    assert paged["total"] == 2 and len(paged["items"]) == 1 and paged["offset"] == 1 and paged["limit"] == 1


def test_a_conversation_shows_its_messages_with_feedback(http):
    a = ask(http)
    http.post(f"/api/v1/messages/{a['message_id']}/feedback", json={"rating": "helpful"}, headers=http.hdrs)
    conv = http.get(f"/api/v1/conversations/{a['conversation_id']}", headers=http.hdrs).json()
    assert conv["id"] == a["conversation_id"] and len(conv["messages"]) == 1
    m = conv["messages"][0]
    assert m["question"] == QUESTION and m["answer"] == a["answer"] and m["message_id"] == a["message_id"]
    assert m["feedback"]["rating"] == "helpful" and m["feedback"]["message_id"] == a["message_id"]
    assert m["citations"] == a["citations"]


def test_another_users_conversation_is_not_found_not_forbidden(http):
    a = ask(http)
    for method in ("get", "delete"):
        r = getattr(http, method)(f"/api/v1/conversations/{a['conversation_id']}", headers=http.other)
        assert r.status_code == 404 and r.json()["code"] == "not_found"
    assert http.get(f"/api/v1/conversations/{a['conversation_id']}", headers=http.hdrs).status_code == 200


def test_delete_removes_the_conversation_and_its_messages(http):
    a = ask(http)
    r = http.delete(f"/api/v1/conversations/{a['conversation_id']}", headers=http.hdrs)
    assert r.status_code == 204 and r.content == b""
    assert http.get(f"/api/v1/conversations/{a['conversation_id']}", headers=http.hdrs).status_code == 404
    assert http.delete(f"/api/v1/conversations/{a['conversation_id']}", headers=http.hdrs).status_code == 404
    assert http.deps.store.conversations.message(a["message_id"]) is None


def test_feedback_is_saved_then_replaced(http):
    a = ask(http)
    url = f"/api/v1/messages/{a['message_id']}/feedback"
    r = http.post(url, json={"rating": "unhelpful", "reason": "outdated", "comment": "The PDL changed in March."},
                  headers=http.hdrs)
    assert r.status_code == 200, r.text
    first = r.json()
    assert first == {"message_id": a["message_id"], "rating": "unhelpful", "reason": "outdated",
                     "comment": "The PDL changed in March.", "created_at": first["created_at"],
                     "updated_at": first["updated_at"]}
    http.deps.clock.advance(seconds=30)
    r = http.post(url, json={"rating": "helpful"}, headers=http.hdrs)
    second = r.json()
    assert second["rating"] == "helpful" and second["reason"] is None and second["comment"] is None
    assert second["created_at"] == first["created_at"] and second["updated_at"] > first["updated_at"]
    assert len(http.deps.store.feedback.rows) == 1


def test_feedback_only_on_own_existing_messages(http):
    a = ask(http)
    r = http.post(f"/api/v1/messages/{a['message_id']}/feedback", json={"rating": "helpful"}, headers=http.other)
    assert r.status_code == 404 and r.json()["code"] == "not_found"
    r = http.post("/api/v1/messages/00000000-0000-0000-0000-000000000000/feedback", json={"rating": "helpful"},
                  headers=http.hdrs)
    assert r.status_code == 404
    r = http.post(f"/api/v1/messages/{a['message_id']}/feedback", json={"rating": "helpful"})
    assert r.status_code == 401


@pytest.mark.parametrize("body", [{"rating": "up"}, {"rating": "helpful", "reason": "meh"}, {},
                                  {"rating": "helpful", "comment": "x" * 1001}])
def test_feedback_validation(http, body):
    a = ask(http)
    r = http.post(f"/api/v1/messages/{a['message_id']}/feedback", json=body, headers=http.hdrs)
    assert r.status_code == 422 and r.json()["code"] == "validation_error" and "meh" not in r.text


def test_comments_are_scrubbed_of_identifiers(http):
    a = ask(http)
    comment = "Rx 12345678 for jane.roe@example.com, DOB 01/02/1980, call 555-123-4567. Otherwise fine."
    r = http.post(f"/api/v1/messages/{a['message_id']}/feedback", json={"rating": "unhelpful", "comment": comment},
                  headers=http.hdrs)
    saved = r.json()["comment"]
    for leak in ("12345678", "jane.roe", "1980", "555-123"):
        assert leak not in saved
    assert "Otherwise fine." in saved and "[removed]" in saved
    assert http.deps.store.feedback.rows[a["message_id"]].comment == saved


def test_scrub_comment_patterns():
    assert scrub_comment("member id 000123456 and mrn: ABC99") == "member id [removed] and [removed]"
    assert scrub_comment("short digits 12345 stay") == "short digits 12345 stay"
    assert scrub_comment("blank comment   ") == "blank comment   "
