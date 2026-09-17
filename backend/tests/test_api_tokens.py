"""API tests for /me/tokens and bearer authentication.

Tokens no longer carry an `active_role`; bearer requests inherit the
owner's per-email admin status at verify time.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.main import create_app
from app.core.models import ApiToken
from app.core.tokens import generate_token


@pytest.fixture()
def client(session) -> TestClient:
    return TestClient(create_app())


def _hdr(email: str = "dev1@example.com", groups: list[str] | None = None) -> dict[str, str]:
    return {
        "X-Dev-Identity": json.dumps(
            {"email": email, "google.groups": groups or ["engineering@example.com"]}
        )
    }


def _bearer(plaintext: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {plaintext}"}


def test_create_list_revoke_token(client, session) -> None:
    r = client.post("/me/tokens", headers=_hdr(), json={"label": "laptop"})
    assert r.status_code == 201
    body = r.json()
    assert body["token"].startswith("secdb_live_")
    assert body["label"] == "laptop"
    token_id = body["id"]
    plaintext = body["token"]

    r2 = client.get("/me/tokens", headers=_hdr())
    assert r2.status_code == 200
    items = r2.json()["items"]
    assert len(items) == 1
    assert "token" not in items[0]

    r3 = client.delete(f"/me/tokens/{token_id}", headers=_hdr())
    assert r3.status_code == 204

    r4 = client.get("/findings", headers=_bearer(plaintext))
    assert r4.status_code == 401


def test_max_five_tokens(client, session) -> None:
    for i in range(5):
        r = client.post("/me/tokens", headers=_hdr(), json={"label": f"t{i}"})
        assert r.status_code == 201
    r6 = client.post("/me/tokens", headers=_hdr(), json={})
    assert r6.status_code == 409


def test_bearer_cannot_mint_tokens(client, session) -> None:
    create = client.post("/me/tokens", headers=_hdr(), json={})
    plaintext = create.json()["token"]
    r = client.post("/me/tokens", headers=_bearer(plaintext), json={})
    assert r.status_code == 403


def test_bearer_inherits_owner_email(client, session) -> None:
    """A token's bearer requests run with the owner's identity. Pinning by
    asking for an admin-only source via the bearer of a non-admin owner —
    the owner can't see Trivy-in-Sonar, so the bearer can't either (403)."""
    create = client.post("/me/tokens", headers=_hdr(), json={})
    plaintext = create.json()["token"]

    r = client.get("/findings?source=sonarcloud_trivy", headers=_bearer(plaintext))
    assert r.status_code == 403


def test_bearer_for_admin_email_can_opt_into_admin_only_sources(client, session) -> None:
    """A token minted by an admin inherits that admin status at verify time —
    so the bearer succeeds at the admin-only-source opt-in. If the owner is
    later removed from `admin_emails`, the same token starts failing on its
    next request without any DB write."""
    create = client.post("/me/tokens", headers=_hdr("admin1@example.com"), json={})
    plaintext = create.json()["token"]

    r = client.get("/findings?source=sonarcloud_trivy", headers=_bearer(plaintext))
    assert r.status_code == 200


def test_expired_token_rejected(client, session) -> None:
    plaintext, digest, prefix = generate_token(test=True)
    row = ApiToken(
        email="dev1@example.com",
        token_hash=digest,
        prefix=prefix,
        active_role="member",
        expires_at=datetime.now(UTC) - timedelta(hours=1),
        created_at=datetime.now(UTC),
    )
    session.add(row)
    session.commit()

    r = client.get("/findings", headers=_bearer(plaintext))
    assert r.status_code == 401


def test_revoked_token_rejected(client, session) -> None:
    plaintext, digest, prefix = generate_token(test=True)
    row = ApiToken(
        email="dev1@example.com",
        token_hash=digest,
        prefix=prefix,
        active_role="member",
        revoked_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )
    session.add(row)
    session.commit()

    r = client.get("/findings", headers=_bearer(plaintext))
    assert r.status_code == 401


def test_delete_other_users_token_404(client, session) -> None:
    create = client.post("/me/tokens", headers=_hdr(), json={})
    token_id = create.json()["id"]
    r = client.delete(f"/me/tokens/{token_id}", headers=_hdr("nobody@example.com"))
    assert r.status_code == 404


def test_token_audit_logs_do_not_500_at_info_level(client, session, caplog) -> None:
    """`secdb.tokens` audit logs must use stdlib-compatible formatting.

    Pytest defaults the root logger to WARNING, so `log.info(...)` short-
    circuits via `isEnabledFor(INFO)` and any bad kwargs never reach
    `Logger._log`. In dev/prod uvicorn runs at INFO, so a misuse of structlog-
    style kwargs against the stdlib logger raises
    `TypeError: Logger._log() got an unexpected keyword argument ...` and
    turns POST/DELETE on /me/tokens into a 500. Pin the level here so the
    regression is caught in CI — if the calls were unsafe, the requests
    below would return 500 instead of 201/204.
    """
    caplog.set_level(logging.INFO, logger="secdb.tokens")

    create = client.post("/me/tokens", headers=_hdr(), json={"label": "audit-log"})
    assert create.status_code == 201, create.text
    token_id = create.json()["id"]

    revoke = client.delete(f"/me/tokens/{token_id}", headers=_hdr())
    assert revoke.status_code == 204, revoke.text


def test_bearer_updates_last_used_at(client, session) -> None:
    plaintext, digest, prefix = generate_token(test=True)
    row = ApiToken(
        email="dev1@example.com",
        token_hash=digest,
        prefix=prefix,
        active_role="member",
        created_at=datetime.now(UTC),
    )
    session.add(row)
    session.commit()

    client.get("/scanners/health", headers=_bearer(plaintext))
    session.expire_all()
    updated = session.scalar(select(ApiToken).where(ApiToken.token_hash == digest))
    assert updated is not None
    assert updated.last_used_at is not None
