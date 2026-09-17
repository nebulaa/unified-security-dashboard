"""Thin async HTTP client for the dashboard API (local dev + hosted MCP).

Auth modes:
  - Bearer token (production / hosted MCP): forwards the caller's
    `Authorization: Bearer secdb_live_...` to FastAPI.
  - Dev identity (local stdio): injects `X-Dev-Identity`, mirroring the
    Next.js dev proxy (`frontend/app/lib/api/server.ts`).
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, cast

import httpx

from app.core.cloud_run_auth import fetch_id_token

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_TIMEOUT_SECONDS = 30.0


def _dev_identity_header() -> str:
    email = os.environ.get("DEV_IDENTITY_EMAIL", "dev1@example.com")
    groups_raw = os.environ.get("DEV_IDENTITY_GROUPS", "")
    groups = [g.strip() for g in groups_raw.split(",") if g.strip()]
    return json.dumps({"email": email, "google.groups": groups})


def hosted_mode() -> bool:
    return os.environ.get("MCP_TRANSPORT", "stdio") == "streamable-http"


class DashboardClient:
    """Async HTTP client for the dashboard API.

    Authorization on the API side is per-email: bearer tokens inherit the
    owner's email-based admin status; the dev-identity path forwards the
    `DEV_IDENTITY_EMAIL` env var. No role plumbing.
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._base_url = base_url or os.environ.get("MCP_API_BASE_URL", DEFAULT_BASE_URL)
        self._timeout = timeout

    async def _headers(self, bearer: str | None) -> dict[str, str]:
        if bearer:
            headers = {
                "Authorization": f"Bearer {bearer}",
                "Accept": "application/json",
            }
            audience = os.environ.get("CLOUD_RUN_API_AUDIENCE")
            if audience:
                token = await asyncio.to_thread(fetch_id_token, audience)
                # Cloud Run consumes this token while preserving Authorization
                # for the dashboard's personal bearer-token authentication.
                headers["X-Serverless-Authorization"] = f"Bearer {token}"
            return headers
        # Hosted MCP is publicly reachable; the only acceptable auth there is a
        # personal bearer token. Falling back to X-Dev-Identity in
        # hosted mode would let any unauthenticated caller impersonate the
        # default DEV_IDENTITY_EMAIL against the API. Local stdio mode keeps
        # the dev-identity path because the API enforces ENV=local + same-host.
        if hosted_mode():
            raise PermissionError(
                "Authorization: Bearer secdb_live_... is required for hosted MCP "
                "calls. Mint a token at /settings/mcp."
            )
        return {
            "X-Dev-Identity": _dev_identity_header(),
            "Accept": "application/json",
        }

    async def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        bearer: str | None = None,
    ) -> dict[str, Any]:
        clean: dict[str, Any] = {}
        for key, value in (params or {}).items():
            if value is None:
                continue
            clean[key] = value

        async with httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
        ) as client:
            response = await client.get(path, params=clean, headers=await self._headers(bearer))
            response.raise_for_status()
            return cast(dict[str, Any], response.json())
