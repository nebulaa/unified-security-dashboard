"""Identity verification — single seam for IAP, local-dev, and bearer tokens.

Downstream RBAC code never knows which strategy produced the `Identity`. The strategy
is selected once at process startup; the application fails to boot if the dev strategy
is selected outside `ENV=local`.

Auth paths:
  - Production browser: IAP JWT (`X-Goog-IAP-JWT-Assertion`)
  - Local browser / Next.js proxy: unsigned `X-Dev-Identity` (dev backend only)
  - MCP / API clients: `Authorization: Bearer secdb_live_...` (personal API token)
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Protocol

from fastapi import HTTPException, Request, status
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.core.db import get_session_factory
from app.core.models import ApiToken
from app.core.tokens import hash_token, is_secdb_bearer_token

log = logging.getLogger("secdb.identity")

AUTH_METHOD_BEARER = "bearer"
AUTH_METHOD_IAP = "iap"
AUTH_METHOD_DEV = "dev"


class Identity(BaseModel):
    """The single identity object every downstream consumer sees.

    `email` and `groups` are the raw IAP claims (or the dev injection). Role and team
    derivation happens elsewhere (`app.core.rbac`) — keeping this model strategy-agnostic.
    Email is `str`, not `EmailStr` — IAP/dev has already produced a validated string;
    we don't add a runtime dependency on `email-validator` for this surface.
    Optional `name` comes from the IdP when available; otherwise callers derive one
    from `email` via `display_name_from_email`.
    """

    email: str
    groups: list[str] = Field(default_factory=list)
    name: str | None = None


class IdentityVerifier(Protocol):
    def verify(self, request: Request) -> Identity: ...


class _IAPVerifier:
    """Validates `X-Goog-IAP-JWT-Assertion`."""

    def __init__(self, audience: str) -> None:
        self._audience = audience
        self._http = google_requests.Request()

    def verify(self, request: Request) -> Identity:
        token = request.headers.get("X-Goog-IAP-JWT-Assertion")
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="missing IAP assertion",
            )
        try:
            claims = id_token.verify_token(
                token,
                request=self._http,
                audience=self._audience,
                certs_url="https://www.gstatic.com/iap/verify/public_key",
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"invalid IAP assertion: {exc}",
            ) from exc

        email = claims.get("email")
        if not email:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="IAP assertion missing email",
            )
        groups = claims.get("google", {}).get("groups", [])
        name = claims.get("name")
        request.state.auth_method = AUTH_METHOD_IAP
        return Identity(email=email, groups=list(groups), name=name or None)


class _DevVerifier:
    """Reads `X-Dev-Identity: {"email": "...", "google.groups": [...]}`.

    Permitted ONLY when both `IDENTITY_BACKEND=dev` and `ENV=local` (enforced in
    `build_verifier` — fails fast at boot if violated).
    """

    def verify(self, request: Request) -> Identity:
        raw = request.headers.get("X-Dev-Identity")
        if not raw:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="missing X-Dev-Identity header (dev backend)",
            )
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"X-Dev-Identity is not valid JSON: {exc}",
            ) from exc

        email = payload.get("email")
        if not email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="X-Dev-Identity missing email",
            )
        groups = payload.get("google.groups") or payload.get("groups") or []
        name = payload.get("name")
        request.state.auth_method = AUTH_METHOD_DEV
        return Identity(email=email, groups=list(groups), name=name or None)


class _BearerVerifier:
    """Validates `Authorization: Bearer secdb_live_...` against `api_tokens`."""

    def verify(self, request: Request) -> Identity:
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="missing or invalid Authorization header",
            )
        plaintext = auth[7:].strip()
        if not is_secdb_bearer_token(plaintext):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="unrecognized bearer token format",
            )

        digest = hash_token(plaintext)
        session = get_session_factory()()
        try:
            row = session.scalar(select(ApiToken).where(ApiToken.token_hash == digest))
            if row is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="invalid API token",
                )
            if row.revoked_at is not None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="API token revoked",
                )
            now = datetime.now(UTC)
            if row.expires_at is not None and row.expires_at < now:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="API token expired",
                )

            row.last_used_at = now
            session.commit()

            request.state.auth_method = AUTH_METHOD_BEARER
            return Identity(email=row.email, groups=[])
        finally:
            session.close()


class _CompositeVerifier:
    """Bearer tokens take precedence when present; otherwise fall back to IAP/dev."""

    def __init__(self, fallback: IdentityVerifier) -> None:
        self._fallback = fallback
        self._bearer = _BearerVerifier()

    def verify(self, request: Request) -> Identity:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:].strip()
            if is_secdb_bearer_token(token):
                return self._bearer.verify(request)
        return self._fallback.verify(request)


class IdentityBackendMisconfiguredError(RuntimeError):
    """Raised at boot when the selected backend is not legal for the current environment."""


def build_verifier(settings: Settings | None = None) -> IdentityVerifier:
    """Resolve the verifier once at process startup.

    : the dev strategy is permitted only when `ENV=local`. Any other
    environment with `IDENTITY_BACKEND=dev` raises immediately so the misconfiguration
    is caught at boot, not at first request.
    """
    s = settings or get_settings()

    if s.identity_backend == "dev":
        if s.env != "local":
            raise IdentityBackendMisconfiguredError(
                f"IDENTITY_BACKEND=dev is only permitted when ENV=local; got ENV={s.env}"
            )
        fallback: IdentityVerifier = _DevVerifier()
    elif s.identity_backend == "iap":
        if not s.iap_audience:
            raise IdentityBackendMisconfiguredError(
                "IDENTITY_BACKEND=iap requires IAP_AUDIENCE to be set"
            )
        fallback = _IAPVerifier(audience=s.iap_audience)
    else:
        raise IdentityBackendMisconfiguredError(f"unknown IDENTITY_BACKEND: {s.identity_backend}")

    return _CompositeVerifier(fallback)


_verifier: IdentityVerifier | None = None


def get_verifier() -> IdentityVerifier:
    global _verifier
    if _verifier is None:
        _verifier = build_verifier()
    return _verifier


def reset_verifier_for_tests() -> None:
    global _verifier
    _verifier = None


def verify_identity(request: Request) -> Identity:
    """FastAPI dependency. Use `Depends(verify_identity)` on every protected route."""
    return get_verifier().verify(request)


def require_browser_session(request: Request) -> None:
    """Reject bearer-authenticated calls (e.g. token mint/revoke must use IAP/dev)."""
    if getattr(request.state, "auth_method", None) == AUTH_METHOD_BEARER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API tokens cannot manage tokens; use the dashboard in your browser",
        )
