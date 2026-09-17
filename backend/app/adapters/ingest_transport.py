"""Ingest transport — http (local in-process) or pubsub (prod).

In `http` mode, the poller POSTs `{source, poll_id, raw_uri}` directly to the
normalizer's `/internal/normalize` endpoint. No auth, no envelope.

In `pubsub` mode, the poller publishes to the configured topic; the normalizer is a
push-subscribed Cloud Run Service that receives the Pub/Sub envelope.

Both modes carry the *same* application payload; only the wire format differs. The
normalizer's request handler unwraps the envelope shape if present.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import TypedDict
from uuid import UUID

import httpx

from app.core.config import Settings, get_settings


class IngestMessage(TypedDict):
    source: str
    poll_id: str
    raw_uri: str


class IngestTransport(ABC):
    @abstractmethod
    def publish(self, source: str, poll_id: UUID, raw_uri: str) -> None: ...


class _HttpTransport(IngestTransport):
    """Direct HTTP POST to the normalizer. Used for local dev only."""

    def __init__(self, normalizer_url: str) -> None:
        self._url = normalizer_url.rstrip("/") + "/internal/normalize"

    def publish(self, source: str, poll_id: UUID, raw_uri: str) -> None:
        body: IngestMessage = {"source": source, "poll_id": str(poll_id), "raw_uri": raw_uri}
        response = httpx.post(self._url, json=body, timeout=60.0)
        response.raise_for_status()


class _PubsubTransport(IngestTransport):
    def __init__(self, project: str, topic: str) -> None:
        from google.cloud import pubsub_v1

        self._publisher = pubsub_v1.PublisherClient()
        self._topic_path = self._publisher.topic_path(project, topic)

    def publish(self, source: str, poll_id: UUID, raw_uri: str) -> None:
        body: IngestMessage = {"source": source, "poll_id": str(poll_id), "raw_uri": raw_uri}
        future = self._publisher.publish(self._topic_path, json.dumps(body).encode("utf-8"))
        future.result(timeout=30)


def build_ingest_transport(settings: Settings | None = None) -> IngestTransport:
    s = settings or get_settings()
    if s.ingest_transport == "http":
        return _HttpTransport(normalizer_url=s.normalizer_url)
    if s.ingest_transport == "pubsub":
        if not s.pubsub_project:
            raise RuntimeError("INGEST_TRANSPORT=pubsub requires PUBSUB_PROJECT")
        return _PubsubTransport(project=s.pubsub_project, topic=s.pubsub_ingest_topic)
    raise RuntimeError(f"unknown INGEST_TRANSPORT: {s.ingest_transport}")
