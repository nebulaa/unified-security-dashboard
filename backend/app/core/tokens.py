"""Personal API token generation and hashing.

Tokens are high-entropy random strings (GitHub PAT model), not user-chosen
passwords — SHA-256 + indexed lookup is sufficient; bcrypt is unnecessary.
"""

from __future__ import annotations

import hashlib
import secrets

TOKEN_PREFIX = "secdb_live_"
TOKEN_PREFIX_TEST = "secdb_test_"
PREFIX_DISPLAY_LEN = 12


def generate_token(*, test: bool = False) -> tuple[str, str, str]:
    """Return (plaintext, sha256_hex, display_prefix).

    Plaintext is shown to the user exactly once at issue time.
    """
    prefix = TOKEN_PREFIX_TEST if test else TOKEN_PREFIX
    raw = secrets.token_urlsafe(32)
    plaintext = f"{prefix}{raw}"
    digest = hash_token(plaintext)
    display = plaintext[:PREFIX_DISPLAY_LEN]
    return plaintext, digest, display


def hash_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def is_secdb_bearer_token(value: str) -> bool:
    """True when `value` is the token portion after 'Bearer '."""
    return value.startswith(TOKEN_PREFIX) or value.startswith(TOKEN_PREFIX_TEST)
