"""Process-wide settings.

Resolved once at process startup. Adapter selections (`raw_store`, `ingest_transport`,
`secret_backend`, `config_store`, `identity_backend`) drive which concrete adapter the
factory returns; downstream code never branches on them.

Boot invariant: the application fails to boot if `identity_backend == "dev"` is
selected outside `env == "local"`. Enforced in `app.core.identity.build_verifier`.

Path resolution: `.env.local` / `.env` and any relative `*_fs_root` paths are resolved
against the repo root (located by walking up from CWD looking for a marker file). This
means the same commands work whether invoked from the repo root, `backend/`, or
anywhere else.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

REPO_ROOT_MARKERS = (".git", "pyproject.toml", "docker-compose.yml")


@lru_cache(maxsize=1)
def find_repo_root(start: Path | None = None) -> Path:
    """Walk up from `start` (or CWD) looking for a marker that identifies the repo root.

    Falls back to CWD if no marker is found, so behaviour is at worst the legacy CWD-
    relative behaviour. The `docker-compose.yml` marker pins the actual project root
    (the only repo root that contains it).
    """
    here = (start or Path.cwd()).resolve()
    for parent in (here, *here.parents):
        if (parent / "docker-compose.yml").exists():
            return parent
    for parent in (here, *here.parents):
        if any((parent / m).exists() for m in REPO_ROOT_MARKERS):
            return parent
    return here


def _env_files() -> tuple[str, ...]:
    root = find_repo_root()
    return (str(root / ".env.local"), str(root / ".env"))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_env_files(),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    env: Literal["local", "dev", "staging", "prod"] = "local"

    identity_backend: Literal["iap", "dev"] = "dev"
    raw_store: Literal["fs", "gcs"] = "fs"
    ingest_transport: Literal["http", "pubsub"] = "http"
    secret_backend: Literal["env", "gsm"] = "env"
    config_store: Literal["fs", "gcs"] = "fs"

    raw_store_fs_root: str = "./var/raw"
    config_store_fs_root: str = "./config"

    database_url: str = "postgresql+psycopg://secdb:secdb@localhost:5432/secdb"

    normalizer_url: str = "http://localhost:8001"

    github_org: str = ""
    dependabot_pat: str = ""

    # SonarCloud organization keys to poll. These often differ from the GitHub
    # organization because SonarCloud keys are lowercase. Accepts a comma-separated
    # string from `SONAR_ORG` or `SONAR_ORGS`.
    # `NoDecode` skips pydantic-settings' built-in complex-type parser (which
    # would try to JSON-decode `exampleorg,exampledivision` and fail). Our
    # `_split_sonar_orgs` validator handles the CSV form instead.
    sonar_orgs: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        validation_alias=AliasChoices("SONAR_ORGS", "SONAR_ORG"),
    )
    sonar_token: str = ""
    sonar_base_url: str = "https://sonarcloud.io"

    iap_audience: str | None = None

    # Public URL of the hosted MCP server (streamable-http). Surfaced on /settings/mcp
    # so setup snippets are copy-pasteable without hardcoding.
    mcp_server_url: str = "http://localhost:3001/mcp"

    gcs_raw_bucket: str | None = None
    gcs_config_bucket: str | None = None

    pubsub_project: str | None = None
    pubsub_ingest_topic: str = "secdb-ingest-raw"

    # GCP region + Cloud Run Job names (admin poller trigger in prod).
    gcp_region: str | None = None
    poller_job_dependabot: str = "secdb-poller-dependabot"
    poller_job_sonarcloud: str = "secdb-poller-sonarcloud"
    poller_job_wiz: str = "secdb-poller-wiz"
    poller_job_jira_pentest: str = "secdb-poller-jira-pentest"

    jira_base_url: str = Field(
        default="",
        validation_alias=AliasChoices("JIRA_BASE_URL"),
    )
    jira_api_email: str = Field(
        default="",
        validation_alias=AliasChoices("JIRA_API_EMAIL"),
    )

    wiz_auth_url: str = Field(
        default="https://auth.app.wiz.io/oauth/token",
        validation_alias=AliasChoices("WIZ_AUTH_URL", "WIZ_AUTH_ENDPOINT"),
    )
    wiz_api_url: str = Field(
        default="",
        validation_alias=AliasChoices("WIZ_API_URL", "WIZ_API_ENDPOINT"),
    )
    wiz_oauth_audience: str = "wiz-api"
    wiz_backfill_days: int = 90
    wiz_threat_center_days: int = 30
    wiz_portal_base_url: str = Field(
        default="https://app.wiz.io",
        validation_alias=AliasChoices("WIZ_PORTAL_BASE_URL", "WIZ_PORTAL_URL"),
        description=(
            "Wiz web UI base URL for finding deep links. "
            "Distinct from WIZ_API_URL (regional GraphQL endpoint)."
        ),
    )
    rollup_job: str = "secdb-rollup"
    ownership_reresolve_job: str = "secdb-ownership-reresolve"

    # Slack incoming webhook for DLQ / ingest failure alerts (optional).
    slack_webhook_url: str = ""

    # OIDC audience for Pub/Sub push to /internal/* (normalizer + API). Set to the
    # Cloud Run service URL in prod via Terraform; local dev leaves it unset.
    oidc_audience: str | None = None

    auto_close_config_path: str = "./config/auto_close.yaml"
    sla_config_path: str = "./config/sla.yaml"

    # Latest cloud security coverage snapshot (written by `app.coverage.collect`).
    coverage_snapshot_path: str = "./var/coverage/latest.json"

    log_level: str = "INFO"

    namespace_secdb: str = Field(
        default="c0ffee00-cafe-babe-dead-beef00000001",
        description="Fixed namespace UUID for uuid5(source:native_id).",
    )

    @field_validator("sonar_orgs", mode="before")
    @classmethod
    def _split_sonar_orgs(cls, v: object) -> list[str] | object:
        """Allow `SONAR_ORG=exampleorg,exampledivision` to populate the list setting.

        pydantic-settings doesn't natively split CSV strings into list[str] — it
        either requires JSON (e.g. `["exampleorg", "exampledivision"]`) or a custom
        parser. CSV is what every operator types into a .env, so we accept it
        here and normalise to a deduplicated list (preserving insertion order,
        which controls poll order downstream).
        """
        if isinstance(v, str):
            seen: set[str] = set()
            out: list[str] = []
            for chunk in v.split(","):
                org = chunk.strip()
                if not org or org in seen:
                    continue
                seen.add(org)
                out.append(org)
            return out
        return v

    @model_validator(mode="after")
    def _resolve_relative_paths(self) -> Settings:
        """Resolve any `./...` paths against the repo root (not CWD).

        Without this, `python -m app.migrate` from `backend/` would look for
        `backend/config/` instead of `<repo>/config/`. Absolute paths and `gs://`
        URIs are passed through untouched.
        """
        root = find_repo_root()
        for attr in (
            "raw_store_fs_root",
            "config_store_fs_root",
            "auto_close_config_path",
            "sla_config_path",
            "coverage_snapshot_path",
        ):
            value = getattr(self, attr)
            if value and value.startswith("./"):
                object.__setattr__(self, attr, str((root / value[2:]).resolve()))
        return self


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings_for_tests() -> None:
    global _settings
    _settings = None
