"""Snapshot persistence — JSON on disk for the prototype.

The collector writes; the API reads. Keeping the two apart behind a file means a
failed collection cannot take the dashboard down: the previous snapshot stays
readable and simply ages into `stale`.

Graduating this to Postgres (a `coverage_snapshots` table keyed by day) is a
storage swap behind `load_latest` / `write`, not a change to the computation.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

from app.core.config import get_settings
from app.coverage.model import CoverageSnapshot, HistoryPoint, InventoryItem

SCHEMA_VERSION = 1


class SnapshotNotFoundError(RuntimeError):
    """No coverage snapshot has been collected yet."""


def snapshot_path() -> Path:
    return Path(get_settings().coverage_snapshot_path)


def _parse_as_of(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def to_dict(snapshot: CoverageSnapshot) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "as_of": snapshot.as_of.isoformat(),
        "collection_mode": snapshot.collection_mode,
        "degraded_sources": list(snapshot.degraded_sources),
        "items": [
            {
                "item_type": item.item_type,
                "item_id": item.item_id,
                "display": item.display,
                "in_scope": item.in_scope,
                "projects": list(item.projects),
                "signals": sorted(item.signals),
            }
            for item in snapshot.items
        ],
        "history": [
            {"day": point.day.isoformat(), "pct": point.pct} for point in snapshot.history
        ],
    }


def from_dict(raw: dict) -> CoverageSnapshot:
    version = raw.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ValueError(
            f"coverage snapshot schema {version!r} unsupported (expected {SCHEMA_VERSION}); "
            "re-run the collector"
        )
    return CoverageSnapshot(
        as_of=_parse_as_of(raw["as_of"]),
        items=tuple(
            InventoryItem(
                item_type=item["item_type"],
                item_id=item["item_id"],
                display=item.get("display", item["item_id"]),
                in_scope=bool(item.get("in_scope", False)),
                projects=tuple(item.get("projects") or ()),
                signals=frozenset(item.get("signals") or ()),
            )
            for item in raw.get("items") or []
        ),
        history=tuple(
            HistoryPoint(
                day=date.fromisoformat(point["day"]),
                pct={k: float(v) for k, v in (point.get("pct") or {}).items()},
            )
            for point in raw.get("history") or []
        ),
        collection_mode=str(raw.get("collection_mode") or "sample"),
        degraded_sources=tuple(raw.get("degraded_sources") or ()),
    )


def write(snapshot: CoverageSnapshot, path: Path | None = None) -> Path:
    target = path or snapshot_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(to_dict(snapshot), indent=2), encoding="utf-8")
    return target


def load_latest(path: Path | None = None) -> CoverageSnapshot:
    source = path or snapshot_path()
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SnapshotNotFoundError(
            f"no coverage snapshot at {source} — run `make coverage-sample` locally "
            "or the collector job in cloud"
        ) from None
    return from_dict(raw)
