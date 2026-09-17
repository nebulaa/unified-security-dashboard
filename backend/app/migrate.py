"""`secdb-migrate` entrypoint (D25).

Locally: `python -m app.migrate upgrade head` or `secdb-migrate upgrade head`.
In GCP: same module runs as a Cloud Run Job; the API and normalizer have DML-only
DB grants so they cannot run DDL (D25).
"""

from __future__ import annotations

import sys
from pathlib import Path

from alembic import command
from alembic.config import Config


def _alembic_config() -> Config:
    cfg = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parent.parent / "migrations"))
    return cfg


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        args = ["upgrade", "head"]

    cfg = _alembic_config()
    op = args[0]

    if op == "upgrade":
        target = args[1] if len(args) > 1 else "head"
        command.upgrade(cfg, target)
    elif op == "downgrade":
        target = args[1] if len(args) > 1 else "-1"
        command.downgrade(cfg, target)
    elif op == "current":
        command.current(cfg)
    elif op == "history":
        command.history(cfg)
    elif op == "revision":
        message = args[args.index("-m") + 1] if "-m" in args else "auto"
        command.revision(cfg, message=message, autogenerate="--autogenerate" in args)
    else:
        print(f"Unknown command: {op}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
