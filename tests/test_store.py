"""Every repository, on MemoryStore and (integration) PgStore, through one set of test functions."""

import uuid
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pytest

from pharmassist.store.protocols import (NO_ANSWER_TEXT, ChunkRecord, Conflict, Document, DocumentVersion,
                                         FigureRecord, Message, NotFound, ParentRecord, TableRowRecord)
from test_store_fixtures import DIM, build_corpus, pg_dsn, pg_store, seeded_vectors, store, version_for  # noqa: F401

NOW = lambda: datetime.now(timezone.utc)  # noqa: E731


def msg(conv, user, request_id, **kw):
    base = dict(id="", conversation_id=conv.id, user_id=user.id, request_id=request_id, question="What is the dose?",
                status="answered", answer="Ten mg", created_at=None)
    return Message(**{**base, **kw})


# ---------------------------------------------------------------- users

def test_users_create_and_login_lookup(store):
    u = store.users.create("Alice@Example.com", "argon2$hash", "admin", "Alice")
    assert u.role == "admin" and u.is_active and u.password_hash is None and u.created_at is not None
    assert store.users.by_id(u.id).password_hash is None
    login = store.users.by_email_for_login("alice@example.COM")
    assert login.id == u.id and login.password_hash == "argon2$hash"
    assert store.users.by_email_for_login("nobody@example.com") is None
    store.users.touch_login(u.id)
    assert store.users.by_id(u.id).last_login_at is not None


def test_duplicate_email_is_a_conflict_case_insensitively(store):
    store.users.create("a@x.com", "h", "staff")
    with pytest.raises(Conflict):
        store.users.create("A@X.COM", "h2", "staff")
    with pytest.raises(ValueError):
        store.users.create("b@x.com", "h", "superuser")


def test_users_list_update_count(store):
    a = store.users.create("a@x.com", "h", "staff", "Ann")
    store.users.create("b@x.com", "h", "admin", "Bob")
    page = store.users.list(q="ann")
    assert page.total == 1 and page.items[0].id == a.id and page.items[0].password_hash is None
    assert store.users.list(limit=1).total == 2 and len(store.users.list(limit=1).items) == 1
    u = store.users.update(a.id, role="admin", is_active=False, display_name="Anne")
    assert (u.role, u.is_active, u.display_name) == ("admin", False, "Anne")
    assert store.users.count() == 2 and store.users.count("admin") == 2 and store.users.count("staff") == 0
    with pytest.raises(NotFound):
        store.users.update(str(uuid.uuid4()), role="staff")


# ---------------------------------------------------------------- tokens

def test_token_issue_rotate_revoke(store):
    u = store.users.create("a@x.com", "h", "staff")
    exp = NOW() + timedelta(days=14)
    t = store.tokens.issue(u.id, "hash1", exp)
    assert store.tokens.by_hash("hash1").id == t.id and store.tokens.by_hash("nope") is None
    new = store.tokens.rotate(t.id, "hash2", exp)
    old = store.tokens.by_hash("hash1")
    assert old.revoked_at is not None and old.replaced_by == new.id and new.revoked_at is None
    assert new.user_id == u.id and store.tokens.by_hash("hash2").id == new.id
    store.tokens.issue(u.id, "hash3", exp)
    assert store.tokens.revoke_all(u.id) == 2          # hash2 and hash3; hash1 was already revoked
    assert store.tokens.revoke_all(u.id) == 0
    with pytest.raises(NotFound):
        store.tokens.rotate(str(uuid.uuid4()), "x", exp)


def test_token_purge_expired(store):
    u = store.users.create("a@x.com", "h", "staff")
    store.tokens.issue(u.id, "old", NOW() - timedelta(seconds=5))
    keep = store.tokens.issue(u.id, "new", NOW() + timedelta(days=1))
    store.tokens.revoke(keep.id)
    assert store.tokens.purge_expired() == 1
    assert store.tokens.by_hash("old") is None and store.tokens.by_hash("new").revoked_at is not None


# ---------------------------------------------------------------- documents and versions

def test_upsert_document_keeps_the_active_pointer(store):
    vid = version_for(store, "doc_a", "VA", "advisory", "a", status="verifying")
    store.documents.activate(vid)
    d = store.documents.upsert_document(Document(id="doc_a", title="New title", program="VA"))
    assert d.title == "New title" and d.active_version_id == vid
    assert store.documents.get_document("missing") is None
    assert [d.id for d in store.documents.list_documents()] == ["doc_a"]


def test_create_version_conflicts_on_the_same_file(store):
    vid = version_for(store, "doc_a", "VA", "advisory", "a")
    with pytest.raises(Conflict):
        version_for(store, "doc_a", "VA", "advisory", "a")
    assert store.documents.version_by_sha("doc_a", "a" * 64).id == vid
    assert store.documents.version_by_sha("doc_a", "b" * 64) is None
    with pytest.raises(NotFound):
        store.documents.create_version(DocumentVersion(id="x" * 16, document_id="ghost", sha256="c" * 64, s3_key="k",
                                                       file_name="f", content_type="application/pdf", bytes=1, status="queued"))


def test_version_status_and_fields(store):
    vid = version_for(store, "doc_a", "VA", "advisory", "a")
    store.documents.set_version_status(vid, "embedding", pages=12, embedder_model="text-embedding-3-large", embedding_dim=3072)
    v = store.documents.get_version(vid)
    assert (v.status, v.pages, v.embedder_model, v.embedding_dim) == ("embedding", 12, "text-embedding-3-large", 3072)
    store.documents.set_version_status(vid, "failed", error="boom")
    assert store.documents.get_version(vid).error == "boom"
    with pytest.raises(ValueError):
        store.documents.set_version_status(vid, "verifying", colour="blue")
    with pytest.raises(ValueError):
        store.documents.set_version_status(vid, "half-done")
    with pytest.raises(NotFound):
        store.documents.set_version_status("nope", "queued")
    assert [x.id for x in store.documents.list_versions("doc_a")] == [vid]


def test_activate_requires_verifying_and_bumps_generation(store):
    vid = version_for(store, "doc_a", "VA", "advisory", "a")
    with pytest.raises(Conflict):
        store.documents.activate(vid)
    with pytest.raises(NotFound):
        store.documents.activate("missing")
    g0 = store.documents.generation()
    store.documents.set_version_status(vid, "verifying")
    assert store.documents.activate(vid) == g0 + 1 == store.documents.generation()
    v = store.documents.get_version(vid)
    assert v.status == "active" and v.activated_at is not None
    assert store.documents.active_versions() == {"doc_a": vid}
    assert store.documents.get_document("doc_a").active_version_id == vid


def test_activating_a_new_version_supersedes_the_old_one(store):
    v1 = version_for(store, "doc_a", "VA", "advisory", "a", status="verifying")
    store.documents.activate(v1)
    sha = "b" * 64
    store.documents.create_version(DocumentVersion(id=sha[:16], document_id="doc_a", sha256=sha, s3_key="k", file_name="f",
                                                   content_type="application/pdf", bytes=1, status="verifying"))
    g = store.documents.activate(sha[:16])
    assert store.documents.get_version(v1).status == "superseded"
    assert store.documents.active_versions() == {"doc_a": sha[:16]} and g == 3
    # a stale version can't take over: it is no longer 'verifying'
    with pytest.raises(Conflict):
        store.documents.activate(v1)


def test_deactivate_removes_the_active_versions_content_and_keeps_the_version(store):
    c = build_corpus(store)
    vid = c["versions"]["ny_pdl"]
    store.content.put_figures([FigureRecord(version_id=vid, figure_id="ny_pdl:p001_f1", document_id="ny_pdl", page=1,
                                            kind="table", status="ocr_checked", record={})])
    store.content.put_table_rows([TableRowRecord(version_id=vid, table_name="ny_pdl", row_no=i, row={"drug": f"d{i}"})
                                  for i in range(3)])
    g0 = store.documents.generation()
    out = store.documents.deactivate("ny_pdl")
    assert out == {"document_id": "ny_pdl", "version_id": vid,
                   "removed": {"chunks": 3, "parents": 2, "figures": 1, "table_rows": 3}, "generation": g0 + 1}
    assert store.documents.generation() == g0 + 1
    assert store.content.counts(vid) == {"chunks": 0, "parents": 0, "figures": 0, "table_rows": 0}
    v = store.documents.get_version(vid)
    assert v.status == "superseded" and v.s3_key and v.sha256 == "b" * 64     # the file reference survives
    d = store.documents.get_document("ny_pdl")
    assert d.active_version_id is None and d.updated_at >= d.created_at
    assert set(store.documents.active_versions()) == {"va_guide", "cms_memo"}
    assert "ny_pdl" not in store.documents.catalog()
    assert store.content.table_rows("ny_pdl") == [] and store.content.figures_for_page("ny_pdl", 1) == []
    hits = store.search.keyword("buprenorphine", 10)
    assert hits and all(h.chunk.document_id != "ny_pdl" for h in hits)
    assert store.search.dense(c["vectors"]["ny_pdl:s0:c0"], 10)[0].chunk.document_id != "ny_pdl"
    with pytest.raises(NotFound):
        store.documents.deactivate("ny_pdl")          # nothing active any more
    with pytest.raises(NotFound):
        store.documents.deactivate("missing")
    assert store.documents.generation() == g0 + 1     # the failed calls did not bump it
    # the superseded version can be queued again for a rebuild (what reindex does through submit_upload)
    store.documents.set_version_status(vid, "queued")
    assert store.documents.get_version(vid).status == "queued"


def test_catalog_has_v1s_shape(store):
    vid = version_for(store, "doc_a", "VA", "advisory", "a", status="verifying")
    version_for(store, "doc_b", "NY Medicaid", "binding", "b")      # never activated: absent from the catalog
    store.documents.activate(vid)
    cat = store.documents.catalog()
    assert list(cat) == ["doc_a"]
    assert cat["doc_a"] == {"id": "doc_a", "title": "Doc A", "program": "VA", "doc_type": "guide", "authority": "advisory",
                            "publisher": "", "date": "2024-01", "source_url": None, "file": "doc_a.pdf", "pages": 10,
                            "version": vid}
    assert [d.id for d in store.documents.list_documents(include_inactive=False)] == ["doc_a"]


def test_jobs(store):
    u = store.users.create("a@x.com", "h", "admin")
    vid = version_for(store, "doc_a", "VA", "advisory", "a")
    j = store.documents.create_job(vid, requested_by=u.id)
    assert j.status == "queued" and j.attempt == 0 and j.requested_by == u.id and j.queued_at is not None
    j = store.documents.update_job(j.id, status="running", attempt=1, stage="parsing", worker_id="w1", started=True, heartbeat=True)
    assert (j.status, j.attempt, j.stage, j.worker_id) == ("running", 1, "parsing", "w1")
    assert j.started_at is not None and j.heartbeat_at is not None and j.finished_at is None
    j = store.documents.update_job(j.id, status="failed", error="timeout", finished=True)
    assert j.finished_at is not None and store.documents.get_job(j.id).error == "timeout"
    assert store.documents.list_jobs(version_id=vid).total == 1 and store.documents.list_jobs(status="queued").total == 0
    with pytest.raises(NotFound):
        store.documents.update_job(str(uuid.uuid4()), status="running")
    with pytest.raises(ValueError):
        store.documents.update_job(j.id, status="exploded")
    with pytest.raises(NotFound):
        store.documents.create_job("missing")


# ---------------------------------------------------------------- content

def test_puts_are_idempotent_upserts(store):
    c = build_corpus(store, activate=False)
    vid = c["versions"]["va_guide"]
    before = store.content.counts(vid)
    store.content.put_parents([p for p in c["parents"] if p.version_id == vid])
    store.content.put_chunks([x for x in c["chunks"] if x.version_id == vid])
    store.content.put_figures([FigureRecord(version_id=vid, figure_id="va_guide:p3:f0", document_id="va_guide", page=3,
                                            kind="flowchart", status="reviewed", record={"kind": "flowchart"})] * 2)
    store.content.put_table_rows([TableRowRecord(version_id=vid, table_name="va_formulary", row_no=1, row={"drug": "x"})] * 2)
    after = store.content.counts(vid)
    assert before == {"chunks": 4, "parents": 2, "figures": 0, "table_rows": 0}
    assert after == {"chunks": 4, "parents": 2, "figures": 1, "table_rows": 1}
    store.content.delete_version_content(vid)
    assert store.content.counts(vid) == {"chunks": 0, "parents": 0, "figures": 0, "table_rows": 0}
    assert store.content.counts(c["versions"]["ny_pdl"])["chunks"] == 3


def test_put_chunks_checks_the_dimension(store):
    vid = version_for(store, "doc_a", "VA", "advisory", "a")
    bad = ChunkRecord(version_id=vid, chunk_id="c", document_id="doc_a", text="t", search_text="t", program="VA",
                      authority="advisory", doc_date="2024", embedding=[0.1] * 1536)
    with pytest.raises(ValueError, match="1536"):
        store.content.put_chunks([bad])
    with pytest.raises(ValueError):
        store.content.put_chunks([ChunkRecord(**{**bad.__dict__, "embedding": None})])
    with pytest.raises(ValueError):
        store.content.put_table_rows([TableRowRecord(version_id=vid, table_name="other", row_no=1, row={})])
    assert store.content.counts(vid)["chunks"] == 0


def test_readers_see_active_versions_only(store):
    c = build_corpus(store, activate=False)
    vid = c["versions"]["va_guide"]
    store.content.put_figures([FigureRecord(version_id=vid, figure_id="va_guide:p1:f0", document_id="va_guide", page=1,
                                            kind="chart", status="ocr_checked", record={})])
    store.content.put_table_rows([TableRowRecord(version_id=vid, table_name="va_formulary", row_no=20,
                                                 row={"drug": "METFORMIN HCL", "cells": []})])
    q = c["vectors"]["va_guide:s0:c0"]
    assert store.search.dense(q, 5) == [] and store.search.keyword("metformin", 5) == []
    assert store.content.figures_for_page("va_guide", 1) == [] and store.content.table_rows("va_formulary") == []
    assert store.content.figure("va_guide", "va_guide:p1:f0") is None
    # staged content is still reachable by explicit id (the worker verifies it before activating)
    assert set(store.content.chunks_by_ids([(vid, "va_guide:s0:c0")])) == {(vid, "va_guide:s0:c0")}
    store.documents.set_version_status(vid, "verifying")
    store.documents.activate(vid)
    assert store.search.dense(q, 5)[0].chunk.chunk_id == "va_guide:s0:c0"
    assert [h.chunk.document_id for h in store.search.keyword("metformin", 5)] == ["va_guide"]
    assert store.content.figures_for_page("va_guide", 1)[0].figure_id == "va_guide:p1:f0"
    assert store.content.figure("va_guide", "va_guide:p1:f0").status == "ocr_checked"
    assert store.content.table_rows("va_formulary", drug="metf")[0]["drug"] == "METFORMIN HCL"
    assert store.content.table_rows("va_formulary", drug="zzz") == [] and store.content.table_rows("ny_pdl") == []


def test_a_new_version_replaces_the_visible_content(store):
    c = build_corpus(store)
    old = c["versions"]["va_guide"]
    sha = "9" * 64
    store.documents.create_version(DocumentVersion(id=sha[:16], document_id="va_guide", sha256=sha, s3_key="k", file_name="f",
                                                   content_type="application/pdf", bytes=1, status="chunking"))
    store.content.put_chunks([ChunkRecord(version_id=sha[:16], chunk_id="va_guide:s0:c0", document_id="va_guide",
                                          text="Zebrafish models of diabetes.", search_text="Zebrafish models of diabetes.",
                                          program="VA", authority="advisory", doc_date="2025", embedding=seeded_vectors(1, 9)[0])])
    assert store.search.keyword("zebrafish", 5) == []
    store.documents.set_version_status(sha[:16], "verifying")
    store.documents.activate(sha[:16])
    assert [h.chunk.version_id for h in store.search.keyword("zebrafish", 5)] == [sha[:16]]
    assert store.search.keyword("naloxone", 5) == []                 # the old version's text is gone
    assert store.content.counts(old)["chunks"] == 4                   # but its rows still exist until deleted


def test_chunk_and_parent_lookups_and_iteration(store):
    c = build_corpus(store)
    vid = c["versions"]["va_guide"]
    got = store.content.chunks_by_ids([(vid, "va_guide:s0:c0"), (vid, "va_guide:s1:c1"), (vid, "nope")])
    assert set(got) == {(vid, "va_guide:s0:c0"), (vid, "va_guide:s1:c1")}
    ch = got[(vid, "va_guide:s0:c0")]
    assert ch.embedding is None and ch.section_path == ["Diabetes", "Pharmacotherapy"] and ch.metadata["pages"] == [1]
    ps = store.content.parents_by_ids([(vid, "va_guide:s0"), (vid, "missing")])
    assert list(ps) == [(vid, "va_guide:s0")] and ps[(vid, "va_guide:s0")].metadata["program"] == "VA"
    plain = list(store.content.iter_chunks(vid))
    assert [x.chunk_id for x in plain] == sorted(x.chunk_id for x in plain) and all(x.embedding is None for x in plain)
    withv = list(store.content.iter_chunks(vid, with_embeddings=True))
    v = np.asarray(withv[0].embedding, dtype=np.float32)
    assert v.shape == (DIM,) and np.allclose(v, c["vectors"][withv[0].chunk_id], atol=2e-3)  # halfvec rounding


# ---------------------------------------------------------------- search halves

def test_dense_ranks_the_nearest_chunk_first_without_embeddings(store):
    c = build_corpus(store)
    target = c["vectors"]["ny_pdl:s0:c0"]
    q = target + 0.05 * seeded_vectors(1, 123)[0]
    hits = store.search.dense(q, 4)
    assert [h.rank for h in hits] == [1, 2, 3, 4]
    assert hits[0].chunk.chunk_id == "ny_pdl:s0:c0" and hits[0].score > 0.9 > hits[1].score
    assert all(h.chunk.embedding is None for h in hits)
    assert len(store.search.dense(q, 50)) == 9 and store.search.dense(q, 0) == []
    with pytest.raises(ValueError):
        store.search.dense([0.0] * 10, 3)


def test_dense_filters_before_ranking(store):
    c = build_corpus(store)
    q = c["vectors"]["ny_pdl:s0:c0"]
    va = store.search.dense(q, 3, program="VA")
    assert len(va) == 3 and {h.chunk.program for h in va} == {"VA"} and va[0].rank == 1
    assert store.search.dense(q, 3, program="Atlantis") == []
    docs = store.search.dense(q, 5, document_ids=["cms_memo"])
    assert len(docs) == 2 and {h.chunk.document_id for h in docs} == {"cms_memo"}
    assert store.search.dense(q, 5, document_ids=[]) == []


def test_keyword_matches_terms_and_filters(store):
    build_corpus(store)
    hits = store.search.keyword("buprenorphine", 10)
    assert {h.chunk.chunk_id for h in hits} == {"va_guide:s0:c1", "ny_pdl:s1:c0"} and [h.rank for h in hits] == [1, 2]
    assert hits[0].score > 0 and hits[0].chunk.embedding is None
    assert [h.chunk.program for h in store.search.keyword("buprenorphine", 10, program="NY Medicaid")] == ["NY Medicaid"]
    assert store.search.keyword("buprenorphine", 10, document_ids=["cms_memo"]) == []
    assert [h.chunk.chunk_id for h in store.search.keyword("reject code 22", 5)] == ["ny_pdl:s0:c0"]
    assert store.search.keyword("", 5) == [] and store.search.keyword("the", 5) == []
    assert store.search.keyword("xylophone", 5) == []


def test_keyword_ranks_all_term_matches_first_then_fills_with_any_term(store):
    build_corpus(store)
    # no chunk has every word; v1's BM25 still returned candidates, so the any-term matches fill the list
    hits = store.search.keyword("naloxone zebra buprenorphine films", 10)
    ids = [h.chunk.chunk_id for h in hits]
    assert ids[0] == "ny_pdl:s1:c0"                                 # two of the terms, incl. the rare 'films'
    assert set(ids) == {"ny_pdl:s1:c0", "va_guide:s1:c0", "va_guide:s0:c1"} and [h.rank for h in hits] == [1, 2, 3]
    # with a complete match present it comes first; partial matches ('buprenorphine', the 'Pain' heading) follow
    hits = store.search.keyword("buprenorphine chronic pain", 10)
    assert hits[0].chunk.chunk_id == "va_guide:s0:c1" and {h.chunk.chunk_id for h in hits[1:]} == {"ny_pdl:s1:c0", "va_guide:s1:c0"}
    assert len(store.search.keyword("buprenorphine chronic pain", 1)) == 1


# ---------------------------------------------------------------- conversations, feedback, stats

def test_conversations_and_messages(store):
    u = store.users.create("a@x.com", "h", "staff")
    other = store.users.create("b@x.com", "h", "staff")
    with pytest.raises(NotFound):
        store.conversations.create(str(uuid.uuid4()), "x")
    conv = store.conversations.create(u.id, "What is the dose?")
    assert store.conversations.get(conv.id).message_count == 0
    assert store.conversations.get(conv.id, user_id=other.id) is None
    m1 = store.conversations.add_message(msg(conv, u, "r1", latency_s=1.0, cost_usd=0.02, citations=[{"id": "doc:p1"}]))
    m2 = store.conversations.add_message(msg(conv, u, "r2", status="no_answer", answer=NO_ANSWER_TEXT, cached=True))
    assert uuid.UUID(m1.id) and m1.created_at is not None and m1.citations == [{"id": "doc:p1"}] and m1.feedback is None
    with pytest.raises(Conflict):
        store.conversations.add_message(msg(conv, u, "r1"))
    with pytest.raises(NotFound):
        store.conversations.add_message(msg(conv, u, "r3", conversation_id=str(uuid.uuid4())))
    assert [m.id for m in store.conversations.messages(conv.id)] == [m1.id, m2.id]
    assert store.conversations.message(m1.id).request_id == "r1" and store.conversations.message(m1.id, user_id=other.id) is None
    assert store.conversations.message_by_request("r2").cached is True and store.conversations.message_by_request("zz") is None
    got = store.conversations.get(conv.id, user_id=u.id)
    assert got.message_count == 2 and got.updated_at >= conv.updated_at
    page = store.conversations.list_for_user(u.id)
    assert page.total == 1 and page.items[0].message_count == 2 and store.conversations.list_for_user(other.id).total == 0
    assert store.conversations.delete(conv.id, other.id) is False
    assert store.conversations.delete(conv.id, u.id) is True and store.conversations.get(conv.id) is None
    assert store.conversations.message(m1.id) is None


def test_feedback_replaces_and_is_attached_to_messages(store):
    u = store.users.create("a@x.com", "h", "staff")
    conv = store.conversations.create(u.id, "q")
    m = store.conversations.add_message(msg(conv, u, "r1"))
    fb = store.feedback.save(m.id, u.id, "helpful", None, "great")
    fb2 = store.feedback.save(m.id, u.id, "unhelpful", "wrong", "no")
    assert fb2.id == fb.id and fb2.rating == "unhelpful" and fb2.reason == "wrong" and fb2.updated_at >= fb.updated_at
    assert store.feedback.get(m.id).comment == "no"
    assert store.conversations.messages(conv.id)[0].feedback.rating == "unhelpful"
    assert store.conversations.message(m.id).feedback.id == fb.id
    with pytest.raises(NotFound):
        store.feedback.save(str(uuid.uuid4()), u.id, "helpful", None, None)
    with pytest.raises(ValueError):
        store.feedback.save(m.id, u.id, "meh", None, None)
    assert store.feedback.get(str(uuid.uuid4())) is None


def test_search_messages_filters(store):
    a = store.users.create("a@x.com", "h", "staff")
    b = store.users.create("b@x.com", "h", "staff")
    ca, cb = store.conversations.create(a.id, "q"), store.conversations.create(b.id, "q")
    old = datetime(2020, 1, 1, tzinfo=timezone.utc)
    m1 = store.conversations.add_message(msg(ca, a, "r1", question="metformin dose", answer="500 mg"))
    m2 = store.conversations.add_message(msg(cb, b, "r2", status="no_answer", answer=NO_ANSWER_TEXT, cached=True))
    m3 = store.conversations.add_message(msg(ca, a, "r3", question="old one", created_at=old))
    store.feedback.save(m1.id, a.id, "helpful", None, None)
    store.feedback.save(m2.id, b.id, "unhelpful", "wrong", None)
    s = store.conversations.search_messages
    assert [m.id for m in s().items] == [m2.id, m1.id, m3.id]           # newest first
    assert [m.id for m in s(rating="helpful").items] == [m1.id] and s(rating="unhelpful").items[0].feedback.reason == "wrong"
    assert s(status="no_answer").total == 1 and s(user_id=b.id).total == 1 and s(cached=True).total == 1 and s(cached=False).total == 2
    assert [m.id for m in s(q="METFORMIN").items] == [m1.id] and [m.id for m in s(q="500").items] == [m1.id]
    assert [m.id for m in s(until=old + timedelta(days=1)).items] == [m3.id]
    assert s(since=old + timedelta(days=1)).total == 2
    page = s(offset=1, limit=1)
    assert page.total == 3 and [m.id for m in page.items] == [m1.id] and (page.offset, page.limit) == (1, 1)


def test_stats_overview_and_usage(store):
    a = store.users.create("a@x.com", "h", "staff")
    b = store.users.create("b@x.com", "h", "staff")
    ca, cb = store.conversations.create(a.id, "q"), store.conversations.create(b.id, "q")
    since, until = NOW() - timedelta(days=1), NOW() + timedelta(days=1)
    assert store.stats.overview(since, until) == {"questions": 0, "answered": 0, "no_answer": 0, "cached": 0, "fallback": 0,
                                                  "helpful": 0, "unhelpful": 0, "latency_p50_s": None, "latency_p95_s": None,
                                                  "spend_usd": 0.0, "active_users": 0, "per_day": []}
    m1 = store.conversations.add_message(msg(ca, a, "r1", latency_s=1.0, cost_usd=0.02, fallback_used=True))
    m2 = store.conversations.add_message(msg(ca, a, "r2", latency_s=2.0, cost_usd=0.03))
    m3 = store.conversations.add_message(msg(cb, b, "r3", latency_s=4.0, status="no_answer", answer=NO_ANSWER_TEXT, cached=True))
    store.conversations.add_message(msg(cb, b, "r4", created_at=datetime(2020, 1, 1, tzinfo=timezone.utc)))  # outside the window
    store.feedback.save(m1.id, a.id, "helpful", None, None)
    store.feedback.save(m2.id, a.id, "helpful", None, None)
    store.feedback.save(m3.id, b.id, "unhelpful", "wrong", None)
    o = store.stats.overview(since, until)
    assert {k: o[k] for k in ("questions", "answered", "no_answer", "cached", "fallback", "helpful", "unhelpful", "active_users")} == \
        {"questions": 3, "answered": 2, "no_answer": 1, "cached": 1, "fallback": 1, "helpful": 2, "unhelpful": 1, "active_users": 2}
    assert o["latency_p50_s"] == pytest.approx(2.0) and o["latency_p95_s"] == pytest.approx(3.8)   # percentile_cont
    assert o["spend_usd"] == pytest.approx(0.05)
    assert len(o["per_day"]) == 1 and o["per_day"][0]["day"] == NOW().date().isoformat()
    assert {k: o["per_day"][0][k] for k in ("questions", "helpful", "unhelpful", "no_answer", "cached")} == \
        {"questions": 3, "helpful": 2, "unhelpful": 1, "no_answer": 1, "cached": 1}
    day = date(2026, 10, 18)
    assert store.stats.usage_day(day) == {"day": "2026-10-18", "questions": 0, "spend_usd": 0.0}
    store.stats.add_usage(day, 1, 0.5)
    store.stats.add_usage(day, 2, 0.25)
    assert store.stats.usage_day(day) == {"day": "2026-10-18", "questions": 3, "spend_usd": 0.75}


def test_ping_and_migrate_are_safe(store):
    assert store.ping() is True
    store.migrate()          # idempotent: already at head
    assert store.ping() is True
