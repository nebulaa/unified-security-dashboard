from __future__ import annotations

import pytest

from app.mcp.client import DashboardClient


@pytest.mark.asyncio
async def test_hosted_bearer_adds_cloud_run_identity_without_replacing_app_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
    monkeypatch.setenv("CLOUD_RUN_API_AUDIENCE", "https://secdb-api.example.run.app")
    monkeypatch.setattr(
        "app.mcp.client.fetch_id_token",
        lambda audience: f"id-token-for:{audience}",
    )

    headers = await DashboardClient()._headers("secdb_live_personal")

    assert headers == {
        "Authorization": "Bearer secdb_live_personal",
        "Accept": "application/json",
        "X-Serverless-Authorization": (
            "Bearer id-token-for:https://secdb-api.example.run.app"
        ),
    }


@pytest.mark.asyncio
async def test_local_bearer_does_not_require_cloud_run_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CLOUD_RUN_API_AUDIENCE", raising=False)

    headers = await DashboardClient()._headers("secdb_live_personal")

    assert headers == {
        "Authorization": "Bearer secdb_live_personal",
        "Accept": "application/json",
    }


@pytest.mark.asyncio
async def test_hosted_mode_still_rejects_missing_personal_bearer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")

    with pytest.raises(PermissionError, match="secdb_live"):
        await DashboardClient()._headers(None)
