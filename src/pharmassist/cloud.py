"""The S3 object store: source documents, admin uploads, figure crops and the Docling parse cache.

One private bucket (PHARMASSIST_BUCKET; S3_ENDPOINT_URL points it at MinIO locally), laid out as:

  uploads/<doc_id>/<sha16>/<file>          an admin upload as received (staging)
  sources/<doc_id>/<sha16>/<file>          each document version, content-addressed
  figures/<doc_id>/<sha16>/pNNN_fK.png     figure crops per document version (linked from citations)
  cache/parse/<doc_id>/<sha16>-<opts>.json Docling results, reused when the same bytes are re-indexed

The ingestion worker writes here (pharmassist.ingest.storage); the API serves documents and figures
through short-lived presigned URLs. Nothing here logs object contents or credentials.
"""

import hashlib
import os
from pathlib import Path

PRESIGN_SECONDS = 600


def bucket() -> str | None:
    return os.environ.get("PHARMASSIST_BUCKET") or None


def endpoint_url() -> str | None:
    """S3_ENDPOINT_URL: MinIO (docker-compose) locally; unset on AWS."""
    return os.environ.get("S3_ENDPOINT_URL") or None


def _s3():
    import boto3
    from botocore.config import Config
    # SigV4 presigned URLs (required for KMS-encrypted objects and newer regions); path-style
    # addressing for MinIO, whose bucket names aren't DNS hosts
    endpoint = endpoint_url()
    config = Config(signature_version="s3v4", s3={"addressing_style": "path"} if endpoint else {})
    return boto3.client("s3", config=config, endpoint_url=endpoint)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha16(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def source_key(doc_id: str, version: str, filename: str) -> str:
    return f"sources/{doc_id}/{version}/{filename}"


def upload_key(doc_id: str, version: str, filename: str) -> str:
    """Where the API stages an admin upload before (or while) submit_upload registers it."""
    return f"uploads/{doc_id}/{version}/{filename}"


def figure_key(doc_id: str, filename: str, version: str | None = None) -> str:
    """Crops live per document version; without `version` (the seeded local build) per document."""
    return f"figures/{doc_id}/{version}/{filename}" if version else f"figures/{doc_id}/{filename}"


def parse_cache_key(doc_id: str, version: str, options: str) -> str:
    return f"cache/parse/{doc_id}/{version}-{options}.json"


def put_bytes(data: bytes, key: str, s3=None, name: str | None = None,
              content_type: str = "application/octet-stream") -> None:
    (s3 or _s3()).put_object(Bucket=name or bucket(), Key=key, Body=data, ContentType=content_type)


def get_bytes(key: str, s3=None, name: str | None = None) -> bytes:
    return (s3 or _s3()).get_object(Bucket=name or bucket(), Key=key)["Body"].read()


def exists(key: str, s3=None, name: str | None = None) -> bool:
    s3 = s3 or _s3()
    try:
        s3.head_object(Bucket=name or bucket(), Key=key)
        return True
    except s3.exceptions.ClientError as e:
        if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
            return False
        raise


def put_file(path: Path, key: str, s3=None, name: str | None = None, content_type: str | None = None) -> None:
    extra = {"ContentType": content_type} if content_type else {}
    (s3 or _s3()).upload_file(str(path), name or bucket(), key, ExtraArgs=extra or None)


def get_file(key: str, path: Path, s3=None, name: str | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    (s3 or _s3()).download_file(name or bucket(), key, str(path))
    return path


def list_keys(prefix: str, s3=None, name: str | None = None) -> list[str]:
    s3 = s3 or _s3()
    out, kw = [], {"Bucket": name or bucket(), "Prefix": prefix}
    while True:
        page = s3.list_objects_v2(**kw)
        out += [o["Key"] for o in page.get("Contents", [])]
        if not page.get("IsTruncated"):
            return out
        kw["ContinuationToken"] = page["NextContinuationToken"]


def presign(key: str, seconds: int = PRESIGN_SECONDS, s3=None, name: str | None = None,
            content_type: str | None = None) -> str:
    params = {"Bucket": name or bucket(), "Key": key}
    if content_type:
        params["ResponseContentType"] = content_type
    return (s3 or _s3()).generate_presigned_url("get_object", Params=params, ExpiresIn=seconds)
