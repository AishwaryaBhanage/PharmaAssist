"""Source pages and figure crops: authentication (Bearer or ?access_token=), validation against the
catalog and the figure records, presigned redirects when object storage is configured (a fake and
moto S3), and the local copies in development."""

import os

import pytest

from app.deps import S3Storage
from fakes_api import FakeStorage, build_app, client, make_user, login


def make_pdf(path, pages=3):
    import pymupdf
    doc = pymupdf.open()
    for i in range(pages):
        doc.new_page().insert_text((72, 72), f"Page {i + 1}")
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    doc.close()


@pytest.fixture
def local(tmp_path):
    app, deps = build_app(tmp_path)
    deps.store.add_document(pages=3)
    deps.store.add_figure("ny_medicaid_pdl", 2, name="p002_f1.png")
    make_pdf(tmp_path / "docs" / "ny_medicaid_pdl.pdf")
    (tmp_path / "figures" / "ny_medicaid_pdl").mkdir(parents=True)
    (tmp_path / "figures" / "ny_medicaid_pdl" / "p002_f1.png").write_bytes(b"\x89PNG fake")
    make_user(deps, "s@example.com")
    with client(app) as http:
        http.deps, http.hdrs = deps, login(http, "s@example.com")
        yield http


def test_sources_and_figures_require_a_signed_in_user(local):
    for path in ("/api/v1/sources/ny_medicaid_pdl/p1.pdf", "/api/v1/figures/ny_medicaid_pdl/p002_f1.png"):
        r = local.get(path)
        assert r.status_code == 401 and r.json()["code"] == "unauthenticated"
        assert local.get(path, params={"access_token": "garbage"}).status_code == 401
        token = local.hdrs["Authorization"].split()[1]
        assert local.get(path, params={"access_token": token}).status_code == 200      # a plain link works
        assert local.get(path, headers=local.hdrs).status_code == 200


def test_a_local_source_page_is_one_page_of_the_pdf(local):
    import pymupdf
    r = local.get("/api/v1/sources/ny_medicaid_pdl/p2.pdf", headers=local.hdrs)
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"] == 'inline; filename="ny_medicaid_pdl_p2.pdf"'
    with pymupdf.open(stream=r.content, filetype="pdf") as doc:
        assert doc.page_count == 1 and "Page 2" in doc[0].get_text()


@pytest.mark.parametrize("path", ["/api/v1/sources/ny_medicaid_pdl/p0.pdf", "/api/v1/sources/ny_medicaid_pdl/p4.pdf",
                                  "/api/v1/sources/ny_medicaid_pdl/page1.pdf", "/api/v1/sources/other_doc/p1.pdf",
                                  "/api/v1/sources/../etc/p1.pdf", "/api/v1/sources/NY_PDL/p1.pdf",
                                  "/api/v1/figures/ny_medicaid_pdl/p002_f2.png", "/api/v1/figures/ny_medicaid_pdl/p003_f1.png",
                                  "/api/v1/figures/ny_medicaid_pdl/notes.txt", "/api/v1/figures/other_doc/p002_f1.png"])
def test_unknown_pages_and_figures_are_404(local, path):
    r = local.get(path, headers=local.hdrs)
    assert r.status_code == 404 and r.json()["code"] == "not_found"


def test_a_spreadsheet_has_no_page_files(local):
    local.deps.store.add_document("va_formulary", file_name="va.xlsx", pages=None, sha="b" * 64)
    r = local.get("/api/v1/sources/va_formulary/p1.pdf", headers=local.hdrs)
    assert r.status_code == 404


def test_a_superseded_or_queued_version_is_not_served(local):
    local.deps.store.add_document("queued_doc", status="queued", sha="c" * 64)
    assert local.get("/api/v1/sources/queued_doc/p1.pdf", headers=local.hdrs).status_code == 404


def test_local_figure_crop(local):
    r = local.get("/api/v1/figures/ny_medicaid_pdl/p002_f1.png", headers=local.hdrs)
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content == b"\x89PNG fake"
    assert "private" in r.headers["cache-control"]


def test_presigned_redirects_when_storage_is_configured(tmp_path):
    storage = FakeStorage(tmp_path / "objects", presign_base="https://bucket.s3.amazonaws.com")
    app, deps = build_app(tmp_path, storage=storage)
    deps.store.add_document(pages=3)
    deps.store.add_figure("ny_medicaid_pdl", 2, name="p002_f1.png")
    make_user(deps, "s@example.com")
    with client(app) as http:
        auth = login(http, "s@example.com")
        r = http.get("/api/v1/sources/ny_medicaid_pdl/p2.pdf", headers=auth, follow_redirects=False)
        assert r.status_code == 302 and r.headers["cache-control"] == "no-store"
        assert r.headers["location"] == ("https://bucket.s3.amazonaws.com/sources/ny_medicaid_pdl/aaaaaaaaaaaaaaaa/"
                                         "ny_medicaid_pdl.pdf?X-Amz-Signature=fake#page=2")
        r = http.get("/api/v1/figures/ny_medicaid_pdl/p002_f1.png", headers=auth, follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"] == "https://bucket.s3.amazonaws.com/figures/ny_medicaid_pdl/p002_f1.png?X-Amz-Signature=fake"
        assert http.get("/api/v1/sources/ny_medicaid_pdl/p9.pdf", headers=auth).status_code == 404
        assert storage.presigned == ["sources/ny_medicaid_pdl/aaaaaaaaaaaaaaaa/ny_medicaid_pdl.pdf",
                                     "figures/ny_medicaid_pdl/p002_f1.png"]


@pytest.fixture
def s3():
    from moto import mock_aws
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        import boto3
        c = boto3.client("s3", region_name="us-east-1")
        c.create_bucket(Bucket="pharmassist-test")
        yield c


def test_s3_storage_against_moto(tmp_path, s3):
    storage = S3Storage("pharmassist-test", presign_seconds=300)
    assert storage.ping() is True
    storage.put_bytes("sources/d/abc/d.pdf", b"%PDF-1.4 x", content_type="application/pdf")
    assert storage.get_bytes("sources/d/abc/d.pdf") == b"%PDF-1.4 x"
    url = storage.presign("sources/d/abc/d.pdf", content_type="application/pdf", fragment="page=3")
    assert url.startswith("https://") and "pharmassist-test" in url and "X-Amz-Signature=" in url
    assert url.endswith("#page=3") and "response-content-type=application%2Fpdf" in url and "X-Amz-Expires=300" in url
    assert S3Storage("no-such-bucket-pa").ping() is False
    app, deps = build_app(tmp_path, storage=storage)
    deps.store.add_document(pages=3)
    make_user(deps, "s@example.com")
    with client(app) as http:
        r = http.get("/api/v1/sources/ny_medicaid_pdl/p3.pdf", headers=login(http, "s@example.com"), follow_redirects=False)
        assert r.status_code == 302 and "sources/ny_medicaid_pdl/aaaaaaaaaaaaaaaa/ny_medicaid_pdl.pdf" in r.headers["location"]
        assert r.headers["location"].endswith("#page=3")
        assert http.get("/health/ready").json()["checks"]["storage"] is True
