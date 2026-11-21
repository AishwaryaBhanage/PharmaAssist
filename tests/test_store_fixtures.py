"""Shared fixtures for the store tests: the same test functions run against MemoryStore and, when a
PostgreSQL server is reachable, against PgStore on a database created for the session (dropped at
the end; every test starts from empty tables). Without a server the `pg` parameter is skipped.

The admin DSN is PHARMASSIST_TEST_DATABASE_URL, else DATABASE_URL, else the local socket
(postgresql:///postgres). Set none of them and only the memory variant runs.
"""

import os
import uuid

import numpy as np
import pytest

from pharmassist.store.memory import MemoryStore
from pharmassist.store.protocols import ChunkRecord, Document, DocumentVersion, ParentRecord

DIM = 3072
TABLES = ("users", "refresh_tokens", "documents", "document_versions", "parents", "chunks", "figures", "table_rows",
          "ingestion_jobs", "conversations", "messages", "feedback", "usage_days")


def admin_dsn() -> str:
    return os.environ.get("PHARMASSIST_TEST_DATABASE_URL") or os.environ.get("DATABASE_URL") or "postgresql:///postgres"


def _url(parts: dict, dbname: str) -> str:
    auth = parts.get("user", "")
    if parts.get("password"):
        auth += ":" + parts["password"]
    host = parts.get("host", "") or ""
    if parts.get("port"):
        host += ":" + str(parts["port"])
    return f"postgresql://{auth + '@' if auth else ''}{host}/{dbname}"


def pg_reachable() -> bool:
    try:
        import psycopg
        with psycopg.connect(admin_dsn(), connect_timeout=2):
            return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def pg_dsn():
    """A fresh database for the whole session, migrated once."""
    if not pg_reachable():
        pytest.skip("no PostgreSQL reachable (set DATABASE_URL or start a local server)")
    import psycopg
    from psycopg.conninfo import conninfo_to_dict
    name = f"pharmassist_test_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(admin_dsn(), autocommit=True) as c:
        c.execute(f'CREATE DATABASE "{name}"')
    dsn = _url(conninfo_to_dict(admin_dsn()), name)
    try:
        yield dsn
    finally:
        with psycopg.connect(admin_dsn(), autocommit=True) as c:
            c.execute(f'DROP DATABASE "{name}" WITH (FORCE)')


@pytest.fixture(scope="session")
def pg_store(pg_dsn):
    from pharmassist.store.pg import PgStore
    s = PgStore.connect(pg_dsn, min_size=1, max_size=10)
    s.migrate()
    yield s
    s.close()


@pytest.fixture(params=["memory", pytest.param("pg", marks=pytest.mark.integration)])
def store(request):
    if request.param == "memory":
        yield MemoryStore(dim=DIM)
        return
    s = request.getfixturevalue("pg_store")
    with s.pool.connection() as conn:
        conn.execute(f"TRUNCATE {', '.join(TABLES)} CASCADE")
        conn.execute("UPDATE index_state SET generation = 1")
    yield s


# ---------------------------------------------------------------- a small synthetic corpus

TEXTS = {
    "va_guide": ("VA", "advisory", [
        ("Metformin is first-line therapy for type 2 diabetes unless contraindicated.", ["Diabetes", "Pharmacotherapy"]),
        ("Buprenorphine for chronic pain: split dosing two to four times daily.", ["Pain", "Buprenorphine"]),
        ("Naloxone should be offered to patients on long-term opioid therapy.", ["Pain", "Naloxone"]),
        ("Semaglutide is a GLP-1 receptor agonist given once weekly.", ["Diabetes", "GLP-1"]),
    ]),
    "ny_pdl": ("NY Medicaid", "binding", [
        ("NCPDP reject code 22: dispense as written code not supported.", ["Billing", "Reject codes"]),
        ("Preferred GLP-1 agents require prior authorization when criteria are not met.", ["PDL", "GLP-1"]),
        ("Buprenorphine films are preferred; tablets are non-preferred.", ["PDL", "Opioid dependence"]),
    ]),
    "cms_memo": ("Medicare Part D", "binding", [
        ("Part D sponsors apply a 7-day supply limit for opioid naive patients.", ["Opioids", "Safety edits"]),
        ("The care coordination edit triggers at 90 MME per day.", ["Opioids", "Safety edits"]),
    ]),
}


def seeded_vectors(n: int, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal((n, DIM)).astype(np.float32)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def version_for(store, doc_id: str, program: str, authority: str, sha_byte: str, status: str = "queued") -> str:
    store.documents.upsert_document(Document(id=doc_id, title=doc_id.replace("_", " ").title(), program=program,
                                             doc_type="guide", authority=authority, doc_date="2024-01"))
    sha = sha_byte * 64
    store.documents.create_version(DocumentVersion(id=sha[:16], document_id=doc_id, sha256=sha,
                                                   s3_key=f"sources/{doc_id}/{sha[:16]}/{doc_id}.pdf",
                                                   file_name=f"{doc_id}.pdf", content_type="application/pdf", bytes=100,
                                                   pages=10, status=status))
    return sha[:16]


def build_corpus(store, *, activate: bool = True) -> dict:
    """Three documents, nine chunks (two per parent where possible), seeded vectors. Returns
    {"vectors": {chunk_id: vector}, "versions": {doc_id: version_id}, "chunks": [ChunkRecord]}."""
    all_chunks, parents, versions, vectors = [], [], {}, {}
    n = 0
    for d, (doc_id, (program, authority, items)) in enumerate(TEXTS.items()):
        vid = version_for(store, doc_id, program, authority, "abcdef"[d])
        versions[doc_id] = vid
        vecs = seeded_vectors(len(items), seed=d)
        for i, (text, path) in enumerate(items):
            pid = f"{doc_id}:s{i // 2}"
            cid = f"{doc_id}:s{i // 2}:c{i % 2}"
            all_chunks.append(ChunkRecord(version_id=vid, chunk_id=cid, document_id=doc_id, text=text,
                                          search_text=" > ".join(path) + "\n" + text, program=program, authority=authority,
                                          doc_date="2024-01", embedding=vecs[i], parent_id=pid, page_start=i + 1,
                                          page_end=i + 1, section_path=path, content_types=["text"],
                                          extraction="docling_text", metadata={"doc_type": "guide", "pages": [i + 1]}))
            vectors[cid] = vecs[i]
            n += 1
        for i in range(0, len(items), 2):
            group = items[i:i + 2]
            parents.append(ParentRecord(version_id=vid, parent_id=f"{doc_id}:s{i // 2}", document_id=doc_id,
                                        text="\n".join(t for t, _ in group), page_start=i + 1, page_end=i + len(group),
                                        section_path=group[0][1],
                                        metadata={"program": program, "authority": authority, "date": "2024-01",
                                                  "doc_type": "guide", "pages": list(range(i + 1, i + len(group) + 1)),
                                                  "content_types": ["text"], "extraction": ["docling_text"]}))
    store.content.put_parents(parents)
    store.content.put_chunks(all_chunks)
    if activate:
        for doc_id, vid in versions.items():
            store.documents.set_version_status(vid, "verifying", chunk_count=sum(c.document_id == doc_id for c in all_chunks))
            store.documents.activate(vid)
    return {"vectors": vectors, "versions": versions, "chunks": all_chunks, "parents": parents}
