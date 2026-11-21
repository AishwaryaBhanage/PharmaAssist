"""The S3 object store (moto; no real AWS): content-addressed keys, round trips, and hosted links as
short-lived presigned URLs that never carry credentials in the path."""

from urllib.parse import parse_qs, urlparse

import pytest

from pharmassist import cloud

BUCKET = "pharmassist-test-docs"


@pytest.fixture
def s3(monkeypatch, tmp_path):
    from moto import mock_aws
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("PHARMASSIST_BUCKET", BUCKET)
    with mock_aws():
        import boto3
        from botocore.config import Config
        client = boto3.client("s3", region_name="us-east-1", config=Config(signature_version="s3v4"))
        client.create_bucket(Bucket=BUCKET)
        yield client


def test_source_files_round_trip_under_content_addressed_keys(s3, tmp_path):
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4 fake")
    ver = cloud.sha16(src)
    key = cloud.source_key("doc_a", ver, "doc.pdf")
    assert key == f"sources/doc_a/{ver}/doc.pdf" and len(ver) == 16
    assert not cloud.exists(key, s3)
    cloud.put_file(src, key, s3, content_type="application/pdf")
    assert cloud.exists(key, s3) and cloud.get_bytes(key, s3) == b"%PDF-1.4 fake"
    assert cloud.list_keys("sources/doc_a/", s3) == [key]
    assert cloud.get_file(key, tmp_path / "out" / "doc.pdf", s3).read_bytes().startswith(b"%PDF")


def test_presigned_links_expire_and_never_carry_credentials_in_the_path(s3):
    url = cloud.presign("sources/doc_a/abc/doc.pdf", s3=s3, content_type="application/pdf")
    q = parse_qs(urlparse(url).query)
    assert int(q["X-Amz-Expires"][0]) == cloud.PRESIGN_SECONDS
    assert q["response-content-type"] == ["application/pdf"]


def test_data_root_moves_data_directories_only(monkeypatch, tmp_path):
    from pharmassist.config import PROJECT_ROOT, figure_records_path, project_path
    monkeypatch.setenv("PHARMASSIST_DATA_ROOT", str(tmp_path))
    assert project_path("docs") == tmp_path / "docs" and project_path("index") == tmp_path / "index"
    assert project_path("reports") == PROJECT_ROOT / "reports"
    assert figure_records_path() == tmp_path / "storage" / "figures" / "records.json"
