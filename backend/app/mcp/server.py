"""Phase-1 MCP server — read-only access to the dashboard.

Transports (set via `MCP_TRANSPORT`):
  - `stdio` (default): local dev, uses X-Dev-Identity against ENV=local API.
  - `streamable-http`: hosted production; forwards caller's bearer token to API.

Configure clients per `docs/user/mcp-server.md` and `docs/dev-setup.md`.
"""

from __future__ import annotations

import os
from typing import Any, Literal

from mcp.server.fastmcp import Context, FastMCP

from app.mcp.client import DashboardClient, hosted_mode

mcp = FastMCP("secdb")
_client = DashboardClient()

Severity = Literal["critical", "high", "medium", "low", "info"]
Status = Literal[
    "open", "triaged", "in_progress", "fixed", "auto_closed", "risk_accepted", "suppressed"
]


def _extract_bearer(ctx: Context | None) -> str | None:
    if not hosted_mode() or ctx is None:
        return None
    try:
        request = ctx.request_context.request
        auth = request.headers.get("authorization") or request.headers.get("Authorization") or ""
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
    except (AttributeError, LookupError):
        pass
    return None


@mcp.tool()
async def get_findings(
    ctx: Context,
    team: str | None = None,
    repo: str | None = None,
    asset: str | None = None,
    severity: list[Severity] | None = None,
    status: list[Status] | None = None,
    source: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """List open security findings across the dashboard.

    Wraps `GET /findings`. Every authenticated caller has org-wide read
    access — narrowing happens via the filters below, not by identity.
    Admin-only sources (today: `sonarcloud_trivy`) are excluded by default
    and only reachable by an admin caller passing `source="sonarcloud_trivy"`
    explicitly.

    Filters combine with AND semantics; multi-value filters (`severity`,
    `status`) combine with OR semantics within themselves.

    Naming convention pitfall — `repo` does an exact match on the asset's
    `repo:<full-path>` key, so for a SonarCloud-backed project you must
    pass the full GitHub org+repo slug (e.g. `ExampleOrg/legacy-translator`,
    not `legacy-translator`). For substring lookups when you only know a
    partial name, use `asset` instead — it does a case-insensitive ILIKE
    on the human-readable asset display string and is the right escape
    hatch when the exact slug isn't known. Empty results from `repo=`
    almost always mean the slug is off; retry with `asset=<substring>`.
    """
    return await _client.get(
        "/findings",
        params={
            "team": team,
            "repo": repo,
            "asset": asset,
            "severity": severity,
            "status": status,
            "source": source,
            "limit": limit,
        },
        bearer=_extract_bearer(ctx),
    )


@mcp.tool()
async def get_sla_breaches(
    ctx: Context, team: str | None = None, limit: int = 50
) -> dict[str, Any]:
    """List open critical+high findings that have breached their SLA window."""
    return await _client.get(
        "/findings",
        params={
            "team": team,
            "severity": ["critical", "high"],
            "sla_breached": "true",
            "sort_by": "sla",
            "sort_dir": "desc",
            "limit": limit,
        },
        bearer=_extract_bearer(ctx),
    )


@mcp.tool()
async def get_scanner_health(ctx: Context) -> dict[str, Any]:
    """Report each scanner source's status (active / stale / dark / no_data)."""
    return await _client.get("/scanners/health", bearer=_extract_bearer(ctx))


@mcp.tool()
async def get_metrics_summary(
    ctx: Context, team: str | None = None, trend_days: int = 30
) -> dict[str, Any]:
    """Return headline KPIs plus a recent severity trend, optionally narrowed by team."""
    bearer = _extract_bearer(ctx)
    summary = await _client.get("/metrics/summary", params={"team": team}, bearer=bearer)
    trend = await _client.get(
        "/metrics/trend", params={"team": team, "days": trend_days}, bearer=bearer
    )
    return {"summary": summary, "trend": trend}


def main() -> None:
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "streamable-http":
        # FastMCP.run() doesn't accept host/port kwargs in the version we're
        # pinned to — host/port live on `mcp.settings` and are read at run()
        # time. Mutating them before run() works for both this version and
        # whatever later versions add explicit run() kwargs.
        mcp.settings.host = os.environ.get("MCP_HOST", "0.0.0.0")
        mcp.settings.port = int(os.environ.get("MCP_PORT", "3001"))
        # FastMCP enables DNS-rebinding protection by default with
        # `allowed_hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]`, which
        # rejects every public-hostname request with "Invalid Host header".
        # The validator only supports exact-match or `name:*` port-wildcards
        # (no host-wildcards), so an `MCP_ALLOWED_HOSTS=*` override would not
        # work either. The protection exists to stop malicious browser tabs
        # from reaching a localhost-bound MCP server cross-origin; it is
        # irrelevant for a bearer-authenticated server on a public URL — auth
        # is enforced one layer up (`DashboardClient._headers` requires
        # `Authorization: Bearer …` in hosted mode). Disable host/origin
        # checks entirely here. If a deployment ever needs the per-host ACL
        # back, set MCP_ALLOWED_HOSTS to a comma-separated allowlist; the
        # presence of that env var re-enables the protection automatically.
        allowed = os.environ.get("MCP_ALLOWED_HOSTS", "").strip()
        if allowed:
            mcp.settings.transport_security.enable_dns_rebinding_protection = True
            mcp.settings.transport_security.allowed_hosts = [
                h.strip() for h in allowed.split(",") if h.strip()
            ]
        else:
            mcp.settings.transport_security.enable_dns_rebinding_protection = False
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
