"""SonarCloud project-analysis connector."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx


class SonarConnector:
    def __init__(
        self,
        *,
        token: str,
        organizations: tuple[str, ...],
        base_url: str = "https://sonarcloud.io",
        client: httpx.Client | None = None,
    ) -> None:
        self.organizations = organizations
        self._own_client = client is None
        self._http = client or httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=60,
            auth=(token, ""),
            headers={"Accept": "application/json", "User-Agent": "secdb-coverage/0.1"},
        )

    def close(self) -> None:
        if self._own_client:
            self._http.close()

    def projects(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for organization in self.organizations:
            page = 1
            while True:
                response = self._http.get(
                    "/api/projects/search",
                    params={
                        "organization": organization,
                        "p": page,
                        "ps": 500,
                    },
                )
                if response.status_code in (401, 403):
                    raise RuntimeError(
                        f"sonar coverage: HTTP {response.status_code} for "
                        f"organization {organization!r}"
                    )
                response.raise_for_status()
                body = response.json()
                batch = body.get("components") or []
                result.extend(batch)
                total = int((body.get("paging") or {}).get("total") or 0)
                if page * 500 >= total or not batch:
                    break
                page += 1
        return result

    @staticmethod
    def _repo_for_project(
        project_key: str,
        *,
        org: str,
        repos_by_lower: dict[str, str],
        explicit_map: dict[str, str],
    ) -> str | None:
        explicit = explicit_map.get(project_key)
        if explicit:
            return explicit

        prefix = f"{org}_"
        candidate = (
            project_key[len(prefix) :]
            if project_key.lower().startswith(prefix.lower())
            else project_key
        )
        return repos_by_lower.get(candidate.lower())

    def covered_repo_ids(
        self,
        *,
        org: str,
        repo_names: set[str],
        explicit_map: dict[str, str],
        now: datetime | None = None,
    ) -> set[str]:
        now = now or datetime.now(UTC)
        cutoff = now - timedelta(days=30)
        repos_by_lower = {name.lower(): name for name in repo_names}
        covered: set[str] = set()
        for project in self.projects():
            key = str(project.get("key") or "")
            analyzed_raw = project.get("lastAnalysisDate")
            if not key or not analyzed_raw:
                continue
            analyzed = datetime.fromisoformat(
                str(analyzed_raw).replace("Z", "+00:00")
            )
            if analyzed < cutoff:
                continue
            repo = self._repo_for_project(
                key,
                org=org,
                repos_by_lower=repos_by_lower,
                explicit_map=explicit_map,
            )
            if repo:
                covered.add(f"repo:{org}/{repo}")
        return covered
