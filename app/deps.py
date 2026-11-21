"""What the API needs from the rest of the system, bundled so `create_app(deps)` is the only seam:
the store (stream A), the semantic cache (D), the answer service around the agent (B), the usage
limiter, the object storage for sources and uploads, the ingestion queue (E) and a clock. Tests
build `Deps` from fakes (tests/fakes_api.py); app/main.py builds them from config and environment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

from fastapi import Request

from pharmassist.config import PROJECT_ROOT

API = "/api/v1"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Storage(Protocol):
    """Object storage for source files, figure crops and uploads. `presign` returns None when the
    object isn't reachable by URL (local development), and the routes then serve the local copy."""
    name: str

    def presign(self, key: str, *, content_type: str | None = None, fragment: str | None = None) -> str | None: ...
    def get_bytes(self, key: str) -> bytes: ...
    def put_bytes(self, key: str, data: bytes, *, content_type: str | None = None) -> None: ...
    def ping(self) -> bool: ...


class LocalStorage:
    """Objects under a local directory (laptop runs without MinIO): nothing is presigned."""
    name = "local"

    def __init__(self, root: Path | None = None):
        self.root = Path(root or PROJECT_ROOT / "storage" / "objects")

    def presign(self, key, *, content_type=None, fragment=None):
        return None

    def get_bytes(self, key):
        return (self.root / key).read_bytes()

    def put_bytes(self, key, data, *, content_type=None):
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def ping(self):
        return True


class S3Storage:
    """The bucket named by `storage.bucket_env` (MinIO when `storage.endpoint_env` is set)."""
    name = "s3"

    def __init__(self, bucket: str, endpoint_url: str | None = None, presign_seconds: int = 600, client=None):
        self.bucket, self.endpoint_url, self.presign_seconds = bucket, endpoint_url, presign_seconds
        self._client = client

    def client(self):
        if self._client is None:
            import boto3
            from botocore.config import Config
            self._client = boto3.client("s3", endpoint_url=self.endpoint_url, config=Config(signature_version="s3v4"))
        return self._client

    def presign_client(self):
        """Presigned URLs must carry the host the *browser* will use: with the compose store the API talks
        to http://s3:9000 but the laptop reaches it as S3_PUBLIC_ENDPOINT_URL (http://localhost:9000), and
        the SigV4 signature is bound to that host. Unset (AWS), the normal client signs."""
        public = os.environ.get("S3_PUBLIC_ENDPOINT_URL") or None
        if not public or public == self.endpoint_url:
            return self.client()
        if getattr(self, "_presign_client", None) is None:
            import boto3
            from botocore.config import Config
            self._presign_client = boto3.client("s3", endpoint_url=public,
                                                config=Config(signature_version="s3v4", s3={"addressing_style": "path"}))
        return self._presign_client

    def presign(self, key, *, content_type=None, fragment=None):
        from pharmassist import cloud
        url = cloud.presign(key, self.presign_seconds, s3=self.presign_client(), name=self.bucket, content_type=content_type)
        return f"{url}#{fragment}" if fragment else url

    def get_bytes(self, key):
        return self.client().get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def put_bytes(self, key, data, *, content_type=None):
        extra = {"ContentType": content_type} if content_type else {}
        self.client().put_object(Bucket=self.bucket, Key=key, Body=data, **extra)

    def ping(self):
        try:
            self.client().head_bucket(Bucket=self.bucket)
            return True
        except Exception:
            return False


class Guard(Protocol):
    """Usage limits for /ask (app/limits.py)."""
    def admit(self, user_id: str) -> None: ...
    def settle(self, user_id: str, cost_usd: float | None) -> None: ...
    def usage(self) -> dict: ...


@dataclass
class Deps:
    cfg: dict                                  # the whole config.yaml
    store: object                              # pharmassist.store.protocols.Store
    cache: object                              # pharmassist.cache.base.SemanticCache
    answers: object                            # app.answer_service.AnswerService
    limiter: Guard
    storage: Storage
    jwt_secret: str
    queue: object | None = None                # the ingestion queue handed to submit_upload
    clock: Callable[[], datetime] = utcnow
    submit_upload: Callable | None = None      # pharmassist.ingest.submit.submit_upload, injected in tests
    version: str | None = None
    insecure_cookies: bool = field(default_factory=lambda: os.environ.get("APP_INSECURE_COOKIES") == "1")
    frontend_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "frontend" / "dist")
    docs_dir: Path | None = None               # local source PDFs (development); default pharmassist.catalog.docs_dir()
    figures_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "storage" / "figures")

    @property
    def auth_cfg(self) -> dict:
        return self.cfg.get("auth") or {}

    @property
    def app_cfg(self) -> dict:
        return self.cfg.get("app") or {}


def get_deps(request: Request) -> Deps:
    return request.app.state.deps
