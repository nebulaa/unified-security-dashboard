"""Display name helpers."""

from __future__ import annotations

from app.core.display_name import display_name_from_email


def test_display_name_from_email_formats_local_part() -> None:
    assert display_name_from_email("jane.doe@example.com") == "Jane Doe"
    assert display_name_from_email("john_smith@example.com") == "John Smith"
