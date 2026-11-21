"""Queue and storage adapters: SQS (moto), the SQLite and memory queues, S3 storage (moto), the local
folder, and the config-driven factories including the MinIO/ElasticMQ endpoint variables."""

import copy
import os

import pytest

from pharmassist import cloud
from pharmassist.config import load_config
from pharmassist.ingest.queue import (LocalQueue, MemoryQueue, QueueConfigError, SQSQueue, queue_from_config)
from pharmassist.ingest.storage import LocalStorage, S3Storage, StorageConfigError, storage_from_config


@pytest.fixture
def aws(monkeypatch):
    from moto import mock_aws
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.delenv("S3_ENDPOINT_URL", raising=False)
    monkeypatch.delenv("SQS_ENDPOINT_URL", raising=False)
    with mock_aws():
        import boto3
        yield boto3


def _exercise(q):
    q.send({"job_id": "j1", "version_id": "v1", "document_id": "d1"})
    q.send({"job_id": "j2", "version_id": "v2", "document_id": "d1"})
    [m] = q.receive(wait_s=0)
    assert m.body["job_id"] == "j1" and m.receive_count == 1
    q.extend_visibility(m, 600)          # the heartbeat
    [m2] = q.receive(wait_s=0)
    assert m2.body["job_id"] == "j2"     # j1 is invisible
    q.retry_later(m2, 0)
    q.ack(m)
    [m2] = q.receive(wait_s=0)
    assert m2.body["job_id"] == "j2" and m2.receive_count == 2
    q.dead_letter(m2, "permanent: parse failed")
    assert q.receive(wait_s=0) == []


def test_sqs_queue_round_trip_and_dead_letter(aws):
    sqs = aws.client("sqs", region_name="us-east-1")
    dlq = sqs.create_queue(QueueName="dlq")["QueueUrl"]
    url = sqs.create_queue(QueueName="q")["QueueUrl"]
    _exercise(SQSQueue(url, dlq, client=sqs))
    dead = sqs.receive_message(QueueUrl=dlq, MaxNumberOfMessages=1)["Messages"][0]
    assert '"dead_letter_reason": "permanent: parse failed"' in dead["Body"] and '"job_id": "j2"' in dead["Body"]


def test_local_and_memory_queues_share_the_semantics(tmp_path):
    _exercise(MemoryQueue(visibility_timeout_s=60))
    lq = LocalQueue(tmp_path / "q.sqlite", visibility_timeout_s=60, max_receives=5)
    _exercise(lq)
    assert lq.dead_letters()[0]["body"]["job_id"] == "j2" and lq.pending() == 0


def test_the_local_queue_redrives_after_max_receives(tmp_path):
    lq = LocalQueue(tmp_path / "q.sqlite", visibility_timeout_s=0, max_receives=2)
    lq.send({"job_id": "j"})
    assert lq.receive(wait_s=0) and lq.receive(wait_s=0)
    assert lq.receive(wait_s=0) == [] and lq.dead_letters()[0]["reason"] == "max receives exceeded"


def test_queue_from_config_honours_backend_and_endpoint(aws, monkeypatch, tmp_path):
    cfg = copy.deepcopy(load_config())
    cfg["queue"].update(backend="sqs")
    monkeypatch.delenv("INGEST_QUEUE_URL", raising=False)
    with pytest.raises(QueueConfigError, match="INGEST_QUEUE_URL"):
        queue_from_config(cfg)
    monkeypatch.setenv("INGEST_QUEUE_URL", "http://localhost:9324/000000000000/ingest")
    monkeypatch.setenv("INGEST_DLQ_URL", "http://localhost:9324/000000000000/ingest-dlq")
    monkeypatch.setenv("SQS_ENDPOINT_URL", "http://localhost:9324")
    q = queue_from_config(cfg)
    assert isinstance(q, SQSQueue) and q.sqs.meta.endpoint_url == "http://localhost:9324"
    cfg["queue"].update(backend="memory")
    assert isinstance(queue_from_config(cfg), MemoryQueue)
    cfg["queue"].update(backend="local", local_db=str(tmp_path / "q.sqlite"))
    monkeypatch.setattr("pharmassist.ingest.queue.PROJECT_ROOT", tmp_path)
    assert isinstance(queue_from_config(cfg), LocalQueue)
    cfg["queue"].update(backend="rabbit")
    with pytest.raises(QueueConfigError):
        queue_from_config(cfg)


def _exercise_storage(s):
    assert not s.exists("sources/d/v/a.pdf")
    s.put_bytes("sources/d/v/a.pdf", b"%PDF-1.4 bytes", "application/pdf")
    s.put_bytes("figures/d/v/p001_f0.png", b"\x89PNG")
    assert s.exists("sources/d/v/a.pdf") and s.get_bytes("sources/d/v/a.pdf") == b"%PDF-1.4 bytes"
    assert s.list_keys("sources/d/") == ["sources/d/v/a.pdf"] and s.list_keys("nothing/") == []
    with pytest.raises(KeyError):
        s.get_bytes("sources/d/v/missing.pdf")


def test_s3_storage(aws):
    s3 = aws.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="pa-test")
    _exercise_storage(S3Storage("pa-test", client=s3))


def test_local_storage(tmp_path):
    _exercise_storage(LocalStorage(tmp_path / "objects"))


def test_storage_from_config_and_the_minio_endpoint(aws, monkeypatch, tmp_path):
    cfg = copy.deepcopy(load_config())
    monkeypatch.delenv("PHARMASSIST_BUCKET", raising=False)
    with pytest.raises(StorageConfigError, match="PHARMASSIST_BUCKET"):
        storage_from_config(cfg)
    monkeypatch.setenv("PHARMASSIST_BUCKET", "pa-test")
    monkeypatch.setenv("S3_ENDPOINT_URL", "http://localhost:9000")
    s = storage_from_config(cfg)
    assert isinstance(s, S3Storage) and s.s3.meta.endpoint_url == "http://localhost:9000"
    assert cloud._s3().meta.config.s3["addressing_style"] == "path"   # MinIO buckets aren't DNS hosts
    cfg["storage"].update(backend="local", local_dir=str(tmp_path / "objects"))
    assert isinstance(storage_from_config(cfg), LocalStorage)


def test_cloud_key_helpers():
    assert cloud.upload_key("doc", "abc", "f.pdf") == "uploads/doc/abc/f.pdf"
    assert cloud.source_key("doc", "abc", "f.pdf") == "sources/doc/abc/f.pdf"
    assert cloud.figure_key("doc", "p001_f0.png") == "figures/doc/p001_f0.png"
    assert cloud.figure_key("doc", "p001_f0.png", "abc") == "figures/doc/abc/p001_f0.png"
    assert cloud.parse_cache_key("doc", "abc", "opts") == "cache/parse/doc/abc-opts.json"
    assert cloud.sha256_bytes(b"") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
