"""Derive a human-readable display name from an email address."""

from __future__ import annotations


def display_name_from_email(email: str) -> str:
    """Format the local part of an email as a display name (e.g. jane.doe → Jane Doe)."""
    local = email.split("@", 1)[0].strip()
    if not local:
        return email
    parts = local.replace(".", " ").replace("_", " ").split()
    if not parts:
        return email
    return " ".join(part.capitalize() for part in parts)
