"""Ownership re-resolution job.

Usage:
    python -m app.jobs.ownership_reresolve
    python -m app.jobs.ownership_reresolve --dry-run
    python -m app.jobs.ownership_reresolve --status
"""

from __future__ import annotations

import argparse
import logging

from app.core.config_store import get_config_cache
from app.core.db import session_scope
from app.internal.ownership_reresolve import (
    core_reresolve,
    maybe_trigger_rollup_backfill,
    print_status,
)

log = logging.getLogger("secdb.ownership_reresolve")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Re-resolve Finding.owner_team from ownership.yaml")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute transitions without writing",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print owner_team distribution and recent ownership_changed events",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        metavar="N",
        help="Findings per fetch batch (default 500)",
    )
    parser.add_argument(
        "--skip-rollup",
        action="store_true",
        help="Do not chain 30d daily_metrics backfill after updates",
    )
    args = parser.parse_args()

    if args.status:
        with session_scope() as session:
            print_status(session)
        return

    ownership = get_config_cache().get_ownership()
    with session_scope() as session:
        result = core_reresolve(
            session,
            ownership,
            actor="system:ownership_reresolve",
            batch_size=args.batch_size,
            dry_run=args.dry_run,
        )

    if not args.dry_run and not args.skip_rollup:
        maybe_trigger_rollup_backfill(result.updated, async_mode=False)

    log.info(
        "ownership_reresolve.complete scanned=%d updated=%d",
        result.scanned,
        result.updated,
    )


if __name__ == "__main__":
    main()
