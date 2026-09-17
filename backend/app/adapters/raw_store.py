"""Raw payload store — local filesystem (dev) or GCS (prod).

The poller writes the full snapshot via `put(source, poll_id, bytes)` and gets back a
URI string. The normalizer reads it back via `get(uri)`. The URI scheme tells the
normalizer where the bytes live, so a fs-stored payload could in theory be read by a
gcs-configured normalizer (we don't rely on this; the prototype runs both with the
same backend).

URI schemes:
    fs  -> `file:///absolute/path`
    gcs -> `gs://bucket/key`
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

from app.core.config import Settings, get_settings


class RawPayloadStore(ABC):
    @abstractmethod
    def put(self, source: str, poll_id: UUID, payload: bytes) -> str: ...

    @abstractmethod
    def get(self, uri: str) -> bytes: ...


class _FsRawStore(RawPayloadStore):
    def __init__(self, root: Path) -> None:
        self._root = root

    def put(self, source: str, poll_id: UUID, payload: bytes) -> str:
        target_dir = self._root / source
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{poll_id}.json"
        target.write_bytes(payload)
        return f"file://{target.resolve()}"

    def get(self, uri: str) -> bytes:
        parsed = urlparse(uri)
        if parsed.scheme != "file":
            raise ValueError(f"fs store cannot read non-file URI: {uri}")
        return Path(parsed.path).read_bytes()


class _GcsRawStore(RawPayloadStore):
    def __init__(self, bucket: str) -> None:
        from google.cloud import storage

        self._client = storage.Client()
        self._bucket_name = bucket
        self._bucket = self._client.bucket(bucket)

    def put(self, source: str, poll_id: UUID, payload: bytes) -> str:
        key = f"{source}/{poll_id}.json"
        self._bucket.blob(key).upload_from_string(payload, content_type="application/json")
        return f"gs://{self._bucket_name}/{key}"

    def get(self, uri: str) -> bytes:
        parsed = urlparse(uri)
        if parsed.scheme != "gs":
            raise ValueError(f"gcs store cannot read non-gs URI: {uri}")
        return self._client.bucket(parsed.netloc).blob(parsed.path.lstrip("/")).download_as_bytes()


def build_raw_store(settings: Settings | None = None) -> RawPayloadStore:
    s = settings or get_settings()
    if s.raw_store == "fs":
        return _FsRawStore(Path(s.raw_store_fs_root).resolve())
    if s.raw_store == "gcs":
        if not s.gcs_raw_bucket:
            raise RuntimeError("RAW_STORE=gcs requires GCS_RAW_BUCKET")
        return _GcsRawStore(bucket=s.gcs_raw_bucket)
    raise RuntimeError(f"unknown RAW_STORE: {s.raw_store}")
