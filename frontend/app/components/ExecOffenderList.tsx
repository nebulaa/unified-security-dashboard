"use client";

import { useMemo, useState, type ReactNode } from "react";
import {
  ALL_EXEC_SERVICES,
  assetKey,
  lookupComponent,
  teamLabel,
  type ServiceInfo,
} from "../lib/component-map";
import { githubUrlFor, sonarUrlFor } from "../lib/per-service-metrics";
import { teamRowLabel } from "../lib/team-registry";
import type { TopAssetPoint, TopTeamPoint } from "../lib/types";
import { GitHubIcon, SonarCloudIcon } from "./icons";

// ---------------------------------------------------------------------------
// Executive offender list — "which teams/services own the most open findings?"
//
// Renders the selected pillar's open critical+high count ranked most → least,
// broken down per severity so a team with 5 criticals looks different from a
// team with 5 highs even when the totals match (was the original ask on
// /executive — the headline "Open criticals" KPI is criticals-only but the
// list below was conflating crit+high into one number).
//
// Two modes via a top-level toggle:
//   - By team    : flat list of sub-team keys; expand for all owned services
//                  (including zero-finding repos) with per-severity counts,
//                  GitHub repo + SonarCloud project links.
//   - By service : flat list of services (asset_displays collapsed via
//                  `lookupComponent` so multiple Sonar projects can count as
//                  one service row); per-severity
//                  badges on the row; expand for repo and Sonar project links.
//
// Team rows are enriched from the frontend team registry.
// Service/repo links reuse `component-map.ts` + `per-service-metrics.ts`.
// ---------------------------------------------------------------------------

type Mode = "team" | "service";

export interface ExecOffenderListProps {
  /** Team-level rows for the selected pillar (from `/metrics/top-teams?team=...`). */
  teams: readonly TopTeamPoint[];
  /** Service-level rows (from `/metrics/top-services?team=...`); collapsed
   *  here by service label so a multi-asset service appears once. */
  services: readonly TopAssetPoint[];
  /** Empty-state message shown when both lists are empty for the selected
   *  pillar (e.g. no findings, or pillar not yet mapped). */
  emptyHint: string;
}

interface ServiceRow {
  service: string;
  teams: readonly string[];
  openCriticals: number;
  openHighs: number;
  openCount: number;
  /** Resolved from `ALL_EXEC_SERVICES` when the service is mapped. */
  info: ServiceInfo | null;
}

/** Per-service crit/high counts attributed to a single team. Used to render
 *  the expanded view of a team row — each repo gets the counts that belong
 *  to that team's slice of it, not the service-wide total. */
interface ServiceBreakdown {
  service: ServiceInfo;
  openCriticals: number;
  openHighs: number;
}

interface TeamRow extends TopTeamPoint {
  /** All services this team owns in `ALL_EXEC_SERVICES`, decorated with the
   *  team's slice of open crit/high. Zero-count services are kept so every
   *  mapped repo and Sonar project is visible on expand. */
  ownedServices: readonly ServiceBreakdown[];
}

export default function ExecOffenderList({
  teams,
  services,
  emptyHint,
}: ExecOffenderListProps) {
  const [mode, setMode] = useState<Mode>("team");
  const [expandedTeams, setExpandedTeams] = useState<ReadonlySet<string>>(
    () => new Set(),
  );
  const [expandedServices, setExpandedServices] = useState<ReadonlySet<string>>(
    () => new Set(),
  );

  const serviceRows = useMemo<ServiceRow[]>(() => {
    // Collapse multi-project services into one row while preserving the
    // per-severity split.
    const byService = new Map<
      string,
      {
        service: string;
        teams: Set<string>;
        openCriticals: number;
        openHighs: number;
        openCount: number;
      }
    >();
    for (const point of services) {
      const info = lookupComponent(point.asset_display, {
        ownerTeam: point.owner_team,
      });
      const serviceKey = info?.service ?? assetKey(point.asset_display);
      const existing = byService.get(serviceKey) ?? {
        service: info?.service ?? assetKey(point.asset_display),
        teams: new Set<string>(),
        openCriticals: 0,
        openHighs: 0,
        openCount: 0,
      };
      existing.teams.add(point.owner_team);
      existing.openCriticals += point.open_criticals;
      existing.openHighs += point.open_highs;
      existing.openCount += point.open_count;
      byService.set(serviceKey, existing);
    }
    return Array.from(byService.values())
      .map((row) => {
        const info =
          ALL_EXEC_SERVICES.find((s) => s.service === row.service) ?? null;
        return {
          service: row.service,
          teams: Array.from(row.teams).sort(),
          openCriticals: row.openCriticals,
          openHighs: row.openHighs,
          openCount: row.openCount,
          info,
        };
      })
      .sort(
        // Criticals dominate the rank; highs only break ties so a service
        // with 1 crit still outranks one with 5 highs.
        (a, b) =>
          b.openCriticals - a.openCriticals || b.openHighs - a.openHighs,
      );
  }, [services]);

  // Per-(team, service) crit/high totals — the source of the expanded view's
  // per-repo breakdown on a team row. Jointly owned services appear under
  // each team with only that team's slice.
  const breakdownByTeam = useMemo(() => {
    const map = new Map<
      string,
      Map<string, { openCriticals: number; openHighs: number }>
    >();
    for (const point of services) {
      const info = lookupComponent(point.asset_display, {
        ownerTeam: point.owner_team,
      });
      const serviceKey = info?.service ?? assetKey(point.asset_display);
      let inner = map.get(point.owner_team);
      if (!inner) {
        inner = new Map();
        map.set(point.owner_team, inner);
      }
      const existing = inner.get(serviceKey) ?? {
        openCriticals: 0,
        openHighs: 0,
      };
      existing.openCriticals += point.open_criticals;
      existing.openHighs += point.open_highs;
      inner.set(serviceKey, existing);
    }
    return map;
  }, [services]);

  const teamRows = useMemo<TeamRow[]>(() => {
    return [...teams]
      .sort(
        // Same ordering rule as the By-service mode: criticals first, then
        // highs as a tiebreaker, so the headline ranking lines up with the
        // "Open criticals" KPI above it.
        (a, b) =>
          b.open_criticals - a.open_criticals || b.open_highs - a.open_highs,
      )
      .map((row) => {
        const teamBreakdown = breakdownByTeam.get(row.team);
        const ownedServices: ServiceBreakdown[] = ALL_EXEC_SERVICES.filter((s) =>
          s.allTeams.includes(row.team),
        )
          .map((service) => {
            const counts = teamBreakdown?.get(service.service) ?? {
              openCriticals: 0,
              openHighs: 0,
            };
            return {
              service,
              openCriticals: counts.openCriticals,
              openHighs: counts.openHighs,
            };
          })
          .sort(
            (a, b) =>
              b.openCriticals - a.openCriticals || b.openHighs - a.openHighs,
          );
        return { ...row, ownedServices };
      });
  }, [teams, breakdownByTeam]);

  const isEmpty = mode === "team" ? teamRows.length === 0 : serviceRows.length === 0;

  function toggleTeam(team: string) {
    setExpandedTeams((prev) => {
      const next = new Set(prev);
      if (next.has(team)) next.delete(team);
      else next.add(team);
      return next;
    });
  }

  function toggleService(service: string) {
    setExpandedServices((prev) => {
      const next = new Set(prev);
      if (next.has(service)) next.delete(service);
      else next.add(service);
      return next;
    });
  }

  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900/40">
      <div className="flex items-center justify-between gap-3 border-b border-neutral-900 px-4 py-3">
        <div>
          <h2 className="text-sm uppercase tracking-wide text-neutral-300">
            {mode === "team"
              ? "Teams with the most open findings"
              : "Services with the most open findings"}
          </h2>
        </div>
        <div className="flex items-center gap-1 text-xs">
          <ModePill label="By team" active={mode === "team"} onClick={() => setMode("team")} />
          <ModePill label="By service" active={mode === "service"} onClick={() => setMode("service")} />
        </div>
      </div>
      {isEmpty ? (
        <div className="px-4 py-8 text-center text-sm text-neutral-500">{emptyHint}</div>
      ) : mode === "team" ? (
        <ol className="divide-y divide-neutral-900">
          {teamRows.map((row, i) => (
            <TeamOffenderRow
              key={row.team}
              row={row}
              rank={i + 1}
              expanded={expandedTeams.has(row.team)}
              onToggle={() => toggleTeam(row.team)}
            />
          ))}
        </ol>
      ) : (
        <ol className="divide-y divide-neutral-900">
          {serviceRows.map((row, i) => (
            <ServiceOffenderRow
              key={row.service}
              row={row}
              rank={i + 1}
              expanded={expandedServices.has(row.service)}
              onToggle={() => toggleService(row.service)}
            />
          ))}
        </ol>
      )}
    </div>
  );
}

function TeamOffenderRow({
  row,
  rank,
  expanded,
  onToggle,
}: {
  row: TeamRow;
  rank: number;
  expanded: boolean;
  onToggle: () => void;
}) {
  const hasDetails = row.ownedServices.length > 0;
  return (
    <li>
      <div className="flex items-center justify-between gap-3 px-4 py-2.5">
        <div className="flex min-w-0 flex-1 items-center gap-2 text-sm">
          <span className="w-6 shrink-0 text-right font-mono text-xs text-neutral-500">
            {rank}.
          </span>
          {hasDetails ? (
            <ExpandButton expanded={expanded} onClick={onToggle} label={`${teamRowLabel(row.team)} details`} />
          ) : (
            <span className="w-5 shrink-0" aria-hidden="true" />
          )}
          <span className="min-w-0 text-neutral-100">{teamRowLabel(row.team)}</span>
        </div>
        <SeverityCounts
          criticals={row.open_criticals}
          highs={row.open_highs}
        />
      </div>
      {expanded && hasDetails && (
        <ul className="space-y-1 border-t border-neutral-900/80 bg-neutral-950/40 px-4 py-2 pl-14">
          {row.ownedServices.map((entry) => (
            <ServiceBreakdownRow
              key={entry.service.service}
              service={entry.service}
              openCriticals={entry.openCriticals}
              openHighs={entry.openHighs}
            />
          ))}
        </ul>
      )}
    </li>
  );
}

function ServiceOffenderRow({
  row,
  rank,
  expanded,
  onToggle,
}: {
  row: ServiceRow;
  rank: number;
  expanded: boolean;
  onToggle: () => void;
}) {
  const hasDetails = row.info != null && row.info.execShowRepoLinks;
  return (
    <li>
      <div className="flex items-center justify-between gap-3 px-4 py-2.5">
        <div className="flex min-w-0 flex-1 items-center gap-2 text-sm">
          <span className="w-6 shrink-0 text-right font-mono text-xs text-neutral-500">
            {rank}.
          </span>
          {hasDetails ? (
            <ExpandButton expanded={expanded} onClick={onToggle} label={`${row.service} details`} />
          ) : (
            <span className="w-5 shrink-0" aria-hidden="true" />
          )}
          <span className="truncate text-neutral-100">{row.service}</span>
          <span className="truncate text-xs text-neutral-500">
            {row.teams.map((t) => teamLabel(t)).join(" · ")}
          </span>
        </div>
        <SeverityCounts criticals={row.openCriticals} highs={row.openHighs} />
      </div>
      {expanded && row.info && (
        <ul className="border-t border-neutral-900/80 bg-neutral-950/40 px-4 py-2 pl-14">
          <ServiceLinks service={row.info} />
        </ul>
      )}
    </li>
  );
}

// ---------------------------------------------------------------------------
// Per-severity pair rendered on each row + on each per-service breakdown row.
// Critical is red, high is amber. We deliberately render both even when one
// is 0 so the cell shape is consistent across rows (otherwise the alignment
// of the numbers wanders as zeros disappear); we just mute the zeros so the
// visual emphasis still points at the actual exposure.
// ---------------------------------------------------------------------------
function SeverityCounts({
  criticals,
  highs,
  size = "lg",
}: {
  criticals: number;
  highs: number;
  size?: "lg" | "sm";
}) {
  const numCls =
    size === "lg" ? "font-mono text-base font-semibold" : "font-mono text-xs";
  const labelCls =
    size === "lg"
      ? "text-[10px] uppercase tracking-wide text-neutral-500"
      : "text-[10px] uppercase tracking-wide text-neutral-500";
  const critTone =
    criticals > 0
      ? "text-red-700 dark:text-red-300"
      : "text-neutral-600 dark:text-neutral-500";
  const highTone =
    highs > 0
      ? "text-amber-700 dark:text-amber-300"
      : "text-neutral-600 dark:text-neutral-500";
  return (
    <div className="flex shrink-0 items-baseline gap-3">
      <span className="inline-flex items-baseline gap-1">
        <span className={`${numCls} ${critTone}`}>{criticals}</span>
        <span className={labelCls}>crit</span>
      </span>
      <span className="inline-flex items-baseline gap-1">
        <span className={`${numCls} ${highTone}`}>{highs}</span>
        <span className={labelCls}>high</span>
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// One line in the expanded view of a team row: service label + crit/high
// counts attributed to *this team's* slice of the service, plus the GitHub
// repo and SonarCloud project links so users can jump from the offender list
// straight to the code (the "mapped to the repo" half of the ask).
// ---------------------------------------------------------------------------
function ServiceBreakdownRow({
  service,
  openCriticals,
  openHighs,
}: {
  service: ServiceInfo;
  openCriticals: number;
  openHighs: number;
}) {
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 py-1 text-xs text-neutral-400">
      <span className="min-w-[8rem] font-medium text-neutral-300">
        {service.service}
      </span>
      <SeverityCounts
        criticals={openCriticals}
        highs={openHighs}
        size="sm"
      />
      {service.execShowRepoLinks ? (
        <>
          <ExternalLink
            href={githubUrlFor(service)}
            label={`Open ${service.repo} on GitHub`}
          >
            <GitHubIcon size={14} />
            <span>{service.repo}</span>
          </ExternalLink>
          {service.sonarProjects.map((key) => {
            const url = sonarUrlFor({ ...service, sonarProjects: [key] });
            if (!url) return null;
            return (
              <ExternalLink
                key={key}
                href={url}
                label={`Open ${key} on SonarCloud`}
              >
                <SonarCloudIcon size={14} />
                <span className="max-w-[12rem] truncate font-mono">{key}</span>
              </ExternalLink>
            );
          })}
        </>
      ) : null}
    </li>
  );
}

// ServiceLinks is still used by the By-service expansion: in that mode the
// crit/high counts are already on the row itself, so the expanded view is
// just the repo + Sonar links and doesn't need to repeat the numbers.
function ServiceLinks({ service }: { service: ServiceInfo }) {
  if (!service.execShowRepoLinks) return null;
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 py-1.5 text-xs text-neutral-400">
      <span className="font-medium text-neutral-300">{service.service}</span>
      <ExternalLink href={githubUrlFor(service)} label={`Open ${service.repo} on GitHub`}>
        <GitHubIcon size={14} />
        <span>{service.repo}</span>
      </ExternalLink>
      {service.sonarProjects.map((key) => {
        const url = sonarUrlFor({ ...service, sonarProjects: [key] });
        if (!url) return null;
        return (
          <ExternalLink key={key} href={url} label={`Open ${key} on SonarCloud`}>
            <SonarCloudIcon size={14} />
            <span className="max-w-[12rem] truncate font-mono">{key}</span>
          </ExternalLink>
        );
      })}
    </li>
  );
}

function ExpandButton({
  expanded,
  onClick,
  label,
}: {
  expanded: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-expanded={expanded}
      aria-label={label}
      className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-neutral-500 transition-colors hover:bg-neutral-800 hover:text-neutral-200"
    >
      <span
        className={`inline-block text-[10px] transition-transform ${expanded ? "rotate-90" : ""}`}
        aria-hidden="true"
      >
        ▶
      </span>
    </button>
  );
}

function ExternalLink({
  href,
  label,
  children,
}: {
  href: string;
  label: string;
  children: ReactNode;
}) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      title={label}
      className="inline-flex items-center gap-1 text-neutral-400 transition-colors hover:text-neutral-100"
    >
      {children}
    </a>
  );
}

function ModePill({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`rounded border px-2 py-0.5 transition-colors ${
        active
          ? "border-neutral-500 bg-neutral-800 text-neutral-100"
          : "border-neutral-800 bg-neutral-950 text-neutral-400 hover:border-neutral-600 hover:text-neutral-200"
      }`}
    >
      {label}
    </button>
  );
}
