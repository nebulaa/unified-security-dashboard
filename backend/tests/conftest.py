"""Test fixtures.

Tests run against the local Postgres started by `docker-compose up -d postgres`.
A dedicated test database `secdb_test` is created on first run; each test truncates
all `findings*` / `processed_payloads` rows before running.

We don't try to spin up a Postgres per test — the migration cost would dominate.
Tests are insulated by truncation, not by transaction rollback, because the processor
itself runs inside a transaction and rolls back on error.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[2]
ADMIN_URL = "postgresql+psycopg://secdb:secdb@localhost:5432/secdb"
TEST_DB_NAME = "secdb_test"
TEST_URL = ADMIN_URL.rsplit("/", 1)[0] + f"/{TEST_DB_NAME}"


def _ensure_test_db() -> None:
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": TEST_DB_NAME}
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    admin.dispose()


def _migrate_test_db() -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(REPO_ROOT / "backend" / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "backend" / "migrations"))
    cfg.set_main_option("sqlalchemy.url", TEST_URL)
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session", autouse=True)
def _bootstrap_test_db() -> None:
    _ensure_test_db()
    os.environ["DATABASE_URL"] = TEST_URL
    os.environ["ENV"] = "local"
    os.environ["IDENTITY_BACKEND"] = "dev"
    # `_fixtures/config/component_registry.yaml` is a minimal test map (not a copy
    # of repo-root `config/component_registry.yaml`).
    os.environ["CONFIG_STORE_FS_ROOT"] = str(Path(__file__).parent / "_fixtures" / "config")
    os.environ["RAW_STORE_FS_ROOT"] = str(REPO_ROOT / "var" / "raw_test")
    # Neutralise Slack across the entire test session — `.env.local` carries
    # a real webhook for dev workflows, and any test that exercises the
    # `/internal/dlq` handler (e.g. `test_admin_dlq_list_and_resolve`) without
    # mocking `notify_dlq_ingest_failure` would otherwise post to the real
    # channel. Empty env var takes precedence over `.env.local` in
    # pydantic-settings, so `resolve_slack_webhook_url()` returns None for
    # the whole suite regardless of which endpoint a test hits.
    os.environ["SLACK_WEBHOOK_URL"] = ""

    from app.core.config import reset_settings_for_tests
    from app.core.config_store import reset_config_cache_for_tests
    from app.core.db import reset_db_for_tests
    from app.core.jira_pentest import reset_jira_pentest_cache_for_tests
    from app.core.policy import reset_policy_cache_for_tests

    reset_settings_for_tests()
    reset_db_for_tests()
    reset_config_cache_for_tests()
    reset_policy_cache_for_tests()
    reset_jira_pentest_cache_for_tests()

    _migrate_test_db()


@pytest.fixture()
def session() -> Iterator[Session]:
    engine = create_engine(TEST_URL, future=True)
    session_local = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE finding_events, processed_payloads, findings, "
                "role_overrides, api_tokens, dlq_events, daily_metrics, "
                "audit RESTART IDENTITY CASCADE"
            )
        )

    s = session_local()
    try:
        yield s
        s.commit()
    finally:
        s.close()
        engine.dispose()
