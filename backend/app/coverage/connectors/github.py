"""GitHub-org inventory and Dependabot-settings connector."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.coverage.config import CoverageConfig
from app.coverage.model import InventoryItem
from app.coverage.spec import ITEM_REPO

API = "https://api.github.com"
API_VERSION = "2022-11-28"


class GitHubConnector:
    def __init__(
        self,
        *,
        org: str,
        token: str,
        client: httpx.Client | None = None,
        workers: int = 12,
    ) -> None:
        self.org = org
        self._own_client = client is None
        self._http = client or httpx.Client(
            base_url=API,
            timeout=45,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": API_VERSION,
                "User-Agent": "secdb-coverage/0.1",
            },
        )
        self._workers = workers

    def close(self) -> None:
        if self._own_client:
            self._http.close()

    def _get(self, path: str, **kwargs: Any) -> httpx.Response:
        response = self._http.get(path, **kwargs)
        if response.status_code in (401, 403):
            raise RuntimeError(
                f"github coverage: HTTP {response.status_code} for {path}; "
                "token needs repo, read:org and repository security-settings access"
            )
        return response

    def list_repositories(self) -> list[dict[str, Any]]:
        repos: list[dict[str, Any]] = []
        page = 1
        while True:
            response = self._get(
                f"/orgs/{self.org}/repos",
                params={"type": "all", "per_page": 100, "page": page},
            )
            response.raise_for_status()
            batch = response.json()
            if not batch:
                return repos
            repos.extend(batch)
            if len(batch) < 100:
                return repos
            page += 1

    def _security_signals(self, repo_name: str) -> frozenset[str]:
        base = f"/repos/{self.org}/{repo_name}"
        alerts = self._get(f"{base}/vulnerability-alerts")
        alerts_enabled = alerts.status_code == 204
        if alerts.status_code not in (204, 404):
            alerts.raise_for_status()

        dependabot_yml = self._get(f"{base}/contents/.github/dependabot.yml")
        version_updates = dependabot_yml.status_code == 200
        if dependabot_yml.status_code not in (200, 404):
            dependabot_yml.raise_for_status()

        signals: set[str] = set()
        if alerts_enabled:
            signals.add("dependabot_enabled")
        if version_updates:
            signals.add("dependabot_version_updates")
        return frozenset(signals)

    @staticmethod
    def _projects(config: CoverageConfig, topics: set[str]) -> tuple[str, ...]:
        return tuple(
            project.key
            for project in config.projects
            if set(project.code_topics).issubset(topics)
            and not set(project.exclude_code_topics).intersection(topics)
        )

    def collect(
        self, config: CoverageConfig, *, now: datetime | None = None
    ) -> tuple[InventoryItem, ...]:
        now = now or datetime.now(UTC)
        cutoff = now - timedelta(days=config.inventory.repo_pushed_within_days)
        repositories = self.list_repositories()
        eligible: list[dict[str, Any]] = []
        out_of_scope: list[InventoryItem] = []

        for repo in repositories:
            name = str(repo["name"])
            pushed_raw = repo.get("pushed_at")
            pushed = (
                datetime.fromisoformat(str(pushed_raw).replace("Z", "+00:00"))
                if pushed_raw
                else None
            )
            in_scope = (
                not bool(repo.get("archived"))
                and not bool(repo.get("fork"))
                and pushed is not None
                and pushed >= cutoff
            )
            topics = {str(v).lower() for v in (repo.get("topics") or [])}
            if in_scope:
                eligible.append({"name": name, "topics": topics})
            else:
                out_of_scope.append(
                    InventoryItem(
                        item_type=ITEM_REPO,
                        item_id=f"repo:{self.org}/{name}",
                        display=name,
                        in_scope=False,
                    )
                )

        with ThreadPoolExecutor(max_workers=self._workers) as pool:
            signals = list(
                pool.map(
                    self._security_signals,
                    [str(repo["name"]) for repo in eligible],
                )
            )

        in_scope = [
            InventoryItem(
                item_type=ITEM_REPO,
                item_id=f"repo:{self.org}/{repo['name']}",
                display=str(repo["name"]),
                in_scope=True,
                projects=self._projects(config, repo["topics"]),
                signals=repo_signals,
            )
            for repo, repo_signals in zip(eligible, signals, strict=True)
        ]
        return tuple(in_scope + out_of_scope)
