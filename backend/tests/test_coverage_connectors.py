"""Read-only coverage connector contracts, with all upstream APIs mocked."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from app.coverage.config import parse_coverage_config
from app.coverage.connectors.github import GitHubConnector
from app.coverage.connectors.sonar import SonarConnector

NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)

CONFIG = parse_coverage_config(
    """
inventory:
  repos:
    eligibility:
      pushed_within_days: 90
projects:
  product-offer-order:
    label: PRODUCT Offer & Order
    code:
      github_topics: [product-services]
      exclude_github_topics: [product-services-legacy]
exceptions: []
"""
)


def test_github_defines_repo_y_and_dependabot_signals() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/orgs/ExampleOrg/repos":
            return httpx.Response(
                200,
                json=[
                    {
                        "name": "covered",
                        "archived": False,
                        "fork": False,
                        "pushed_at": "2026-09-10T00:00:00Z",
                        "topics": ["product-services"],
                    },
                    {
                        "name": "alerts-only",
                        "archived": False,
                        "fork": False,
                        "pushed_at": "2026-09-10T00:00:00Z",
                        "topics": ["product-services"],
                    },
                    {
                        "name": "archived",
                        "archived": True,
                        "fork": False,
                        "pushed_at": "2026-09-10T00:00:00Z",
                        "topics": ["product-services"],
                    },
                ],
            )
        if path.endswith("/vulnerability-alerts"):
            return httpx.Response(204)
        if path.endswith("/contents/.github/dependabot.yml"):
            if "/repos/ExampleOrg/covered/" in path:
                return httpx.Response(200, json={"type": "file"})
            return httpx.Response(404)
        raise AssertionError(path)

    client = httpx.Client(
        base_url="https://api.github.com", transport=httpx.MockTransport(handler)
    )
    connector = GitHubConnector(org="ExampleOrg", token="test", client=client, workers=1)

    items = connector.collect(CONFIG, now=NOW)
    covered = next(item for item in items if item.display == "covered")
    alerts_only = next(item for item in items if item.display == "alerts-only")
    archived = next(item for item in items if item.display == "archived")
    assert covered.in_scope is True
    assert covered.projects == ("product-offer-order",)
    assert covered.signals == frozenset(
        {"dependabot_enabled", "dependabot_version_updates"}
    )
    assert alerts_only.signals == frozenset({"dependabot_enabled"})
    assert archived.in_scope is False


def test_sonar_uses_supported_projects_api_and_30_day_cutoff() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/projects/search"
        return httpx.Response(
            200,
            json={
                "paging": {"total": 2},
                "components": [
                    {
                        "key": "ExampleOrg_recent",
                        "lastAnalysisDate": "2026-09-10T00:00:00Z",
                    },
                    {
                        "key": "ExampleOrg_old",
                        "lastAnalysisDate": "2026-01-01T00:00:00Z",
                    },
                ],
            },
        )

    client = httpx.Client(
        base_url="https://sonarcloud.io", transport=httpx.MockTransport(handler)
    )
    connector = SonarConnector(
        token="test", organizations=("exampleorg",), client=client
    )
    covered = connector.covered_repo_ids(
        org="ExampleOrg",
        repo_names={"recent", "old"},
        explicit_map={},
        now=NOW,
    )
    assert covered == {"repo:ExampleOrg/recent"}
