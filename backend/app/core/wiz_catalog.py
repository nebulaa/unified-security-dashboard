"""Wiz Service Catalog helpers for config validation."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

from app.pollers.wiz import _graphql_errors, fetch_oauth_token

log = logging.getLogger("secdb.wiz_catalog")

_APPLICATION_SERVICES_QUERY = """
query WizApplicationServices($first: Int, $after: String) {
  applicationServices(first: $first, after: $after) {
    nodes {
      displayName
      projects {
        name
      }
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
"""

_PAGE_SIZE = 500


@dataclass(frozen=True)
class WizCatalogService:
    display_name: str
    project_names: tuple[str, ...] = ()


def wiz_live_check_configured() -> bool:
    """True when env has enough to call the Wiz GraphQL API."""
    return bool(
        os.environ.get("WIZ_CLIENT_ID", "").strip()
        and os.environ.get("WIZ_CLIENT_SECRET", "").strip()
        and os.environ.get("WIZ_API_URL", "").strip()
    )


def fetch_application_services(
    *,
    api_url: str,
    auth_url: str,
    client_id: str,
    client_secret: str,
    audience: str = "wiz-api",
    client: httpx.Client | None = None,
) -> list[WizCatalogService]:
    """Return all Wiz Service Catalog entries."""
    own = client is None
    http = client or httpx.Client(timeout=120.0)
    services: list[WizCatalogService] = []
    try:
        token = fetch_oauth_token(
            auth_url=auth_url,
            client_id=client_id,
            client_secret=client_secret,
            audience=audience,
            client=http,
        )
        cursor: str | None = None
        while True:
            variables: dict[str, Any] = {"first": _PAGE_SIZE}
            if cursor:
                variables["after"] = cursor
            response = http.post(
                api_url,
                headers={"Authorization": f"Bearer {token}"},
                json={"query": _APPLICATION_SERVICES_QUERY, "variables": variables},
            )
            if response.status_code == 401:
                raise RuntimeError("wiz catalog: GraphQL 401 — token invalid or expired")
            response.raise_for_status()
            payload = response.json()
            errors = _graphql_errors(payload)
            if errors:
                messages = "; ".join(str(e.get("message", e)) for e in errors)
                raise RuntimeError(f"wiz catalog: GraphQL errors: {messages}")
            conn = (payload.get("data") or {}).get("applicationServices") or {}
            for node in conn.get("nodes") or []:
                name = str(node.get("displayName") or "").strip()
                if not name:
                    continue
                projects = tuple(
                    str(p.get("name") or "").strip()
                    for p in (node.get("projects") or [])
                    if p.get("name")
                )
                services.append(WizCatalogService(display_name=name, project_names=projects))
            page = conn.get("pageInfo") or {}
            if not page.get("hasNextPage"):
                break
            cursor = page.get("endCursor")
            if not cursor:
                break
        return services
    finally:
        if own:
            http.close()


def fetch_application_services_from_env() -> list[WizCatalogService]:
    """Load catalog using `WIZ_*` environment variables."""
    api_url = os.environ["WIZ_API_URL"].strip()
    auth_url = os.environ.get("WIZ_AUTH_URL", "https://auth.app.wiz.io/oauth/token").strip()
    client_id = os.environ["WIZ_CLIENT_ID"].strip()
    client_secret = os.environ["WIZ_CLIENT_SECRET"].strip()
    audience = os.environ.get("WIZ_OAUTH_AUDIENCE", "wiz-api").strip() or "wiz-api"
    return fetch_application_services(
        api_url=api_url,
        auth_url=auth_url,
        client_id=client_id,
        client_secret=client_secret,
        audience=audience,
    )


def fetch_wiz_application_service_names(
    *,
    api_url: str,
    auth_url: str,
    client_id: str,
    client_secret: str,
    audience: str = "wiz-api",
    client: httpx.Client | None = None,
) -> set[str]:
    """Return all Wiz Service Catalog `displayName` values (registry join keys)."""
    return {
        s.display_name
        for s in fetch_application_services(
            api_url=api_url,
            auth_url=auth_url,
            client_id=client_id,
            client_secret=client_secret,
            audience=audience,
            client=client,
        )
    }


def fetch_wiz_application_service_names_from_env() -> set[str]:
    """Load catalog names using `WIZ_*` environment variables."""
    return {s.display_name for s in fetch_application_services_from_env()}
