"use client";

import { Fragment, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  ALL_SERVICES,
  teamLabel,
  type ServiceInfo,
} from "../lib/component-map";
import {
  effectiveDeveloperTeams,
  resolveActiveDeveloperPillar,
} from "../lib/developer-scope";
import {
  aggregateByService,
  aggregateGroup,
  GRADE_RANK,
  githubUrlFor,
  sonarUrlFor,
  type Grade,
  type GroupAggregate,
  type ServiceMetrics,
} from "../lib/per-service-metrics";
import type { FindingListResponse, FindingSummary } from "../lib/types";
import { GitHubIcon, SonarCloudIcon } from "./icons";

// ---------------------------------------------------------------------------
// Per-service security table — the chart-first roll-up on /developer.
//
// Goals (per the 2026-05-18 dev-view rework):
//   1. Land on this section ready to filter — four static dropdowns at the top
//      (Application / Team / Service / Repo) narrow the table AND the URL,
//      so the rating cards + trend chart up the page rescope in lockstep.
//      Service + Repo write the same `?asset=` URL param (substring match on
//      asset_display); selecting one clears the other. Application + Team
//      write `?team=…` (possibly repeated).
//   2. Two orthogonal controls above the table:
//        - **Group by** (By application / By service / By team) controls row
//          organisation. By service is a flat list; the others render a
//          rowspan group cell on the left with the group label + aggregate
//          worst-grade pill + total open critical / high. By team duplicates
//          shared services under each owning team so shared ownership remains
//          visible.
//        - **Detail level** (High-level / Detailed) controls the column set:
//            - High-level: per-source A-D rating + Jira pentest count. Daily
//              glance for "who is doing well / who needs help".
//            - Detailed:   raw count columns (Sonar crit/high, Dependabot
//              crit/high, SLA-breached crit/high). The operations view.
//   3. One row per service. Each row carries GitHub + SonarCloud icon links
//      out to the source tools (the user spends their day in those, the
//      dashboard's job is to point them at the right tab).
//   4. Every service from `dev-view mapping.md` is listed, even with zero
//      findings, so the full footprint is visible. Sorted by severity-weighted
//      open count (rows that need attention float to the top); zero-finding
//      rows pile up at the bottom in alphabetical order. Groups follow the
//      same logic: worst-grade group first, ties broken by total open count.
//   5. NO inline finding rows. The granular list lives in the "Explore
//      findings" disclosure below — keeps this table a true overview.
// ---------------------------------------------------------------------------

type ViewMode = "highlevel" | "detailed";
type GroupBy = "application" | "service" | "team";

interface GroupedSet {
  /** Stable key for React iteration (`__all__` for the flat By-Service case). */
  key: string;
  /** Display label for the group rowspan cell ("" for the flat case). */
  label: string;
  /** Aggregate worst-grade + counts across the group's services. */
  agg: GroupAggregate;
  /** Services in the group, pre-sorted by severity desc. */
  services: ServiceMetrics[];
}

interface Props {
  initialData?: FindingListResponse;
}

// ---------------------------------------------------------------------------
// Filter bar — mutually-exclusive SLA toggles (Breaches / Within SLA).
//
// Rationale (2026-05-18 simplification): the previous 4-dropdown bar
// (Application / Team / Service / Repo) was removed because the team chips
// in TeamQuickPicker already cover the structural scoping flow, and the
// remaining Application / Service / Repo narrowings weren't earning their
// vertical real estate on the daily landing read. The only filter that
// stayed was the cross-cutting SLA narrowing, which got promoted to first-
// class status with its complement ("Within SLA") next to it. The two pills
// are mutually exclusive — picking one clears the other — so the URL `?sla=`
// only ever holds one of `breached` / `within`. Click an active pill to
// clear back to no SLA filter.
// ---------------------------------------------------------------------------

type SlaMode = "off" | "breached" | "within";

interface FilterBarProps {
  slaMode: SlaMode;
  onSlaModeChange: (next: SlaMode) => void;
  onClear: () => void;
  showClear: boolean;
}

function FilterBar(props: FilterBarProps) {
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-xl border border-white/5 bg-gradient-to-b from-neutral-900/60 to-neutral-950/40 px-3 py-2.5 shadow-sm">
      <span className="text-xs font-semibold uppercase tracking-[0.08em] text-neutral-400 mr-1">
        SLA
      </span>
      <SlaPill
        mode="breached"
        active={props.slaMode === "breached"}
        onClick={() =>
          props.onSlaModeChange(
            props.slaMode === "breached" ? "off" : "breached",
          )
        }
      />
      <SlaPill
        mode="within"
        active={props.slaMode === "within"}
        onClick={() =>
          props.onSlaModeChange(
            props.slaMode === "within" ? "off" : "within",
          )
        }
      />
      {props.showClear && (
        <button
          type="button"
          onClick={props.onClear}
          className="ml-auto text-xs text-neutral-400 hover:text-neutral-200 underline underline-offset-2"
        >
          clear filters
        </button>
      )}
    </div>
  );
}

/** Single SLA toggle pill — used twice in FilterBar to render the mutually-
 *  exclusive "Breaches" and "Within SLA" pair. Red palette for breaches (a
 *  warning narrowing), emerald palette for within-SLA (a healthy-state
 *  narrowing). Each pill is independently togglable: clicking an active pill
 *  turns the SLA filter off entirely. The parent enforces the mutual-exclusion
 *  by switching to "off" whenever the user clicks the already-active pill. */
function SlaPill({
  mode,
  active,
  onClick,
}: {
  mode: "breached" | "within";
  active: boolean;
  onClick: () => void;
}) {
  const isBreached = mode === "breached";
  const label = isBreached ? "SLA breaches" : "Within SLA";
  const icon = isBreached ? "⚠" : "✓";
  const title = isBreached
    ? "Show only services with at least one finding past its SLA window (Sonar, Dependabot, or Jira pentest)"
    : "Show only services whose findings are all inside their SLA window";

  // Semantic-tinted pill (red for breaches, emerald for within-SLA). Light
  // mode reads the 700 end of each ramp for the foreground; dark mode keeps
  // the existing 200 end. The ring shadow stays an explicit rgba() because
  // Tailwind's shadow arbitrary syntax can't take a theme switcher inline.
  const activeStyle = isBreached
    ? "border-red-500/50 bg-red-500/15 text-red-700 dark:text-red-200 shadow-[0_0_0_1px_rgba(239,68,68,0.35)]"
    : "border-emerald-500/50 bg-emerald-500/15 text-emerald-700 dark:text-emerald-200 shadow-[0_0_0_1px_rgba(16,185,129,0.35)]";
  const idleHover = isBreached
    ? "hover:border-red-500/30 hover:bg-red-500/5 hover:text-red-700 dark:hover:text-red-200"
    : "hover:border-emerald-500/30 hover:bg-emerald-500/5 hover:text-emerald-700 dark:hover:text-emerald-200";

  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      title={title}
      className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-all ${
        active
          ? activeStyle
          : `border-white/10 bg-neutral-900/60 text-neutral-300 ${idleHover}`
      }`}
    >
      <span aria-hidden="true">{icon}</span>
      <span>{label}</span>
      {active && (
        <span
          className={`text-[10px] uppercase tracking-wide ${
            isBreached
              ? "text-red-700/80 dark:text-red-300/80"
              : "text-emerald-700/80 dark:text-emerald-300/80"
          }`}
        >
          on
        </span>
      )}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Mode tabs (High-level vs Detailed)
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Group-by segmented control (Application / Service / Team)
// ---------------------------------------------------------------------------

function GroupByTabs({
  group,
  onChange,
}: {
  group: GroupBy;
  onChange: (next: GroupBy) => void;
}) {
  // Wide pill so the three options are equally
  // weighted and easy to scan. Default landing is "By application" — the most
  // generally useful organisation regardless of the active team scope.
  const tabs: ReadonlyArray<{ key: GroupBy; label: string; icon: string }> = [
    { key: "application", label: "By application", icon: "▦" },
    { key: "service", label: "By service", icon: "◫" },
    { key: "team", label: "By team", icon: "◉" },
  ];
  return (
    <div
      role="tablist"
      aria-label="Group by"
      className="grid grid-cols-3 gap-1 rounded-xl border border-white/5 bg-neutral-900/40 p-1 shadow-inner"
    >
      {tabs.map((t) => (
        <button
          key={t.key}
          type="button"
          role="tab"
          aria-selected={group === t.key}
          onClick={() => onChange(t.key)}
          className={`flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-all ${
            group === t.key
              ? "bg-blue-500/20 text-blue-700 dark:text-blue-200 shadow-[0_0_0_1px_rgba(59,130,246,0.35)]"
              : "text-neutral-400 hover:bg-neutral-800/50 hover:text-neutral-100"
          }`}
        >
          <span className="text-base opacity-70" aria-hidden="true">
            {t.icon}
          </span>
          <span>{t.label}</span>
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Mode tabs (High-level vs Detailed) — controls the COLUMN set, orthogonal
// to GroupByTabs which controls ROW organisation
// ---------------------------------------------------------------------------

function ModeTabs({
  mode,
  onChange,
}: {
  mode: ViewMode;
  onChange: (next: ViewMode) => void;
}) {
  // Segmented-control pill — more modern than the previous underlined-tabs
  // style. The two modes are siblings of equal weight (not "main vs alt"),
  // and a pill control makes that clearer. The hint text below the row is
  // the standard pattern (Recharts / Linear / GitHub) for a single-line tip
  // attached to a segmented control.
  const tabs: ReadonlyArray<{ key: ViewMode; label: string; hint: string }> = [
    { key: "highlevel", label: "High-level", hint: "per-source A–D ratings + Jira pentest findings" },
    { key: "detailed", label: "Detailed", hint: "raw counts per source + SLA breach" },
  ];
  const activeHint = tabs.find((t) => t.key === mode)?.hint ?? "";
  return (
    <div className="flex flex-wrap items-center gap-3">
      <div
        role="tablist"
        aria-label="Detail level"
        className="inline-flex rounded-full border border-white/5 bg-neutral-900/60 p-0.5 shadow-inner"
      >
        {tabs.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={mode === t.key}
            onClick={() => onChange(t.key)}
            className={`rounded-full px-4 py-1.5 text-sm font-medium transition-all ${
              mode === t.key
                ? "bg-neutral-700/80 text-white shadow-[0_1px_2px_rgba(0,0,0,0.4)]"
                : "text-neutral-400 hover:text-neutral-100"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      <span className="text-xs text-neutral-500">{activeHint}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Row presentation atoms
// ---------------------------------------------------------------------------

// Grade pill palette per A–D tier. Same pattern used elsewhere: pale 50/300
// ramp end in light mode, deep 950/700 ramp end in dark mode.
const GRADE_COLOR: Record<Grade, string> = {
  A: "text-emerald-700 border-emerald-300 bg-emerald-50 dark:text-emerald-300 dark:border-emerald-700/50 dark:bg-emerald-950/30",
  B: "text-blue-700 border-blue-300 bg-blue-50 dark:text-blue-300 dark:border-blue-700/50 dark:bg-blue-950/30",
  C: "text-amber-700 border-amber-300 bg-amber-50 dark:text-amber-300 dark:border-amber-700/50 dark:bg-amber-950/30",
  D: "text-red-700 border-red-300 bg-red-50 dark:text-red-300 dark:border-red-700/50 dark:bg-red-950/30",
};

function GradePill({ grade }: { grade: Grade }) {
  // Slightly larger pill (was w-7 h-6 text-xs) so the letter reads from the
  // far end of a meeting room screen-share without leaning in.
  return (
    <span
      className={`inline-flex items-center justify-center w-8 h-7 rounded-md border font-mono font-bold text-sm ${GRADE_COLOR[grade]}`}
    >
      {grade}
    </span>
  );
}

function CountCell({
  count,
  tone,
}: {
  count: number;
  tone: "crit" | "high" | "sla";
}) {
  if (count === 0)
    return (
      <span className="text-neutral-700 tabular-nums text-sm">—</span>
    );
  const color =
    tone === "crit"
      ? "text-red-700 dark:text-red-300"
      : tone === "high"
        ? "text-amber-700 dark:text-amber-300"
        : "text-red-700 dark:text-red-400";
  return (
    <span className={`tabular-nums font-mono text-sm ${color}`}>{count}</span>
  );
}

function IconLink({
  href,
  label,
  children,
}: {
  href: string;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      title={label}
      aria-label={label}
      className="inline-flex items-center justify-center text-neutral-500 hover:text-neutral-100 transition-colors"
    >
      {children}
    </a>
  );
}

function GroupCell({ label, agg }: { label: string; agg: GroupAggregate }) {
  // Left-side rowspan cell shown when GroupBy is "application" or "team".
  // Compact 2-line layout (was 4 in the original; the table felt very tall
  // with multi-row groups stretching every group cell to four stacked lines):
  //   Line 1: bold group label
  //   Line 2: grade pill + service count + inline crit / high / SLA badges
  // Counts only render when non-zero, so quiet groups collapse to just the
  // label + grade pill — the green-grade quiet-state reads as calm.
  const tone = GRADE_TONE[agg.worstGrade];
  const hasCounts =
    agg.totalCriticals > 0 || agg.totalHighs > 0 || agg.totalSlaBreached > 0;
  return (
    <div className="flex flex-col gap-1.5">
      <div className="text-base font-semibold text-neutral-100 leading-snug">
        {label}
      </div>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
        <GradePill grade={agg.worstGrade} />
        <span className="text-neutral-500">
          {agg.serviceCount} {agg.serviceCount === 1 ? "service" : "services"}
        </span>
        {hasCounts && <span className="text-neutral-700">·</span>}
        {agg.totalCriticals > 0 && (
          <span className={`${tone.critText} font-medium`}>
            {agg.totalCriticals} critical
          </span>
        )}
        {agg.totalHighs > 0 && (
          <span className="text-amber-700/90 dark:text-amber-300/90 font-medium">
            {agg.totalHighs} high
          </span>
        )}
        {agg.totalSlaBreached > 0 && (
          <span className="text-red-700 dark:text-red-300 font-medium">
            {agg.totalSlaBreached} SLA
          </span>
        )}
      </div>
    </div>
  );
}

// Per-grade colour hints, matched to the GradePill palette. Only `critText`
// is consumed today; keeping the structure makes future tone-aware UI
// (badges, sub-counts) a one-line addition.
const GRADE_TONE: Record<Grade, { critText: string }> = {
  A: { critText: "text-emerald-700/80 dark:text-emerald-300/80" },
  B: { critText: "text-blue-700/80 dark:text-blue-300/80" },
  C: { critText: "text-amber-700/80 dark:text-amber-300/80" },
  D: { critText: "text-red-700/90 dark:text-red-300/90" },
};

function ServiceCell({ service }: { service: ServiceInfo }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-neutral-100 text-sm font-medium">
        {service.service}
      </span>
      <span className="flex items-center gap-1.5 ml-1">
        <IconLink href={githubUrlFor(service)} label={`Open ${service.repo} on GitHub`}>
          <GitHubIcon />
        </IconLink>
        {sonarUrlFor(service) && (
          <IconLink
            href={sonarUrlFor(service)!}
            label={`Open ${service.sonarProjects[0]} on SonarCloud`}
          >
            <SonarCloudIcon />
          </IconLink>
        )}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Headers + rows — parameterised by group mode so the same JSX handles all
// three groupings cleanly.
//
//   showGroupColumn — true for "application" and "team" (rowspan group cell
//                     prepended on the leftmost column).
//   showAppColumn   — false when GroupBy === "application" (would be redundant
//                     with the group label); true otherwise.
// ---------------------------------------------------------------------------

interface LayoutFlags {
  showGroupColumn: boolean;
  showAppColumn: boolean;
}

function flagsForGroupBy(group: GroupBy): LayoutFlags {
  return {
    showGroupColumn: group !== "service",
    showAppColumn: group !== "application",
  };
}

function HighLevelHeader({ flags }: { flags: LayoutFlags }) {
  return (
    <tr className="text-xs uppercase tracking-[0.08em] text-neutral-300">
      {flags.showGroupColumn && (
        <th className="px-4 py-3 text-left font-semibold w-52">
          {/* Group label is filled per-row via the rowspan cell. */}
        </th>
      )}
      {flags.showAppColumn && (
        <th className="px-4 py-3 text-left font-semibold">Application</th>
      )}
      <th className="px-4 py-3 text-left font-semibold">Service</th>
      <th className="px-4 py-3 text-center font-semibold">Sonar</th>
      <th className="px-4 py-3 text-center font-semibold">Dependabot</th>
      <th className="px-4 py-3 text-right font-semibold">Jira pentest</th>
    </tr>
  );
}

function HighLevelRow({
  m,
  flags,
  groupCell,
  isGroupBoundary,
}: {
  m: ServiceMetrics;
  flags: LayoutFlags;
  /** First row of a group renders this in a rowspan cell; subsequent rows omit. */
  groupCell?: { node: React.ReactNode; rowSpan: number };
  /** First row of a non-first group gets a stronger top border to visually
   *  separate the groups. */
  isGroupBoundary?: boolean;
}) {
  const pentestOpen = m.pentestCriticals + m.pentestHighs + m.pentestMediums;
  const boundary = isGroupBoundary ? "border-t-2 border-t-neutral-800/80" : "border-t border-white/5";
  return (
    <tr className={`${boundary} hover:bg-white/[0.025] transition-colors`}>
      {flags.showGroupColumn && groupCell && (
        <td
          rowSpan={groupCell.rowSpan}
          className="px-4 py-3 align-top border-r border-white/5 bg-neutral-900/40"
        >
          {groupCell.node}
        </td>
      )}
      {flags.showAppColumn && (
        <td className="px-4 py-2.5 text-sm text-neutral-200 align-middle">
          {m.service.application}
        </td>
      )}
      <td className="px-4 py-2.5 align-middle">
        <ServiceCell service={m.service} />
      </td>
      <td className="px-4 py-2.5 text-center align-middle">
        <GradePill grade={m.sonarGrade} />
      </td>
      <td className="px-4 py-2.5 text-center align-middle">
        <GradePill grade={m.dependabotGrade} />
      </td>
      <td className="px-4 py-2.5 text-right align-middle">
        {pentestOpen === 0 ? (
          <span className="text-neutral-700 tabular-nums text-sm">0</span>
        ) : (
          <span
            className={`tabular-nums font-mono text-sm ${
              m.pentestCriticals > 0
                ? "text-red-700 dark:text-red-300"
                : m.pentestHighs > 0
                  ? "text-amber-700 dark:text-amber-300"
                  : "text-neutral-300"
            }`}
            title={`${m.pentestCriticals} critical / ${m.pentestHighs} high / ${m.pentestMediums} medium`}
          >
            {pentestOpen}
          </span>
        )}
      </td>
    </tr>
  );
}

function DetailedHeader({ flags }: { flags: LayoutFlags }) {
  return (
    <tr className="text-xs uppercase tracking-[0.08em] text-neutral-300">
      {flags.showGroupColumn && (
        <th className="px-4 py-3 text-left font-semibold w-52" rowSpan={2} />
      )}
      {flags.showAppColumn && (
        <th className="px-4 py-3 text-left font-semibold" rowSpan={2}>
          Application
        </th>
      )}
      <th className="px-4 py-3 text-left font-semibold" rowSpan={2}>
        Service
      </th>
      <th className="px-4 py-3 text-right font-semibold" colSpan={2}>
        <span className="text-red-700 dark:text-red-300">Sonar</span>
      </th>
      <th className="px-4 py-3 text-right font-semibold" colSpan={2}>
        <span className="text-blue-700 dark:text-blue-300">Dependabot</span>
      </th>
      <th className="px-4 py-3 text-right font-semibold" colSpan={2}>
        <span className="text-red-700 dark:text-red-300">SLA</span>
      </th>
    </tr>
  );
}

function DetailedSubHeader() {
  return (
    <tr className="text-[11px] uppercase tracking-wide text-neutral-500">
      <th className="px-4 pb-2 text-right font-medium">Critical</th>
      <th className="px-4 pb-2 text-right font-medium">High</th>
      <th className="px-4 pb-2 text-right font-medium">Critical</th>
      <th className="px-4 pb-2 text-right font-medium">High</th>
      <th className="px-4 pb-2 text-right font-medium">Critical</th>
      <th className="px-4 pb-2 text-right font-medium">High</th>
    </tr>
  );
}

function DetailedRow({
  m,
  flags,
  groupCell,
  isGroupBoundary,
}: {
  m: ServiceMetrics;
  flags: LayoutFlags;
  groupCell?: { node: React.ReactNode; rowSpan: number };
  isGroupBoundary?: boolean;
}) {
  const boundary = isGroupBoundary ? "border-t-2 border-t-neutral-800/80" : "border-t border-white/5";
  return (
    <tr className={`${boundary} hover:bg-white/[0.025] transition-colors`}>
      {flags.showGroupColumn && groupCell && (
        <td
          rowSpan={groupCell.rowSpan}
          className="px-4 py-3 align-top border-r border-white/5 bg-neutral-900/40"
        >
          {groupCell.node}
        </td>
      )}
      {flags.showAppColumn && (
        <td className="px-4 py-2.5 text-sm text-neutral-200 align-middle">
          {m.service.application}
        </td>
      )}
      <td className="px-4 py-2.5 align-middle">
        <ServiceCell service={m.service} />
      </td>
      <td className="px-4 py-2.5 text-right align-middle">
        <CountCell count={m.sonarCriticals} tone="crit" />
      </td>
      <td className="px-4 py-2.5 text-right align-middle">
        <CountCell count={m.sonarHighs} tone="high" />
      </td>
      <td className="px-4 py-2.5 text-right align-middle">
        <CountCell count={m.dependabotCriticals} tone="crit" />
      </td>
      <td className="px-4 py-2.5 text-right align-middle">
        <CountCell count={m.dependabotHighs} tone="high" />
      </td>
      <td className="px-4 py-2.5 text-right align-middle">
        <CountCell count={m.criticalSlaBreached} tone="sla" />
      </td>
      <td className="px-4 py-2.5 text-right align-middle">
        <CountCell count={m.highSlaBreached} tone="sla" />
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Filtering + URL sync
// ---------------------------------------------------------------------------

function applyServiceFilters(
  metrics: Map<string, ServiceMetrics>,
  filter: {
    /** When true, drop services with no findings in the loaded list. Active
     *  whenever the SLA pill is on (breached OR within) — the findings list
     *  is then pre-filtered server-side via `sla_breached=true|false`, so a
     *  zero-total service in either mode literally has nothing to contribute
     *  and shouldn't take up a row. Off by default so the "is everyone
     *  healthy?" landing read still shows the full structural footprint. */
    onlyNonEmpty: boolean;
  },
): ServiceMetrics[] {
  const out: ServiceMetrics[] = [];
  for (const m of metrics.values()) {
    if (filter.onlyNonEmpty && m.totalOpen === 0) continue;
    out.push(m);
  }
  // Sort: rows that need attention first (total open desc), then alphabetical.
  out.sort((a, b) => {
    if (a.totalOpen !== b.totalOpen) return b.totalOpen - a.totalOpen;
    if (a.totalCriticals !== b.totalCriticals)
      return b.totalCriticals - a.totalCriticals;
    return a.service.service.localeCompare(b.service.service);
  });
  return out;
}

// ---------------------------------------------------------------------------
// Grouping — turn a flat ServiceMetrics[] into GroupedSet[].
//
//   "service":     one synthetic group, no label (flat list — preserves the
//                  pre-grouping behaviour).
//   "application": one group per applicationKey. Each service belongs to
//                  exactly one app, so no duplication.
//   "team":        one group per team. Multi-team services appear in each
//                  owning team's group so every owner sees shared findings.
//
// Groups are sorted by worst grade desc (D first), then by total open count
// desc, then alphabetically — so the most-attention-needed group floats to
// the top of the table on every render.
// ---------------------------------------------------------------------------

function groupRows(rows: ServiceMetrics[], groupBy: GroupBy): GroupedSet[] {
  if (groupBy === "service") {
    return [
      {
        key: "__all__",
        label: "",
        agg: aggregateGroup(rows),
        services: rows,
      },
    ];
  }

  const buckets = new Map<string, { label: string; services: ServiceMetrics[] }>();
  for (const r of rows) {
    if (groupBy === "application") {
      const key = r.service.applicationKey;
      const label = r.service.application;
      const b = buckets.get(key) ?? { label, services: [] };
      b.services.push(r);
      buckets.set(key, b);
    } else {
      for (const team of r.service.allTeams) {
        const b = buckets.get(team) ?? { label: teamLabel(team), services: [] };
        b.services.push(r);
        buckets.set(team, b);
      }
    }
  }

  const sortServices = (a: ServiceMetrics, b: ServiceMetrics) => {
    if (a.totalOpen !== b.totalOpen) return b.totalOpen - a.totalOpen;
    if (a.totalCriticals !== b.totalCriticals)
      return b.totalCriticals - a.totalCriticals;
    return a.service.service.localeCompare(b.service.service);
  };

  const groups: GroupedSet[] = [];
  for (const [key, { label, services }] of buckets) {
    services.sort(sortServices);
    groups.push({ key, label, agg: aggregateGroup(services), services });
  }
  groups.sort((a, b) => {
    const rankDiff = GRADE_RANK[b.agg.worstGrade] - GRADE_RANK[a.agg.worstGrade];
    if (rankDiff !== 0) return rankDiff;
    const openDiff =
      b.agg.totalCriticals + b.agg.totalHighs - (a.agg.totalCriticals + a.agg.totalHighs);
    if (openDiff !== 0) return openDiff;
    return a.label.localeCompare(b.label);
  });
  return groups;
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

export default function FindingsGroupedView({ initialData }: Props) {
  const router = useRouter();
  const searchParams = useSearchParams();

  // SLA filter mode (tri-state — see the FilterBar block above for the why).
  // The developer page reads the same param server-side and threads the
  // matching `sla_breached=true|false` into the /findings query, so the list
  // arriving here is pre-filtered. We mirror that intent by dropping zero-
  // total services in either mode — otherwise the table would still list
  // every clean dev-view service (the default-on full-footprint behaviour)
  // with all zeros, which fights the narrowing.
  const slaParam = searchParams.get("sla");
  const slaMode: SlaMode =
    slaParam === "breached"
      ? "breached"
      : slaParam === "within"
        ? "within"
        : "off";
  const slaActive = slaMode !== "off";

  // Active team selection from the URL (`?team=ccui`, possibly repeated). When
  // absent, narrow to all teams in the active pillar tab (`?pillar=`) so the
  // table matches TeamQuickPicker + server-side fetches.
  const selectionTeams = searchParams.getAll("team");
  const activePillar = resolveActiveDeveloperPillar(
    searchParams.get("pillar") ?? undefined,
    selectionTeams,
  );
  const effectiveTeams = effectiveDeveloperTeams(activePillar, selectionTeams);

  const [mode, setMode] = useState<ViewMode>("highlevel");
  // Default grouping is "application" — most generally useful organisation
  // regardless of active team scope. Eng managers / devs who pick their team
  // via the TeamQuickPicker still get a useful by-app view (most teams own
  // services across one or two apps); admins viewing everything see the full
  // app-by-app breakdown.
  const [groupBy, setGroupBy] = useState<GroupBy>("application");

  const findings = useMemo<FindingSummary[]>(
    () => initialData?.items ?? [],
    [initialData],
  );

  const scopedServices = useMemo(() => {
    const selected = new Set(effectiveTeams);
    return ALL_SERVICES.filter((s) =>
      s.allTeams.some((t) => selected.has(t)),
    );
  }, [effectiveTeams]);

  const metricsByService = useMemo(
    () => aggregateByService(scopedServices, findings),
    [scopedServices, findings],
  );

  const filteredRows = useMemo(
    () =>
      applyServiceFilters(metricsByService, {
        onlyNonEmpty: slaActive,
      }),
    [metricsByService, slaActive],
  );

  const groupedRows = useMemo(
    () => groupRows(filteredRows, groupBy),
    [filteredRows, groupBy],
  );
  const layoutFlags = useMemo(() => flagsForGroupBy(groupBy), [groupBy]);

  // ---- URL writes ----------------------------------------------------------
  //
  // Both writers below use `{ scroll: false }` — the SLA filter lives roughly
  // in the middle of a long /developer page, and Next.js's default behaviour
  // (scroll-to-top on every router.push) was yanking users away from the very
  // table they were trying to narrow. The data still re-fetches server-side
  // because `?sla=` is read in the page component; we only suppress the
  // viewport jump so the toggle feels like a filter, not a navigation.

  function onSlaModeChange(next: SlaMode) {
    const nextParams = new URLSearchParams(searchParams.toString());
    if (next === "off") {
      nextParams.delete("sla");
    } else {
      nextParams.set("sla", next);
    }
    router.push(nextParams.toString() ? `?${nextParams.toString()}` : ".", {
      scroll: false,
    });
  }

  function onClearAll() {
    // The bar now owns just the SLA toggle, so "clear filters" wipes that
    // one key. Team / asset scoping lives on TeamQuickPicker; we deliberately
    // don't touch those here — clearing the SLA filter shouldn't blow away
    // the user's active team selection.
    const next = new URLSearchParams(searchParams.toString());
    next.delete("sla");
    router.push(next.toString() ? `?${next.toString()}` : ".", {
      scroll: false,
    });
  }

  const showClear = slaActive;

  // Totals across visible rows (helps the user gauge the size of the slice
  // they're looking at).
  const visibleTotals = useMemo(
    () =>
      filteredRows.reduce(
        (acc, r) => ({
          crit: acc.crit + r.totalCriticals,
          high: acc.high + r.totalHighs,
          slaCrit: acc.slaCrit + r.criticalSlaBreached,
          slaHigh: acc.slaHigh + r.highSlaBreached,
        }),
        { crit: 0, high: 0, slaCrit: 0, slaHigh: 0 },
      ),
    [filteredRows],
  );

  return (
    // space-y-2.5 (was space-y-4) — the filter bar, group tabs, mode tabs+
    // summary and the table are all dense controls; the prior 16px gap was
    // luxurious. This tightens the stack so 3-4 service rows fit above the
    // fold on a standard MacBook viewport without changing what's shown.
    <div className="space-y-2.5">
      <FilterBar
        slaMode={slaMode}
        onSlaModeChange={onSlaModeChange}
        onClear={onClearAll}
        showClear={showClear}
      />

      <GroupByTabs group={groupBy} onChange={setGroupBy} />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <ModeTabs mode={mode} onChange={setMode} />
        <div className="text-sm text-neutral-400">
          Showing{" "}
          <span className="font-semibold text-neutral-100">
            {filteredRows.length}
          </span>{" "}
          of {scopedServices.length} services
          <span className="mx-2 text-neutral-700">·</span>
          <span className="text-red-700 dark:text-red-300">
            {visibleTotals.crit} critical
          </span>
          <span className="mx-1.5 text-neutral-700">/</span>
          <span className="text-amber-700 dark:text-amber-300">
            {visibleTotals.high} high
          </span>
          {(visibleTotals.slaCrit > 0 || visibleTotals.slaHigh > 0) && (
            <>
              <span className="mx-2 text-neutral-700">·</span>
              <span className="text-red-700 dark:text-red-300 font-medium">
                SLA breach: {visibleTotals.slaCrit} critical /{" "}
                {visibleTotals.slaHigh} high
              </span>
            </>
          )}
        </div>
      </div>

      {filteredRows.length === 0 ? (
        <div className="rounded-xl border border-white/5 bg-neutral-900/40 p-6 text-sm text-neutral-500">
          No services match the current filters.
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-white/5 shadow-sm">
          <table className="w-full">
            <thead className="bg-neutral-900/80">
              {mode === "highlevel" ? (
                <HighLevelHeader flags={layoutFlags} />
              ) : (
                <DetailedHeader flags={layoutFlags} />
              )}
              {mode === "detailed" && <DetailedSubHeader />}
            </thead>
            <tbody>
              {groupedRows.map((g, gIdx) => {
                const groupCell =
                  groupBy === "service"
                    ? undefined
                    : {
                        node: <GroupCell label={g.label} agg={g.agg} />,
                        rowSpan: g.services.length,
                      };
                return (
                  <Fragment key={g.key}>
                    {g.services.map((m, sIdx) => {
                      const cell = sIdx === 0 ? groupCell : undefined;
                      const boundary = sIdx === 0 && gIdx > 0;
                      const key = `${g.key}::${m.service.service}`;
                      return mode === "highlevel" ? (
                        <HighLevelRow
                          key={key}
                          m={m}
                          flags={layoutFlags}
                          groupCell={cell}
                          isGroupBoundary={boundary}
                        />
                      ) : (
                        <DetailedRow
                          key={key}
                          m={m}
                          flags={layoutFlags}
                          groupCell={cell}
                          isGroupBoundary={boundary}
                        />
                      );
                    })}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
