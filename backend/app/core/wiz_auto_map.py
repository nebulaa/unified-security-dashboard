"""Wiz Service Catalog → component_registry auto-mapping (plans/wiz_auto_map.plan.md)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.models import Finding
from app.core.wiz_catalog import WizCatalogService

Confidence = Literal["high", "medium", "low"]

@dataclass(frozen=True)
class RegistryComponent:
    key: str
    label: str
    repo: str | None
    teams: tuple[str, ...]
    dev_pillar: str | None
    wiz_service: str | None

    @property
    def primary_team(self) -> str:
        return self.teams[0] if self.teams else "unowned"


@dataclass(frozen=True)
class MatchSuggestion:
    wiz_service: str
    component_key: str
    team: str
    confidence: Confidence
    matcher: str
    finding_count: int = 0
    score: float = 0.0
    project_hint: str | None = None


@dataclass
class SuggestReport:
    suggestions: list[MatchSuggestion] = field(default_factory=list)
    already_mapped: list[tuple[str, str]] = field(default_factory=list)  # slug, key
    unmapped_catalog: list[str] = field(default_factory=list)
    unmapped_findings_only: list[tuple[str, int]] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)


def normalize_slug(value: str) -> str:
    """Normalize an upstream display name without tenant-specific rewriting."""
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _component_aliases(comp: RegistryComponent) -> set[str]:
    aliases: set[str] = {normalize_slug(comp.key), normalize_slug(comp.label)}
    if comp.repo:
        aliases.add(normalize_slug(comp.repo))
    if comp.wiz_service:
        aliases.add(normalize_slug(comp.wiz_service))
    return {a for a in aliases if a}


def _token_set(value: str) -> set[str]:
    return {t for t in re.split(r"[-_]+", value.lower()) if len(t) > 2}


_GENERIC_LABEL_TOKENS = frozenset(
    {
        "stack",
        "service",
        "api",
        "core",
        "agent",
        "operator",
        "server",
        "ui",
        "gateway",
        "manager",
        "worker",
        "frontend",
        "backend",
        "deployment",
        "collector",
        "metrics",
        "prometheus",
        "internal",
        "external",
    }
)


def _suggestion_priority(suggestion: MatchSuggestion) -> float:
    return suggestion.finding_count * 100.0 + suggestion.score


def load_registry_components(config_dir: Path) -> list[RegistryComponent]:
    path = config_dir / "component_registry.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: list[RegistryComponent] = []
    for item in raw.get("components") or []:
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        teams = tuple(str(t) for t in (item.get("teams") or []))
        out.append(
            RegistryComponent(
                key=key,
                label=str(item.get("label") or key),
                repo=str(item.get("repo") or "").strip() or None,
                teams=teams,
                dev_pillar=str(item.get("dev_pillar") or "").strip() or None,
                wiz_service=str(item.get("wiz_service") or "").strip() or None,
            )
        )
    return out


def load_overrides(config_dir: Path) -> dict[str, str]:
    """Map Wiz displayName → registry component key."""
    path = config_dir / "wiz_service_overrides.yaml"
    if not path.is_file():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    overrides = raw.get("overrides") or raw
    if not isinstance(overrides, dict):
        return {}
    return {str(k): str(v) for k, v in overrides.items()}


def wiz_finding_counts(session: Session) -> dict[str, int]:
    """Count open Wiz findings by wizservice slug (asset_id prefix)."""
    rows = session.execute(
        select(Finding.asset_id, func.count())
        .where(Finding.source == "wiz")
        .group_by(Finding.asset_id)
    ).all()
    counts: dict[str, int] = {}
    for asset_id, n in rows:
        aid = str(asset_id)
        if aid.startswith("wizservice:"):
            slug = aid.removeprefix("wizservice:")
            counts[slug] = counts.get(slug, 0) + int(n)
    return counts


def _score_candidate(
    norm_slug: str,
    comp: RegistryComponent,
) -> tuple[float, str]:
    aliases = _component_aliases(comp)
    if norm_slug in aliases:
        return 1.0, "exact_normalized"
    for alias in aliases:
        if len(alias) < 5:
            continue
        if norm_slug in alias or alias in norm_slug:
            return 0.92, "substring"
    if comp.repo:
        repo_norm = normalize_slug(comp.repo)
        slug_parts = norm_slug.split("-")
        if len(repo_norm) >= 5 and (
            norm_slug == repo_norm
            or norm_slug.endswith(repo_norm)
            or repo_norm in slug_parts
        ):
            return 0.95, "repo_norm"
        repo_tail = comp.repo
        slug_compact = norm_slug.replace("-", "")
        repo_compact = repo_tail.replace("-", "")
        if len(repo_compact) >= 8 and repo_compact in slug_compact:
            return 0.9, "repo_stem"
    key_stem = comp.key.lower()
    if len(key_stem) >= 6:
        for part in norm_slug.split("-"):
            if part == key_stem or part.startswith(f"{key_stem}-"):
                return 0.88, "key_stem"
    slug_parts = norm_slug.split("-")
    label_tokens = _token_set(comp.key) | _token_set(comp.label)
    for token in label_tokens:
        if len(token) < 5 or token in _GENERIC_LABEL_TOKENS:
            continue
        if token in slug_parts:
            return 0.88, "label_token"
    slug_tokens = _token_set(norm_slug)
    alias_tokens: set[str] = set()
    for alias in aliases:
        alias_tokens |= _token_set(alias)
    if not slug_tokens or not alias_tokens:
        return 0.0, "token_overlap"
    overlap = len(slug_tokens & alias_tokens) / len(slug_tokens | alias_tokens)
    if overlap >= 0.5:
        return 0.55 + overlap * 0.35, "token_overlap"
    return 0.0, "none"


def _confidence_from_score(score: float, matcher: str) -> Confidence | None:
    if matcher == "override" or matcher == "exact_normalized" or matcher == "exact_display":
        return "high"
    if matcher in (
        "substring",
        "repo_stem",
        "repo_norm",
        "key_stem",
        "label_token",
    ) and score >= 0.85:
        return "high"
    if score >= 0.75:
        return "medium"
    if score >= 0.55:
        return "low"
    return None


def match_slug(
    slug: str,
    *,
    components: list[RegistryComponent],
    overrides: dict[str, str],
    by_key: dict[str, RegistryComponent],
    catalog_by_name: dict[str, WizCatalogService],
    finding_counts: dict[str, int],
) -> MatchSuggestion | None:
    if slug == "unknown":
        return None

    svc = catalog_by_name.get(slug)
    project_names = svc.project_names if svc else ()

    if slug in overrides:
        comp = by_key.get(overrides[slug])
        if comp:
            return MatchSuggestion(
                wiz_service=slug,
                component_key=comp.key,
                team=comp.primary_team,
                confidence="high",
                matcher="override",
                finding_count=finding_counts.get(slug, 0),
                score=1.0,
                project_hint=project_names[0] if project_names else None,
            )

    for comp in components:
        if comp.wiz_service == slug:
            return None  # already mapped — handled by caller

    norm_slug = normalize_slug(slug)
    if norm_slug == normalize_slug(slug) and slug != norm_slug:
        pass  # still match on raw slug below

    if slug in {c.label for c in components}:
        comp = next(c for c in components if c.label == slug)
        return MatchSuggestion(
            wiz_service=slug,
            component_key=comp.key,
            team=comp.primary_team,
            confidence="high",
            matcher="exact_display",
            finding_count=finding_counts.get(slug, 0),
            score=1.0,
        )

    best: tuple[float, str, RegistryComponent] | None = None
    for comp in components:
        score, matcher = _score_candidate(norm_slug, comp)
        if score <= 0:
            continue
        if best is None or score > best[0]:
            best = (score, matcher, comp)

    if best:
        score, matcher, comp = best
        conf = _confidence_from_score(score, matcher)
        if conf:
            return MatchSuggestion(
                wiz_service=slug,
                component_key=comp.key,
                team=comp.primary_team,
                confidence=conf,
                matcher=matcher,
                finding_count=finding_counts.get(slug, 0),
                score=score,
                project_hint=project_names[0] if project_names else None,
            )

    return None


def build_suggestions(
    *,
    catalog: list[WizCatalogService],
    components: list[RegistryComponent],
    overrides: dict[str, str],
    finding_counts: dict[str, int],
    min_confidence: Confidence | None = None,
) -> SuggestReport:
    by_key = {c.key: c for c in components}
    catalog_by_name = {s.display_name: s for s in catalog}
    report = SuggestReport()

    slugs_in_db = {s for s in finding_counts if finding_counts[s] > 0}
    all_slugs = set(catalog_by_name) | slugs_in_db

    claimed_slug: dict[str, str] = {}
    claimed_component: dict[str, str] = {}
    for comp in components:
        if comp.wiz_service:
            report.already_mapped.append((comp.wiz_service, comp.key))
            claimed_slug[comp.wiz_service] = comp.key
            claimed_component[comp.key] = comp.wiz_service

    candidates: list[MatchSuggestion] = []
    for slug in sorted(all_slugs):
        if slug in claimed_slug:
            continue
        suggestion = match_slug(
            slug,
            components=components,
            overrides=overrides,
            by_key=by_key,
            catalog_by_name=catalog_by_name,
            finding_counts=finding_counts,
        )
        if not suggestion or not suggestion.component_key:
            if slug in catalog_by_name:
                report.unmapped_catalog.append(slug)
            elif finding_counts.get(slug, 0):
                report.unmapped_findings_only.append((slug, finding_counts[slug]))
            continue
        if min_confidence:
            order = {"high": 3, "medium": 2, "low": 1}
            if order[suggestion.confidence] < order[min_confidence]:
                continue
        candidates.append(suggestion)

    candidates.sort(key=_suggestion_priority, reverse=True)
    for suggestion in candidates:
        slug = suggestion.wiz_service
        key = suggestion.component_key
        prev_slug_owner = claimed_component.get(key)
        if prev_slug_owner and prev_slug_owner != slug:
            report.conflicts.append(
                f"component {key!r} already matched to {prev_slug_owner!r}, "
                f"also want {slug!r} (skipped)"
            )
            continue
        prev_key = claimed_slug.get(slug)
        if prev_key and prev_key != key:
            report.conflicts.append(
                f"duplicate target for wiz_service {slug!r}: {prev_key!r} vs {key!r} (skipped)"
            )
            continue
        claimed_slug[slug] = key
        claimed_component[key] = slug
        report.suggestions.append(suggestion)

    report.suggestions.sort(key=lambda s: s.wiz_service)
    return report


def merge_suggest_yaml_with_existing(
    payload: dict[str, Any],
    existing_path: Path | None,
) -> dict[str, Any]:
    """Keep operator manual_mappings when regenerating wiz_service_map.suggested.yaml."""
    if not existing_path or not existing_path.is_file():
        return payload
    raw = yaml.safe_load(existing_path.read_text(encoding="utf-8")) or {}
    by_slug: dict[str, dict[str, str]] = {}
    for item in raw.get("manual_mappings") or []:
        if isinstance(item, dict) and item.get("wiz_service"):
            by_slug[str(item["wiz_service"])] = {
                k: str(v)
                for k, v in item.items()
                if k in ("wiz_service", "team", "component_key") and v
            }
    for entry in operator_manual_from_suggestions(raw):
        slug = entry["wiz_service"]
        by_slug[slug] = {**by_slug.get(slug, {}), **entry}
    if not by_slug:
        return payload
    annotated = set(by_slug)
    payload["manual_mappings"] = sorted(
        by_slug.values(), key=lambda e: e.get("wiz_service", "")
    )
    payload["unmapped_catalog"] = [
        slug
        for slug in payload.get("unmapped_catalog") or []
        if slug not in annotated
    ]
    return payload


def suggest_to_yaml_dict(
    report: SuggestReport,
    *,
    wiz_tenant_hint: str = "live",
) -> dict[str, Any]:
    return {
        "version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "wiz_tenant": wiz_tenant_hint,
        "suggestions": [
            {
                "wiz_service": s.wiz_service,
                "component_key": s.component_key,
                "team": s.team,
                "confidence": s.confidence,
                "matcher": s.matcher,
                "finding_count": s.finding_count,
                "score": round(s.score, 3),
                **({"project_hint": s.project_hint} if s.project_hint else {}),
            }
            for s in report.suggestions
        ],
        "already_mapped": [
            {"wiz_service": slug, "component_key": key}
            for slug, key in report.already_mapped
        ],
        "manual_mappings": [],
        "unmapped_catalog": report.unmapped_catalog,
        "unmapped_findings_only": [
            {"wiz_service": slug, "finding_count": n}
            for slug, n in report.unmapped_findings_only
        ],
        "conflicts": report.conflicts,
    }


def apply_suggestions_to_registry(
    config_dir: Path,
    suggestions: list[MatchSuggestion],
    *,
    min_confidence: Confidence = "high",
    dry_run: bool = False,
) -> tuple[int, list[str]]:
    """Set `wiz_service` on registry rows. Returns (updated_count, log lines)."""
    order = {"high": 3, "medium": 2, "low": 1}
    min_ord = order[min_confidence]

    path = config_dir / "component_registry.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    components: list[dict] = list(raw.get("components") or [])
    by_key = {str(c.get("key")): c for c in components if c.get("key")}

    logs: list[str] = []
    updated = 0
    seen_wiz: set[str] = set()
    for comp in components:
        wiz = str(comp.get("wiz_service") or "").strip()
        if wiz:
            seen_wiz.add(wiz)

    for sug in suggestions:
        if order[sug.confidence] < min_ord:
            continue
        if not sug.component_key:
            continue
        if sug.wiz_service in seen_wiz:
            logs.append(f"skip {sug.wiz_service!r}: wiz_service already on registry")
            continue
        row = by_key.get(sug.component_key)
        if row is None:
            logs.append(f"skip {sug.wiz_service!r}: unknown component_key {sug.component_key!r}")
            continue
        if row.get("wiz_service"):
            logs.append(
                f"skip {sug.wiz_service!r}: {sug.component_key!r} already has "
                f"wiz_service={row['wiz_service']!r}"
            )
            continue
        logs.append(
            f"{'would set' if dry_run else 'set'} {sug.component_key!r}.wiz_service = {sug.wiz_service!r} "
            f"({sug.confidence}/{sug.matcher})"
        )
        if not dry_run:
            row["wiz_service"] = sug.wiz_service
            seen_wiz.add(sug.wiz_service)
            updated += 1

    if not dry_run and updated:
        path.write_text(
            yaml.safe_dump(raw, sort_keys=False, default_flow_style=False),
            encoding="utf-8",
        )
    return updated, logs


def strip_inline_comment(value: str) -> str:
    return value.split("#", 1)[0].strip()


def parse_unmapped_catalog_entry(line: object) -> tuple[str, str] | None:
    """Parse `slug - team` entries (YAML list items or `- slug - team` markdown lines)."""
    if not isinstance(line, str):
        return None
    text = line.strip()
    if text.startswith("- "):
        text = text[2:].strip()
    if " - " not in text:
        return None
    slug, target = text.rsplit(" - ", 1)
    slug = slug.strip()
    target = strip_inline_comment(target.strip())
    if not slug or not target:
        return None
    return slug, target


def _slug_component_score(slug: str, comp: RegistryComponent) -> float:
    norm_slug = normalize_slug(slug)
    slug_tokens = _token_set(norm_slug)
    key_tokens = _token_set(comp.key) | _token_set(comp.label)
    if comp.repo:
        key_tokens |= _token_set(comp.repo)
    if not slug_tokens or not key_tokens:
        return 0.0
    return len(slug_tokens & key_tokens) / len(slug_tokens | key_tokens)


def resolve_manual_target(
    slug: str,
    target: str,
    components: list[RegistryComponent],
    *,
    taken_components: set[str],
) -> tuple[str, str] | None:
    """Resolve operator `slug - target` to (component_key, team). Target may be team or component key."""
    by_key = {c.key: c for c in components}
    target = strip_inline_comment(target)
    if target in by_key:
        comp = by_key[target]
        if comp.key in taken_components or comp.wiz_service:
            return None
        return comp.key, comp.primary_team
    candidates = [
        c
        for c in components
        if c.primary_team == target and c.key not in taken_components and not c.wiz_service
    ]
    if not candidates:
        return None
    best = max(candidates, key=lambda c: _slug_component_score(slug, c))
    return best.key, best.primary_team


def operator_manual_from_suggestions(raw: dict[str, Any]) -> list[dict[str, str]]:
    """Rows operators edited under suggestions: team-only or explicit matcher=manual."""
    out: list[dict[str, str]] = []
    for item in raw.get("suggestions") or []:
        if not isinstance(item, dict):
            continue
        slug = str(item.get("wiz_service") or "").strip()
        team = str(item.get("team") or "").strip()
        key = strip_inline_comment(str(item.get("component_key") or ""))
        matcher = str(item.get("matcher") or "")
        if not slug or not team:
            continue
        if matcher == "manual" or not key:
            entry: dict[str, str] = {"wiz_service": slug, "team": team}
            if key:
                entry["component_key"] = key
            out.append(entry)
    return out


def load_manual_mappings_from_yaml(raw: dict[str, Any]) -> list[tuple[str, str]]:
    """Collect slug → team/component targets from manual_mappings and annotated unmapped_catalog."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in raw.get("manual_mappings") or []:
        if not isinstance(item, dict):
            continue
        slug = str(item.get("wiz_service") or "").strip()
        target = str(item.get("component_key") or item.get("team") or "").strip()
        if slug and target and slug not in seen:
            out.append((slug, target))
            seen.add(slug)
    for line in raw.get("unmapped_catalog") or []:
        parsed = parse_unmapped_catalog_entry(line)
        if parsed and parsed[0] not in seen:
            out.append(parsed)
            seen.add(parsed[0])
    return out


def load_suggestions_from_yaml(
    path: Path,
    *,
    config_dir: Path | None = None,
) -> tuple[list[MatchSuggestion], dict[str, str]]:
    """Load auto-suggestions plus operator manual mappings from wiz_service_map.suggested.yaml."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    components = load_registry_components(config_dir) if config_dir else []
    by_key = {c.key: c for c in components}
    taken: set[str] = set()
    suggestions: list[MatchSuggestion] = []
    team_only: dict[str, str] = {}

    for s in raw.get("suggestions") or []:
        if not isinstance(s, dict) or not s.get("wiz_service"):
            continue
        slug = str(s["wiz_service"])
        key = strip_inline_comment(str(s.get("component_key") or ""))
        if not key:
            continue
        team = str(s.get("team") or "")
        if key not in by_key and components:
            resolved = resolve_manual_target(
                slug, key, components, taken_components=taken
            )
            if resolved:
                key, team = resolved
            else:
                team_only[slug] = team or key
                continue
        suggestions.append(
            MatchSuggestion(
                wiz_service=slug,
                component_key=key,
                team=team or (by_key[key].primary_team if key in by_key else ""),
                confidence=s.get("confidence") or "high",  # type: ignore[arg-type]
                matcher=str(s.get("matcher") or "file"),
                finding_count=int(s.get("finding_count") or 0),
                score=float(s.get("score") or 0),
                project_hint=s.get("project_hint"),
            )
        )
        taken.add(key)

    for slug, target in load_manual_mappings_from_yaml(raw):
        resolved = None
        if components:
            resolved = resolve_manual_target(
                slug, target, components, taken_components=taken
            )
        if resolved:
            key, team = resolved
            suggestions.append(
                MatchSuggestion(
                    wiz_service=slug,
                    component_key=key,
                    team=team,
                    confidence="high",
                    matcher="manual",
                    finding_count=0,
                    score=1.0,
                )
            )
            taken.add(key)
        else:
            comp = next((c for c in components if c.key == target), None)
            team_only[slug] = comp.primary_team if comp else target

    return suggestions, team_only


def parse_wiz_service_team_map_text(text: str) -> dict[str, str]:
    raw = yaml.safe_load(text) or {}
    teams = raw.get("teams") or {}
    if not isinstance(teams, dict):
        return {}
    return {str(k): str(v) for k, v in teams.items()}


def load_wiz_service_team_map(config_dir: Path) -> dict[str, str]:
    path = config_dir / "wiz_service_team_map.yaml"
    if not path.is_file():
        return {}
    return parse_wiz_service_team_map_text(path.read_text(encoding="utf-8"))


def write_wiz_service_team_map(
    config_dir: Path,
    teams: dict[str, str],
    *,
    dry_run: bool = False,
) -> None:
    path = config_dir / "wiz_service_team_map.yaml"
    payload = {"version": 1, "teams": dict(sorted(teams.items()))}
    if not dry_run:
        path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def load_wiz_slug_owner_teams(config_dir: Path) -> dict[str, str]:
    """Registry wiz_service rows plus supplemental wiz_service_team_map.yaml."""
    from app.core.component_registry import parse_component_registry

    text = (config_dir / "component_registry.yaml").read_text(encoding="utf-8")
    out = dict(parse_component_registry(text).wiz_service_to_team)
    for slug, team in load_wiz_service_team_map(config_dir).items():
        out.setdefault(slug, team)
    return out


def load_wiz_service_to_team(config_dir: Path) -> dict[str, str]:
    return load_wiz_slug_owner_teams(config_dir)


def reresolve_wiz_owner_teams(
    session: Session,
    wiz_service_to_team: dict[str, str],
    *,
    dry_run: bool = False,
) -> tuple[int, int]:
    """Re-stamp owner_team on Wiz findings from registry wiz_service_to_team."""
    from app.core.enums import Status
    from app.normalizer.processor import UNOWNED_TEAM

    open_statuses = [s.value for s in Status.open_set()]
    rows = session.scalars(
        select(Finding).where(
            Finding.source == "wiz",
            Finding.status.in_(open_statuses),
            Finding.asset_id.like("wizservice:%"),
        )
    ).all()
    scanned = len(rows)
    updated = 0
    for row in rows:
        slug = str(row.asset_id).removeprefix("wizservice:")
        new_team = wiz_service_to_team.get(slug, UNOWNED_TEAM)
        if row.owner_team == new_team:
            continue
        if not dry_run:
            row.owner_team = new_team
        updated += 1
    if not dry_run and updated:
        session.commit()
    return scanned, updated
