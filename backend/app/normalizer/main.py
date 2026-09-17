"""Normalizer Cloud Run Service entrypoint.

Endpoints:
  POST /internal/normalize   — ingest snapshot processing (Pub/Sub push or direct HTTP)
  POST /internal/dlq — dead-letter handler
  POST /internal/config-reload — hot-reload ownership/rbac/policy caches

Pub/Sub push requests include an OIDC bearer when `INGEST_TRANSPORT=pubsub`.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request, status

from app.adapters.raw_store import build_raw_store
from app.api.pubsub_auth import verify_pubsub_oidc
from app.core.config import get_settings
from app.core.config_store import get_config_cache
from app.core.db import session_scope
from app.core.finding_owner import resolve_finding_owner_team
from app.core.policy import get_policy_cache
from app.internal.config_reload import reload_caches
from app.internal.dlq import record_dlq_event
from app.internal.pubsub import delivery_attempt_from_request, pubsub_message_id, unwrap_pubsub_body
from app.internal.slack import notify_dlq_ingest_failure
from app.normalizer.mappers.dependabot import DEPENDABOT_SOURCE
from app.normalizer.mappers.dependabot import map_snapshot as map_dependabot_snapshot
from app.normalizer.mappers.jira_pentest import PENTEST_SOURCE
from app.normalizer.mappers.jira_pentest import map_snapshot as map_jira_pentest_snapshot
from app.normalizer.mappers.sonarcloud import SONARCLOUD_SOURCE
from app.normalizer.mappers.sonarcloud import map_snapshot as map_sonarcloud_snapshot
from app.normalizer.mappers.wiz import WIZ_SOURCE
from app.normalizer.mappers.wiz import map_snapshot as map_wiz_snapshot
from app.normalizer.processor import process_snapshot

log = logging.getLogger("secdb.normalizer")

_OIDC = [Depends(verify_pubsub_oidc)]

_MAPPERS = {
    DEPENDABOT_SOURCE: map_dependabot_snapshot,
    SONARCLOUD_SOURCE: map_sonarcloud_snapshot,
    WIZ_SOURCE: map_wiz_snapshot,
    PENTEST_SOURCE: map_jira_pentest_snapshot,
}


def create_app() -> FastAPI:
    settings = get_settings()
    raw_store = build_raw_store(settings)

    app = FastAPI(title="secdb normalizer", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "env": settings.env}

    @app.post("/internal/config-reload", dependencies=_OIDC)
    async def config_reload() -> dict[str, str]:
        reload_caches()
        return {"status": "reloaded"}

    @app.post("/internal/dlq", dependencies=_OIDC)
    async def dlq_handler(request: Request) -> dict[str, Any]:
        body = await request.json()
        message_id = pubsub_message_id(body)
        if not message_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "pub/sub message missing messageId")

        delivery_attempt = delivery_attempt_from_request(dict(request.headers))
        failure_reason = None
        if isinstance(body.get("message"), dict):
            failure_reason = body["message"].get("attributes", {}).get("CloudPubSubDeadLetterSourceDeliveryCount")

        with session_scope() as session:
            inserted = record_dlq_event(
                session,
                message_id=message_id,
                envelope=body,
                delivery_attempt=delivery_attempt,
                failure_reason=failure_reason,
            )

        if inserted:
            inner = unwrap_pubsub_body(body)
            notify_dlq_ingest_failure(
                source=str(inner.get("source")) if inner.get("source") else None,
                poll_id=str(inner.get("poll_id")) if inner.get("poll_id") else None,
                raw_uri=str(inner.get("raw_uri")) if inner.get("raw_uri") else None,
                delivery_attempt=delivery_attempt,
                message_id=message_id,
                settings=settings,
            )

        return {"message_id": message_id, "inserted": inserted}

    @app.post("/internal/normalize", dependencies=_OIDC)
    async def normalize(request: Request) -> dict[str, Any]:
        body = await request.json()
        payload = unwrap_pubsub_body(body)

        source = payload.get("source")
        poll_id_raw = payload.get("poll_id")
        raw_uri = payload.get("raw_uri")

        if not (source and poll_id_raw and raw_uri):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "payload must include source, poll_id, raw_uri",
            )

        try:
            poll_id = UUID(poll_id_raw)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"invalid poll_id: {exc}") from exc

        mapper = _MAPPERS.get(source)
        if mapper is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unsupported source: {source}")

        raw_bytes = raw_store.get(raw_uri)
        try:
            raw_json = json.loads(raw_bytes)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"raw payload not JSON: {exc}"
            ) from exc

        normalized = mapper(raw_json)

        ownership = get_config_cache().get_ownership()
        registry = get_config_cache().get_component_registry()
        thresholds = get_policy_cache().get_auto_close()

        def owner_resolver(source: str, asset_id: str, tags: list[str]) -> str:
            return resolve_finding_owner_team(
                source=source,
                asset_id=asset_id,
                tags=tags,
                ownership=ownership,
                wiz_service_to_team=registry.wiz_service_to_team,
            )

        with session_scope() as session:
            result = process_snapshot(
                session,
                source=source,
                poll_id=poll_id,
                raw_uri=raw_uri,
                findings=normalized,
                owner_resolver=owner_resolver,
                auto_close_threshold=thresholds.threshold_for(source),
            )

        return {
            "source": source,
            "poll_id": str(poll_id),
            "already_processed": result.already_processed,
            "inserted": result.inserted,
            "updated": result.updated,
            "reopened": result.reopened,
            "auto_closed": result.auto_closed,
            "absent_marked": result.absent_marked,
            "finding_count": result.finding_count,
        }

    log.info("normalizer.boot env=%s raw_store=%s", settings.env, settings.raw_store)
    return app


app = create_app()
