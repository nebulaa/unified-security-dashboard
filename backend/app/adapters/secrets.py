"""Secret backend adapter — env (local) or Google Secret Manager (prod).

Selected by `SECRET_BACKEND`. The env adapter pulls the raw value from a process
environment variable; the gsm adapter resolves a `gsm://project/secret/version`-style
ref. Either way the caller asks for `secrets.get(SecretRef.dependabot_pat())` and gets
back a plain string — the rest of the codebase doesn't care which backend produced it.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.core.config import Settings, get_settings


@dataclass(frozen=True)
class SecretRef:
    """A logical reference. Each backend resolves it differently.

    `env_var` is the environment variable used by the `env` backend.
    `gsm_resource` is the `projects/{p}/secrets/{name}/versions/latest` used by `gsm`.
    """

    env_var: str
    gsm_resource: str

    @classmethod
    def dependabot_pat(cls) -> SecretRef:
        return cls(env_var="DEPENDABOT_PAT", gsm_resource="secdb-dependabot-pat")

    @classmethod
    def sonarcloud_token(cls) -> SecretRef:
        return cls(env_var="SONAR_TOKEN", gsm_resource="secdb-sonar-token")

    @classmethod
    def slack_webhook(cls) -> SecretRef:
        return cls(env_var="SLACK_WEBHOOK_URL", gsm_resource="secdb-slack-webhook")

    @classmethod
    def wiz_client_id(cls) -> SecretRef:
        return cls(env_var="WIZ_CLIENT_ID", gsm_resource="secdb-wiz-client-id")

    @classmethod
    def wiz_client_secret(cls) -> SecretRef:
        return cls(env_var="WIZ_CLIENT_SECRET", gsm_resource="secdb-wiz-client-secret")

    @classmethod
    def jira_api_token(cls) -> SecretRef:
        return cls(env_var="JIRA_API_TOKEN", gsm_resource="secdb-jira-api-token")


class SecretBackend(ABC):
    @abstractmethod
    def get(self, ref: SecretRef) -> str: ...


class _EnvSecrets(SecretBackend):
    def get(self, ref: SecretRef) -> str:
        value = os.environ.get(ref.env_var)
        if not value:
            raise RuntimeError(f"secret not set in env: {ref.env_var}")
        return value


class _GsmSecrets(SecretBackend):
    def __init__(self, project: str) -> None:
        from google.cloud import secretmanager

        self._client = secretmanager.SecretManagerServiceClient()
        self._project = project

    def get(self, ref: SecretRef) -> str:
        name = f"projects/{self._project}/secrets/{ref.gsm_resource}/versions/latest"
        response = self._client.access_secret_version(name=name)
        return response.payload.data.decode("utf-8")


def build_secret_backend(settings: Settings | None = None) -> SecretBackend:
    s = settings or get_settings()
    if s.secret_backend == "env":
        return _EnvSecrets()
    if s.secret_backend == "gsm":
        if not s.pubsub_project:
            raise RuntimeError("SECRET_BACKEND=gsm requires PUBSUB_PROJECT (used as GCP project id)")
        return _GsmSecrets(project=s.pubsub_project)
    raise RuntimeError(f"unknown SECRET_BACKEND: {s.secret_backend}")
