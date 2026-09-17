"""FastAPI dependency wiring — identity → DB session → user context.

Authorization collapsed to a single `is_admin` flag (see `app.core.rbac`);
there is no `X-Active-Role` header or active-role plumbing any more.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.db import get_session_factory
from app.core.identity import Identity, verify_identity
from app.core.rbac import UserContext, build_user_context


def db_session() -> Iterator[Session]:
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def current_identity(request: Request) -> Identity:
    return verify_identity(request)


def current_user(
    identity: Annotated[Identity, Depends(current_identity)],
    session: Annotated[Session, Depends(db_session)],
) -> UserContext:
    return build_user_context(identity, session)
