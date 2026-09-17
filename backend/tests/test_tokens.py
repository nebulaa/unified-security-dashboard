"""Unit tests for personal API token primitives."""

from __future__ import annotations

from app.core.tokens import (
    TOKEN_PREFIX,
    generate_token,
    hash_token,
    is_secdb_bearer_token,
)


def test_generate_token_unique_and_hashable() -> None:
    p1, h1, prefix1 = generate_token()
    p2, h2, prefix2 = generate_token()
    assert p1 != p2
    assert h1 != h2
    assert p1.startswith(TOKEN_PREFIX)
    assert hash_token(p1) == h1
    assert prefix1 == p1[:12]


def test_is_secdb_bearer_token() -> None:
    plain, _, _ = generate_token()
    assert is_secdb_bearer_token(plain)
    assert not is_secdb_bearer_token("Bearer something")
    assert not is_secdb_bearer_token("not-a-secdb-token")
