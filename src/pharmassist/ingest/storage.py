"""Object storage for the ingestion pipeline: source files, figure crops and the Docling parse cache.

S3 (or MinIO through S3_ENDPOINT_URL) in deployments, a local folder for tests and a laptop. Keys
follow pharmassist.cloud's layout, so the API's presigned source and figure links keep working:
  sources/<doc_id>/<sha16>/<file_name>     the uploaded file, content-addressed
  figures/<doc_id>/<sha16>/<name>.png      the indexed figure crops of that version
  cache/parse/<doc_id>/<sha16>-<opts>.json the Docling result, so a re-run of the same bytes skips
                                           the ~10 minutes of conversion a large guideline costs
"""

import os
from abc import ABC, abstractmethod
from pathlib import Path

from pharmassist import cloud
from pharmassist.config import PROJECT_ROOT


class Storage(ABC):
    @abstractmethod
    def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None: ...

    @abstractmethod
    def get_bytes(self, key: str) -> bytes:
        """Raises KeyError when the key doesn't exist."""

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def list_keys(self, prefix: str) -> list[str]: ...

    def put_file(self, path: Path, key: str, content_type: str | None = None) -> None:
        self.put_bytes(key, Path(path).read_bytes(), content_type or "application/octet-stream")

    def get_file(self, key: str, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.get_bytes(key))
        return path


class LocalStorage(Storage):
    def __init__(self, root: Path | str):
        self.root = Path(root)

    def _p(self, key: str) -> Path:
        return self.root / key

    def put_bytes(self, key, data, content_type="application/octet-stream"):
        p = self._p(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def get_bytes(self, key):
        p = self._p(key)
        if not p.is_file():
            raise KeyError(key)
        return p.read_bytes()

    def exists(self, key):
        return self._p(key).is_file()

    def list_keys(self, prefix):
        base = self._p(prefix)
        folder = base if base.is_dir() else base.parent
        if not folder.is_dir():
            return []
        return sorted(p.relative_to(self.root).as_posix() for p in folder.rglob("*")
                      if p.is_file() and p.relative_to(self.root).as_posix().startswith(prefix))


class S3Storage(Storage):
    def __init__(self, bucket: str, client=None):
        self.bucket, self.s3 = bucket, client or cloud._s3()

    def put_bytes(self, key, data, content_type="application/octet-stream"):
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    def get_bytes(self, key):
        try:
            return self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except self.s3.exceptions.NoSuchKey:
            raise KeyError(key) from None
        except self.s3.exceptions.ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("404", "NotFound", "NoSuchKey"):
                raise KeyError(key) from None
            raise

    def exists(self, key):
        return cloud.exists(key, self.s3, self.bucket)

    def list_keys(self, prefix):
        return cloud.list_keys(prefix, self.s3, self.bucket)

    def put_file(self, path, key, content_type=None):
        cloud.put_file(Path(path), key, self.s3, self.bucket, content_type)

    def get_file(self, key, path):
        try:
            return cloud.get_file(key, Path(path), self.s3, self.bucket)
        except self.s3.exceptions.ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("404", "NotFound", "NoSuchKey"):
                raise KeyError(key) from None
            raise


class StorageConfigError(RuntimeError):
    """The bucket (or local folder) the pipeline needs isn't configured."""


def storage_from_config(cfg: dict) -> Storage:
    """`storage.backend` s3 (default; bucket from `storage.bucket_env`, endpoint from
    `storage.endpoint_env` for MinIO) or local (`storage.local_dir`)."""
    s = cfg["storage"]
    if s.get("backend", "s3") == "local":
        return LocalStorage(PROJECT_ROOT / s.get("local_dir", "storage/objects"))
    bucket = os.environ.get(s.get("bucket_env", "PHARMASSIST_BUCKET"))
    if not bucket:
        raise StorageConfigError(f"set {s.get('bucket_env', 'PHARMASSIST_BUCKET')} (or storage.backend: local)")
    return S3Storage(bucket)
