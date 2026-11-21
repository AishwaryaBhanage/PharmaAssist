"""Admin endpoints: stats, conversation search filters, message detail, documents, upload (happy path
and every rejection), reindex, jobs, users and the self-demotion guard, cache stats and clearing.
`submit_upload` (stream E) is faked; its rejections are reproduced by name and code."""

import io
from dataclasses import dataclass
from datetime import timedelta

import pytest

from fakes_api import QUESTION, agent_result, build_app, client, make_user, login
from pharmassist.store.protocols import DocumentVersion


class UploadRejected(Exception):
    """Stream E's exception, by name and shape."""
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass
class UploadResult:
    document: object
    version: object
    job: object
    reused: bool = False


class FakeSubmit:
    """Behaves like pharmassist.ingest.submit.submit_upload: stores the file, creates a queued version
    and a job, reuses an identical version, honours `force`."""
    def __init__(self, reject=None):
        self.calls, self.reject = [], reject

    def __call__(self, store, *, file_bytes, file_name, content_type, document, requested_by, cfg, storage=None,
                 queue=None, force=False):
        import hashlib
        self.calls.append(dict(file_bytes=file_bytes, file_name=file_name, content_type=content_type,
                               document=document, requested_by=requested_by, storage=storage, queue=queue, force=force))
        if self.reject:
            raise UploadRejected(*self.reject)
        sha = hashlib.sha256(file_bytes).hexdigest()
        doc = store.documents.upsert_document(document)
        existing = store.documents.version_by_sha(doc.id, sha)
        if existing and not force:
            if existing.status == "active":
                return UploadResult(doc, existing, None, reused=True)
            raise UploadRejected("duplicate_version", "This file is already being indexed.")
        vid = f"{doc.id}:{sha[:16]}" + (":reindex" if existing else "")
        key = f"uploads/{doc.id}/{sha[:16]}/{file_name}"
        if storage is not None:
            storage.put_bytes(key, file_bytes, content_type=content_type)
        version = DocumentVersion(id=vid, document_id=doc.id, sha256=sha if not existing else sha + ":r", s3_key=key,
                                  file_name=file_name, content_type=content_type, bytes=len(file_bytes), status="queued",
                                  created_by=requested_by)
        version = store.documents.create_version(version)
        job = store.documents.create_job(version.id, requested_by)
        return UploadResult(doc, version, job)


@pytest.fixture
def http(tmp_path):
    submit = FakeSubmit()
    app, deps = build_app(tmp_path, submit_upload=submit)
    deps.store.add_document()
    make_user(deps, "s@example.com", display_name="Sam Staff")
    make_user(deps, "admin@example.com", role="admin")
    with client(app) as c:
        c.deps, c.submit = deps, submit
        c.staff, c.admin = login(c, "s@example.com"), login(c, "admin@example.com")
        yield c


def ask(http, question=QUESTION, headers=None, **kw):
    r = http.post("/api/v1/ask", json={"question": question, **kw}, headers=headers or http.staff)
    assert r.status_code == 200, r.text
    return r.json()


def rate(http, message_id, rating, comment=None):
    r = http.post(f"/api/v1/messages/{message_id}/feedback", json={"rating": rating, "comment": comment},
                  headers=http.staff)
    assert r.status_code == 200


# ---------------------------------------------------------------- stats

def test_stats_overview(http):
    a = ask(http)
    rate(http, a["message_id"], "helpful")
    b = ask(http, QUESTION.upper())                       # a cache hit
    rate(http, b["message_id"], "unhelpful")
    http.deps.answers.ask_fn.result = agent_result(status="no_answer")
    ask(http, "Something the corpus does not cover at all")
    r = http.get("/api/v1/admin/stats?days=7", headers=http.admin)
    assert r.status_code == 200, r.text
    s = r.json()
    assert (s["questions"], s["answered"], s["no_answer"], s["cached"]) == (3, 2, 1, 1)
    assert (s["helpful"], s["unhelpful"], s["fallback"]) == (1, 1, 0)
    assert s["spend_usd"] == 0.10 and s["spend_today_usd"] == 0.10 and s["spend_cap_usd"] == 10.0
    assert s["active_users"] == 1 and s["users_total"] == 2 and s["documents_active"] == 1
    assert s["cache"]["hits"] == 1 and s["cache"]["backend"] == "memory-fake"
    assert s["latency_p50_s"] is not None and len(s["per_day"]) == 1
    assert s["per_day"][0] == {"day": http.deps.clock().strftime("%Y-%m-%d"), "questions": 3, "helpful": 1,
                               "unhelpful": 1, "no_answer": 1, "cached": 1}
    assert http.get("/api/v1/admin/stats?days=0", headers=http.admin).status_code == 422


# ---------------------------------------------------------------- conversations

def test_admin_conversation_search_filters(http):
    a = ask(http)
    rate(http, a["message_id"], "unhelpful", "Wrong tier for Trulicity")
    http.deps.clock.advance(minutes=5)
    b = ask(http, "Metformin dosing with CKD under VA")
    rate(http, b["message_id"], "helpful")
    make_user(http.deps, "other@example.com")
    other = login(http, "other@example.com")
    http.deps.clock.advance(minutes=5)
    c = ask(http, "Lantus coverage under Part D", headers=other)

    def search(**params):
        r = http.get("/api/v1/admin/conversations", params=params, headers=http.admin)
        assert r.status_code == 200, r.text
        return r.json()
    everything = search()
    assert everything["total"] == 3 and [m["message_id"] for m in everything["items"]] == [c["message_id"], b["message_id"], a["message_id"]]
    item = everything["items"][2]
    assert item["user_email"] == "s@example.com" and item["question"] == QUESTION
    assert item["feedback"]["comment"] == "Wrong tier for Trulicity" and item["cost_usd"] == 0.05
    assert item["tokens"] == {"input": 1200, "output": 300} and item["trace_id"] == "trace-1"
    assert item["agent_status"] == "answered" and item["user_id"]
    assert [m["message_id"] for m in search(rating="unhelpful")["items"]] == [a["message_id"]]
    assert [m["message_id"] for m in search(user="other@example.com")["items"]] == [c["message_id"]]
    assert [m["message_id"] for m in search(user=http.deps.store.users.by_email_for_login("other@example.com").id)["items"]] == [c["message_id"]]
    assert search(user="nobody@example.com")["total"] == 0
    assert [m["message_id"] for m in search(q="metformin")["items"]] == [b["message_id"]]
    since = (http.deps.clock() - timedelta(minutes=7, seconds=30)).isoformat()
    assert [m["message_id"] for m in search(**{"from": since})["items"]] == [c["message_id"], b["message_id"]]
    until = (http.deps.clock() - timedelta(minutes=7, seconds=30)).isoformat()
    assert [m["message_id"] for m in search(to=until)["items"]] == [a["message_id"]]
    assert search(cached="true")["total"] == 0 and search(status="answered")["total"] == 3
    page = search(offset=1, limit=1)
    assert page["total"] == 3 and len(page["items"]) == 1 and page["items"][0]["message_id"] == b["message_id"]
    bad = http.get("/api/v1/admin/conversations", params={"from": "yesterday"}, headers=http.admin)
    assert bad.status_code == 422 and bad.json()["code"] == "validation_error"
    assert http.get("/api/v1/admin/conversations", params={"rating": "meh"}, headers=http.admin).status_code == 422


def test_admin_message_detail(http):
    a = ask(http)
    r = http.get(f"/api/v1/admin/messages/{a['message_id']}", headers=http.admin)
    assert r.status_code == 200 and r.json()["user_email"] == "s@example.com" and r.json()["answer"] == a["answer"]
    assert http.get("/api/v1/admin/messages/nope", headers=http.admin).status_code == 404


# ---------------------------------------------------------------- documents and uploads

FORM = {"doc_id": "ny_medicaid_pharmacy_policy", "title": "NYRx Pharmacy Policy Manual", "program": "NY Medicaid",
        "doc_type": "policy manual", "authority": "binding", "publisher": "NYS DOH", "doc_date": "2026-02",
        "source_url": "https://newyork.fhsc.com/policy.pdf"}


def upload(http, data=b"%PDF-1.4 fake", name="policy.pdf", ctype="application/pdf", **form):
    return http.post("/api/v1/admin/documents", data={**FORM, **form}, files={"file": (name, io.BytesIO(data), ctype)},
                     headers=http.admin)


def test_documents_list_with_active_and_latest_versions(http):
    r = http.get("/api/v1/admin/documents", headers=http.admin)
    assert r.status_code == 200
    [doc] = r.json()
    assert doc["id"] == "ny_medicaid_pdl" and doc["program"] == "NY Medicaid" and doc["versions"] == 1
    assert doc["active_version"]["status"] == "active" and doc["active_version"]["pages"] == 120
    assert doc["latest_version"]["id"] == doc["active_version"]["id"]
    assert set(doc) == {"id", "title", "program", "doc_type", "authority", "publisher", "doc_date", "source_url",
                        "active_version", "latest_version", "versions"}


def test_upload_happy_path(http):
    r = upload(http)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["document"]["id"] == "ny_medicaid_pharmacy_policy" and body["document"]["active_version"] is None
    assert body["version"]["status"] == "queued" and body["version"]["bytes"] == len(b"%PDF-1.4 fake")
    assert body["version"]["file_name"] == "policy.pdf" and body["version"]["content_type"] == "application/pdf"
    assert body["job"]["status"] == "queued" and body["job"]["document_id"] == "ny_medicaid_pharmacy_policy"
    assert body["reused"] is False and body["document"]["latest_version"]["id"] == body["version"]["id"]
    [call] = http.submit.calls
    admin = http.deps.store.users.by_email_for_login("admin@example.com")
    assert call["requested_by"] == admin.id and call["force"] is False and call["storage"] is http.deps.storage
    assert call["document"].title == FORM["title"] and call["document"].created_by == admin.id
    assert call["document"].source_url == FORM["source_url"] and call["document"].doc_type == "policy manual"
    assert (http.deps.storage.root / body["version"]["id"].split(":")[0]).exists() is False
    assert http.get("/api/v1/admin/jobs", headers=http.admin).json()["items"][0]["id"] == body["job"]["id"]
    docs = http.get("/api/v1/admin/documents", headers=http.admin).json()
    assert [d["id"] for d in docs] == ["ny_medicaid_pdl", "ny_medicaid_pharmacy_policy"]


def test_upload_reuses_an_identical_active_file(http):
    first = upload(http).json()
    v = http.deps.store.documents.get_version(first["version"]["id"])
    http.deps.store.documents.set_version_status(v.id, "verifying")
    http.deps.store.documents.activate(v.id)
    again = upload(http)
    assert again.status_code == 201 and again.json()["reused"] is True and again.json()["job"] is None
    assert again.json()["version"]["id"] == first["version"]["id"]


@pytest.mark.parametrize("form, field", [
    ({"doc_id": "Bad Slug!"}, "doc_id"), ({"program": "Medicaid"}, "program"), ({"authority": "law"}, "authority"),
    ({"title": "   "}, "title"), ({"doc_date": "Feb 2026"}, "doc_date"), ({"source_url": "http://insecure"}, "source_url")])
def test_upload_form_validation(http, form, field):
    r = upload(http, **form)
    assert r.status_code == 422 and r.json()["code"] == "validation_error" and field in r.json()["message"]
    assert http.submit.calls == []


def test_upload_without_a_file_or_required_fields(http):
    r = http.post("/api/v1/admin/documents", data=FORM, headers=http.admin)
    assert r.status_code == 422 and r.json()["code"] == "validation_error" and "file" in r.json()["message"]
    r = http.post("/api/v1/admin/documents", data={"title": "x"}, files={"file": ("a.pdf", io.BytesIO(b"x"))},
                  headers=http.admin)
    assert r.status_code == 422 and "doc_id" in r.json()["message"] and "program" in r.json()["message"]


@pytest.mark.parametrize("code, status", [("upload_too_large", 413), ("upload_type", 400), ("upload_pages", 400),
                                          ("duplicate_version", 409)])
def test_each_submit_rejection_maps_to_its_status(http, code, status):
    http.submit.reject = (code, f"rejected: {code}")
    r = upload(http)
    assert r.status_code == status and r.json() == {"code": code, "message": f"rejected: {code}",
                                                    "request_id": r.headers["x-request-id"]}


def test_oversized_uploads_are_refused_by_the_api_itself(tmp_path):
    from fakes_api import test_config
    submit = FakeSubmit()
    app, deps = build_app(tmp_path, submit_upload=submit, cfg=test_config(uploads={"max_bytes": 1000}))
    make_user(deps, "admin@example.com", role="admin")
    with client(app) as http:
        http.admin = login(http, "admin@example.com")
        r = upload(http, data=b"x" * 1001)
        assert r.status_code == 413 and r.json()["code"] == "upload_too_large" and submit.calls == []
        assert upload(http, data=b"x" * 1000).status_code == 201
        huge = http.post("/api/v1/admin/documents", content=b"x" * 10, headers={**http.admin, "content-length": str(2_000_000)})
        assert huge.status_code == 413 and huge.json()["code"] == "too_large"


def test_unexpected_submit_errors_are_a_fixed_500(tmp_path):
    def boom(*a, **k):
        raise RuntimeError("s3 credentials AKIA...")
    app, deps = build_app(tmp_path, submit_upload=boom)
    make_user(deps, "admin@example.com", role="admin")
    with client(app, raise_server_exceptions=False) as http:
        http.admin = login(http, "admin@example.com")
        r = upload(http)
    assert r.status_code == 500 and r.json()["code"] == "server_error" and "AKIA" not in r.text


def test_reindex_resubmits_the_active_file_with_force(http):
    doc = http.deps.store.documents.get_document("ny_medicaid_pdl")
    version = http.deps.store.documents.get_version(doc.active_version_id)
    http.deps.storage.put_bytes(version.s3_key, b"%PDF-1.4 original")
    r = http.post("/api/v1/admin/documents/ny_medicaid_pdl/reindex", headers=http.admin)
    assert r.status_code == 200, r.text
    body = r.json()
    [call] = http.submit.calls
    assert call["force"] is True and call["file_bytes"] == b"%PDF-1.4 original"
    assert call["file_name"] == version.file_name and call["content_type"] == "application/pdf"
    assert call["document"].id == "ny_medicaid_pdl" and call["document"].title == doc.title
    assert body["version"]["id"] != version.id and body["version"]["status"] == "queued" and body["job"]
    assert body["document"]["active_version"]["id"] == version.id and body["document"]["versions"] == 2


def test_reindex_errors(http):
    r = http.post("/api/v1/admin/documents/unknown_doc/reindex", headers=http.admin)
    assert r.status_code == 404 and r.json()["code"] == "not_found"
    http.deps.store.add_document("queued_only", status="queued", sha="c" * 64)
    r = http.post("/api/v1/admin/documents/queued_only/reindex", headers=http.admin)
    assert r.status_code == 404
    r = http.post("/api/v1/admin/documents/ny_medicaid_pdl/reindex", headers=http.admin)   # file missing in storage
    assert r.status_code == 404 and r.json()["code"] == "not_found" and http.submit.calls == []


# ---------------------------------------------------------------- remove from index

def remove_index(http, doc_id="ny_medicaid_pdl", headers=None):
    return http.delete(f"/api/v1/admin/documents/{doc_id}/index", headers=http.admin if headers is None else headers)


def test_remove_from_index_keeps_the_document_and_drops_cached_answers(http):
    store = http.deps.store
    doc = store.documents.get_document("ny_medicaid_pdl")
    store.add_figure("ny_medicaid_pdl", 34)
    ask(http)                                              # cached under the current generation
    assert len(http.deps.cache.entries) == 1
    g0 = store.documents.generation()
    r = remove_index(http)
    assert r.status_code == 200, r.text
    assert r.json() == {"document_id": "ny_medicaid_pdl", "version_id": doc.active_version_id,
                        "removed": {"chunks": 0, "parents": 0, "figures": 1, "table_rows": 0}, "generation": g0 + 1}
    assert store.documents.get_document("ny_medicaid_pdl").active_version_id is None
    assert store.documents.generation() == g0 + 1
    assert http.deps.cache.entries == {}                   # invalidated before the new generation
    assert store.content.figures_for_page("ny_medicaid_pdl", 34) == []
    [listed] = http.get("/api/v1/admin/documents", headers=http.admin).json()
    assert listed["active_version"] is None and listed["versions"] == 1
    assert listed["latest_version"]["id"] == doc.active_version_id and listed["latest_version"]["status"] == "superseded"
    assert store.documents.get_version(doc.active_version_id).s3_key   # the stored file is untouched
    assert http.get("/api/v1/admin/stats", headers=http.admin).json()["documents_active"] == 0
    again = remove_index(http)                             # nothing indexed any more
    assert again.status_code == 404 and again.json()["code"] == "not_found"


def test_remove_from_index_404_when_nothing_is_indexed(http):
    r = remove_index(http, "unknown_doc")
    assert r.status_code == 404 and r.json() == {"code": "not_found", "message": "No indexed version to remove.",
                                                 "request_id": r.headers["x-request-id"]}
    http.deps.store.add_document("queued_only", status="queued", sha="c" * 64)
    assert remove_index(http, "queued_only").status_code == 404
    assert remove_index(http, "Bad Slug!").status_code == 404


def test_remove_from_index_409_while_a_job_is_open(http):
    body = upload(http, doc_id="ny_medicaid_pdl", title="NYRx PDL", data=b"%PDF-1.4 newer").json()   # a queued rebuild
    r = remove_index(http)
    assert r.status_code == 409 and r.json()["code"] == "conflict"
    assert r.json()["message"] == "A job for this document is queued or running."
    http.deps.store.documents.update_job(body["job"]["id"], status="running", started=True)
    assert remove_index(http).status_code == 409
    http.deps.store.documents.update_job(body["job"]["id"], status="failed", finished=True)
    assert remove_index(http).status_code == 200
    assert http.deps.store.documents.get_document("ny_medicaid_pdl").active_version_id is None


def test_remove_from_index_is_admin_only(http):
    r = remove_index(http, headers=http.staff)
    assert r.status_code == 403 and r.json()["code"] == "forbidden"
    assert http.deps.store.documents.get_document("ny_medicaid_pdl").active_version_id is not None
    assert remove_index(http, headers={}).status_code == 401


def test_reindex_after_removal_rebuilds_from_the_stored_file(http):
    doc = http.deps.store.documents.get_document("ny_medicaid_pdl")
    version = http.deps.store.documents.get_version(doc.active_version_id)
    http.deps.storage.put_bytes(version.s3_key, b"%PDF-1.4 original")
    assert remove_index(http).status_code == 200
    r = http.post("/api/v1/admin/documents/ny_medicaid_pdl/reindex", headers=http.admin)
    assert r.status_code == 200, r.text
    body = r.json()
    [call] = http.submit.calls
    assert call["force"] is True and call["file_bytes"] == b"%PDF-1.4 original" and call["file_name"] == version.file_name
    assert body["job"]["status"] == "queued" and body["version"]["status"] == "queued"
    assert body["document"]["active_version"] is None        # until the worker activates the rebuild
    assert http.get("/api/v1/admin/jobs?status=queued", headers=http.admin).json()["total"] == 1


def test_jobs_listing_and_filters(http):
    upload(http)
    job = http.deps.store.documents.list_jobs().items[0]
    http.deps.store.documents.update_job(job.id, status="failed", attempt=3, stage="parsing", error="bad pdf",
                                         started=True, finished=True)
    r = http.get("/api/v1/admin/jobs", headers=http.admin)
    [j] = r.json()["items"]
    assert j["status"] == "failed" and j["attempt"] == 3 and j["stage"] == "parsing" and j["error"] == "bad pdf"
    assert j["document_id"] == "ny_medicaid_pharmacy_policy" and j["started_at"] and j["finished_at"]
    assert http.get("/api/v1/admin/jobs?status=queued", headers=http.admin).json()["total"] == 0
    assert http.get("/api/v1/admin/jobs?status=exploded", headers=http.admin).status_code == 422
    assert http.get(f"/api/v1/admin/jobs?version_id={j['version_id']}", headers=http.admin).json()["total"] == 1


# ---------------------------------------------------------------- users

def test_users_list_and_patch(http):
    r = http.get("/api/v1/admin/users", headers=http.admin)
    assert r.status_code == 200 and r.json()["total"] == 2
    assert [u["email"] for u in r.json()["items"]] == ["s@example.com", "admin@example.com"]
    assert "password" not in r.text
    assert http.get("/api/v1/admin/users?q=sam", headers=http.admin).json()["total"] == 1
    staff = http.deps.store.users.by_email_for_login("s@example.com")
    r = http.patch(f"/api/v1/admin/users/{staff.id}", json={"role": "admin", "display_name": " Sam "}, headers=http.admin)
    assert r.status_code == 200 and r.json()["role"] == "admin" and r.json()["display_name"] == "Sam"
    assert http.get("/api/v1/admin/stats", headers=http.staff).status_code == 200   # the new admin's token works
    assert all(t.revoked_at for t in http.deps.store.tokens.rows.values() if t.user_id == staff.id)
    r = http.patch(f"/api/v1/admin/users/{staff.id}", json={"is_active": False}, headers=http.admin)
    assert r.json()["is_active"] is False
    assert http.get("/api/v1/auth/me", headers=http.staff).status_code == 403
    assert http.patch("/api/v1/admin/users/nope", json={"role": "staff"}, headers=http.admin).status_code == 404
    bad = http.patch(f"/api/v1/admin/users/{staff.id}", json={"role": "owner"}, headers=http.admin)
    assert bad.status_code == 422 and bad.json()["code"] == "validation_error"


def test_an_admin_cannot_demote_or_deactivate_themselves(http):
    me = http.deps.store.users.by_email_for_login("admin@example.com")
    for body in ({"role": "staff"}, {"is_active": False}):
        r = http.patch(f"/api/v1/admin/users/{me.id}", json=body, headers=http.admin)
        assert r.status_code == 403 and r.json()["code"] == "forbidden"
    r = http.patch(f"/api/v1/admin/users/{me.id}", json={"display_name": "Root"}, headers=http.admin)
    assert r.status_code == 200 and r.json()["display_name"] == "Root"
    assert http.deps.store.users.by_id(me.id).role == "admin" and http.deps.store.users.by_id(me.id).is_active


# ---------------------------------------------------------------- cache

def test_cache_stats_and_clear(http):
    ask(http)
    ask(http, QUESTION.lower())
    r = http.get("/api/v1/admin/cache/stats", headers=http.admin)
    assert r.status_code == 200
    assert r.json() == {"entries": 1, "hits": 1, "misses": 1, "hit_rate": 0.5, "threshold": 0.9, "generation": None,
                        "backend": "memory-fake", "cleared_at": None}
    r = http.delete("/api/v1/admin/cache", headers=http.admin)
    assert r.status_code == 200 and r.json() == {"removed": 1}
    after = http.get("/api/v1/admin/cache/stats", headers=http.admin).json()
    assert after["entries"] == 0
    assert (after["hits"], after["misses"]) == (0, 0) and after["cleared_at"]   # counters restart at the clear
    assert ask(http)["cached"] is False
