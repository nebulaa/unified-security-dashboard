"use client";

import { useDeferredValue, useMemo, useState } from "react";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { clientFetch } from "../lib/api/client";
import type {
  FilterState,
  FindingListResponse,
  FindingSummary,
  Severity,
  SlaFilter,
  Status,
  TeamListResponse,
} from "../lib/types";
import {
  DEFAULT_OPEN_STATUSES,
  DEFAULT_SEVERITIES,
} from "../lib/findings-defaults";
import SeverityPill from "./SeverityPill";
import StatusPill from "./StatusPill";

type SortKey =
  | "severity"
  | "status"
  | "title"
  | "asset"
  | "team"
  | "source"
  | "age"
  | "sla";

type SortDir = "asc" | "desc";

// First-render filter state. Sourced from the shared module so the SSR pages
// (which can't import this client file) and the client stay in lockstep.
const DEFAULT_FILTERS: FilterState = { severities: DEFAULT_SEVERITIES };

interface Props {
  initialData?: FindingListResponse;
  /** Seed the filter state on first render (user can still change it). */
  initialFilters?: FilterState;
  /** Locked filters that the user can't change (e.g. team="unowned" on admin). */
  lockedParams?: Partial<FilterState>;
  /**
   * Locked union-team filter — emits `team=a&team=b&...` in the query and hides
   * the team selector in the filter bar. Used by /platform to pin multiple
   * teams. When set, takes precedence
   * over `lockedParams.team` for query construction.
   */
  lockedTeams?: readonly string[];
  /** Locked source union — emits repeated `source=` params. */
  lockedSources?: readonly string[];
  /** Extra immutable query params to inject (e.g. limit=200). */
  extraParams?: Record<string, string>;
  /** Hide columns that are always identical (e.g. team col on the developer view). */
  hideColumns?: Set<"team" | "source">;
}

const SEVERITY_OPTIONS: Severity[] = ["critical", "high", "medium", "low", "info"];
const STATUS_OPTIONS: Status[] = [
  "open",
  "triaged",
  "in_progress",
  "fixed",
  "auto_closed",
  "risk_accepted",
  "suppressed",
];
// `sonarcloud_trivy` is admin-only on the backend (the /findings endpoint
// returns 403 for non-admins requesting it). Listing it in the dropdown lets
// admins filter explicitly when they're already on /admin; on every other
// page the row scope strips it out via apply_finding_scope, so a non-admin
// who happens to pick it from the dropdown just sees a 403 / empty list.
const SOURCE_OPTIONS = [
  "dependabot",
  "sonarcloud",
  "sonarcloud_trivy",
  "trivy",
  "wiz",
  "nuclei",
  "vanta",
  "pentest",
];

function ageLabel(days: number): string {
  if (days < 1) return `${Math.round(days * 24)}h`;
  if (days < 30) return `${Math.round(days)}d`;
  if (days < 365) return `${Math.round(days / 30)}mo`;
  return `${(days / 365).toFixed(1)}y`;
}

function buildQuery(
  filters: FilterState,
  sort: { by: SortKey; dir: SortDir },
  locked: Partial<FilterState>,
  lockedTeams: readonly string[],
  lockedSources: readonly string[],
  extra: Record<string, string>,
): string {
  // Use URLSearchParams.append() so we can emit `severity` (and any other repeatable
  // param) multiple times — FastAPI parses repeated values into a list.
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(extra)) params.append(k, v);

  const all: FilterState = { ...filters, ...locked };
  for (const s of all.severities ?? []) params.append("severity", s);
  if (all.status) {
    params.append("status", all.status);
  } else {
    for (const s of DEFAULT_OPEN_STATUSES) params.append("status", s);
  }
  // lockedTeams (multi-team union) wins over single-team filter state when set
  // — used by /platform pillar tabs (locked team union per tab).
  if (lockedTeams.length > 0) {
    for (const t of lockedTeams) params.append("team", t);
  } else if (all.team) {
    params.append("team", all.team);
  }
  if (lockedSources.length > 0) {
    for (const s of lockedSources) params.append("source", s);
  } else if (all.source) {
    params.append("source", all.source);
  }
  if (all.title) params.append("title", all.title);
  if (all.asset) params.append("asset", all.asset);
  if (all.sla === "breached") params.append("sla_breached", "true");
  if (all.sla === "ok") params.append("sla_breached", "false");
  params.append("sort_by", sort.by);
  params.append("sort_dir", sort.dir);

  return params.toString();
}

function SortHeader({
  label,
  col,
  sort,
  setSort,
  align = "left",
}: {
  label: string;
  col: SortKey;
  sort: { by: SortKey; dir: SortDir };
  setSort: (s: { by: SortKey; dir: SortDir }) => void;
  align?: "left" | "right";
}) {
  const active = sort.by === col;
  const arrow = !active ? "" : sort.dir === "asc" ? " ↑" : " ↓";
  const onClick = () =>
    setSort({
      by: col,
      dir: !active ? defaultDir(col) : sort.dir === "asc" ? "desc" : "asc",
    });
  return (
    <th
      className={`select-none px-3 py-2 text-${align} ${
        active ? "text-neutral-100" : "text-neutral-400"
      } cursor-pointer hover:text-neutral-100`}
      onClick={onClick}
    >
      {label}
      {arrow}
    </th>
  );
}

function defaultDir(col: SortKey): SortDir {
  return col === "age" || col === "sla" ? "desc" : "asc";
}

export default function FindingsTable({
  initialData,
  initialFilters,
  lockedParams = {},
  lockedTeams = [],
  lockedSources = [],
  extraParams = { limit: "200" },
  hideColumns = new Set(),
}: Props) {
  const [filters, setFilters] = useState<FilterState>(initialFilters ?? DEFAULT_FILTERS);
  const [sort, setSort] = useState<{ by: SortKey; dir: SortDir }>({
    by: "severity",
    dir: "asc",
  });

  // Defer text-input filters so React Query doesn't re-fetch on every keystroke;
  // dropdown changes still feel instant because they bypass the deferred path.
  const deferredFilters = useDeferredValue(filters);

  const queryString = useMemo(
    () =>
      buildQuery(
        deferredFilters,
        sort,
        lockedParams,
        lockedTeams,
        lockedSources,
        extraParams,
      ),
    [deferredFilters, sort, lockedParams, lockedTeams, lockedSources, extraParams],
  );

  // Use the SSR-prefetched data only on the very first render (no filters or sort
  // changed from the documented defaults). The server pages MUST fetch with the
  // same defaults — see server/page.tsx callers.
  const isPristine =
    JSON.stringify(deferredFilters) === JSON.stringify(DEFAULT_FILTERS) &&
    sort.by === "severity" &&
    sort.dir === "asc";

  const { data, isFetching } = useQuery<FindingListResponse>({
    queryKey: ["findings", queryString],
    queryFn: () => clientFetch<FindingListResponse>(`/findings?${queryString}`),
    initialData: isPristine ? initialData : undefined,
    placeholderData: keepPreviousData,
    staleTime: 5 * 60_000,
  });

  // Team list is small (~25 teams) and rarely changes — load once, cache long.
  // Failures fall back to an empty list so the dropdown silently degrades to just
  // "All teams" + "unowned" rather than blocking the whole table.
  const { data: teamList } = useQuery<TeamListResponse>({
    queryKey: ["teams"],
    queryFn: () => clientFetch<TeamListResponse>("/teams"),
    staleTime: 30 * 60_000,
  });

  const items: FindingSummary[] = data?.items ?? [];
  const total = data?.total ?? 0;

  return (
    <div className="space-y-3">
      <FiltersBar
        filters={filters}
        setFilters={setFilters}
        lockedParams={lockedParams}
        teamLocked={lockedTeams.length > 0 || !!lockedParams.team}
        sourceLocked={lockedSources.length > 0 || !!lockedParams.source}
        assetLocked={!!lockedParams.asset}
        showTeam={!hideColumns.has("team")}
        showSource={!hideColumns.has("source")}
        teams={teamList?.items ?? []}
      />

      <div className="flex items-center justify-between text-xs text-neutral-500">
        <div>
          {total.toLocaleString()} match{total === 1 ? "" : "es"}
          {items.length < total && ` · showing first ${items.length}`}
        </div>
        {isFetching && <div className="text-neutral-400">loading…</div>}
      </div>

      {items.length === 0 ? (
        <div className="rounded border border-neutral-800 bg-neutral-900/40 p-6 text-sm text-neutral-500">
          no findings match the current filters
        </div>
      ) : (
        <div className="overflow-hidden rounded border border-neutral-800">
          <table className="w-full text-sm">
            <thead className="bg-neutral-900/80 text-xs uppercase tracking-wide">
              <tr>
                <SortHeader label="Severity" col="severity" sort={sort} setSort={setSort} />
                <SortHeader label="Status" col="status" sort={sort} setSort={setSort} />
                <SortHeader label="Title" col="title" sort={sort} setSort={setSort} />
                <SortHeader label="Asset" col="asset" sort={sort} setSort={setSort} />
                {!hideColumns.has("team") && (
                  <SortHeader label="Team" col="team" sort={sort} setSort={setSort} />
                )}
                {!hideColumns.has("source") && (
                  <SortHeader label="Source" col="source" sort={sort} setSort={setSort} />
                )}
                <SortHeader label="Age" col="age" sort={sort} setSort={setSort} align="right" />
                <SortHeader label="SLA" col="sla" sort={sort} setSort={setSort} align="right" />
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-900">
              {items.map((f) => (
                <tr key={f.id} className="bg-neutral-950/40 hover:bg-neutral-900/40">
                  <td className="px-3 py-2">
                    <SeverityPill severity={f.severity} />
                  </td>
                  <td className="px-3 py-2">
                    <StatusPill status={f.status} />
                  </td>
                  <td className="px-3 py-2">
                    <div className="text-neutral-100">{f.title}</div>
                    {f.cve_id && (
                      <div className="text-xs text-neutral-500">{f.cve_id}</div>
                    )}
                  </td>
                  <td className="px-3 py-2 text-neutral-300">{f.asset_display}</td>
                  {!hideColumns.has("team") && (
                    <td className="px-3 py-2 text-neutral-300">{f.owner_team}</td>
                  )}
                  {!hideColumns.has("source") && (
                    <td className="px-3 py-2 text-neutral-400">{f.source}</td>
                  )}
                  <td className="px-3 py-2 text-right text-neutral-300">
                    {ageLabel(f.age_days)}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {f.sla_breached ? (
                      <span className="text-red-700 dark:text-red-400">breached</span>
                    ) : (
                      <span className="text-emerald-700 dark:text-emerald-400">ok</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function SeverityPillsToggle({
  selected,
  onChange,
}: {
  selected: Severity[];
  onChange: (next: Severity[]) => void;
}) {
  // Visual style per severity matches SeverityPill so users get the same color cue
  // they'll see in the table rows.
  const styleFor = (s: Severity, on: boolean): string => {
    const base =
      "rounded border px-2 py-0.5 text-xs uppercase tracking-wide cursor-pointer select-none transition-colors";
    if (!on) {
      return `${base} border-neutral-700 bg-neutral-950 text-neutral-500 hover:border-neutral-500 hover:text-neutral-300`;
    }
    // Selected-state pills keep the semantic palette in both themes; the
    // pale 50/300 ramp end carries the chip in light mode, the deep 950/700
    // ramp end keeps the legacy dark look.
    const tones: Record<Severity, string> = {
      critical:
        "border-red-300 bg-red-50 text-red-700 dark:border-red-700 dark:bg-red-950 dark:text-red-300",
      high:
        "border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-300",
      medium:
        "border-yellow-300 bg-yellow-50 text-yellow-700 dark:border-yellow-700 dark:bg-yellow-950 dark:text-yellow-300",
      low:
        "border-sky-300 bg-sky-50 text-sky-700 dark:border-sky-700 dark:bg-sky-950 dark:text-sky-300",
      info: "border-neutral-600 bg-neutral-900 text-neutral-300",
    };
    return `${base} ${tones[s]}`;
  };

  const toggle = (s: Severity) => {
    if (selected.includes(s)) onChange(selected.filter((x) => x !== s));
    else onChange([...selected, s]);
  };

  return (
    <div className="flex items-center gap-1">
      {SEVERITY_OPTIONS.map((s) => (
        <button
          key={s}
          type="button"
          className={styleFor(s, selected.includes(s))}
          onClick={() => toggle(s)}
          aria-pressed={selected.includes(s)}
        >
          {s}
        </button>
      ))}
    </div>
  );
}

function TeamSelect({
  value,
  onChange,
  teams,
}: {
  value: string;
  onChange: (v: string) => void;
  teams: import("../lib/types").TeamItem[];
}) {
  // Group by pillar. `unowned` always lives at the top so it is one click away.
  const grouped = useMemo(() => {
    const byPillar = new Map<
      string,
      { pillarName: string; teams: import("../lib/types").TeamItem[] }
    >();
    for (const t of teams) {
      if (t.name === "unowned") continue;
      const key = t.pillar ?? "__none__";
      const label = t.pillar_name ?? (t.pillar ? t.pillar : "Other");
      if (!byPillar.has(key)) byPillar.set(key, { pillarName: label, teams: [] });
      byPillar.get(key)!.teams.push(t);
    }
    return Array.from(byPillar.entries()).map(([key, v]) => ({ key, ...v }));
  }, [teams]);

  const hasUnowned = teams.some((t) => t.name === "unowned");

  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
    >
      <option value="">All teams</option>
      {hasUnowned && <option value="unowned">unowned (no team)</option>}
      {grouped.map((g) => (
        <optgroup key={g.key} label={g.pillarName}>
          {g.teams.map((t) => (
            <option key={t.name} value={t.name}>
              {t.display_name ?? t.name}
            </option>
          ))}
        </optgroup>
      ))}
    </select>
  );
}

function FiltersBar({
  filters,
  setFilters,
  lockedParams,
  teamLocked,
  sourceLocked,
  assetLocked,
  showTeam,
  showSource,
  teams,
}: {
  filters: FilterState;
  setFilters: (f: FilterState) => void;
  lockedParams: Partial<FilterState>;
  teamLocked: boolean;
  sourceLocked: boolean;
  /** When true, the page pinned an `?asset=` filter (e.g. dev-view deep
   *  link from a service row); hide the input so typing in it doesn't look
   *  like it does something while the locked param keeps winning. */
  assetLocked: boolean;
  showTeam: boolean;
  showSource: boolean;
  teams: import("../lib/types").TeamItem[];
}) {
  const update = (patch: Partial<FilterState>) => setFilters({ ...filters, ...patch });
  // Two distinct affordances:
  //   - "Clear all"          → wipe to {} (no filters at all, even severity)
  //   - "Reset to defaults"  → restore the curated default view (critical + high)
  // The first is for "show me literally everything", the second is the natural
  // undo for the curated default; both show only when meaningful.
  const isEmpty = Object.values(filters).every(
    (v) => v === undefined || v === "" || (Array.isArray(v) && v.length === 0),
  );
  const isDefault = JSON.stringify(filters) === JSON.stringify(DEFAULT_FILTERS);

  return (
    <div className="space-y-3 rounded border border-neutral-800 bg-neutral-900/40 p-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <span className="text-xs uppercase tracking-wide text-neutral-500">
          severity
        </span>
        <SeverityPillsToggle
          selected={filters.severities ?? []}
          onChange={(next) => update({ severities: next })}
        />
        <div className="ml-auto">
          <button
            type="button"
            onClick={() => setFilters({})}
            disabled={isEmpty}
            className="rounded border border-neutral-700 bg-neutral-950 px-3 py-1 text-xs uppercase tracking-wide text-neutral-300 transition-colors hover:border-neutral-500 hover:text-neutral-100 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:border-neutral-700 disabled:hover:text-neutral-300"
            title="Clear every filter, including severity"
          >
            clear all filters
          </button>
        </div>
      </div>

      <div className="grid gap-2 md:grid-cols-3 lg:grid-cols-6">
        <input
          type="text"
          placeholder="Title contains…"
          value={filters.title ?? ""}
          onChange={(e) => update({ title: e.target.value || undefined })}
          className="rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100 placeholder:text-neutral-500"
        />
        {!assetLocked && (
          <input
            type="text"
            placeholder="Asset contains…"
            value={filters.asset ?? ""}
            onChange={(e) => update({ asset: e.target.value || undefined })}
            className="rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100 placeholder:text-neutral-500"
          />
        )}
        <select
          value={filters.status ?? ""}
          onChange={(e) =>
            update({ status: (e.target.value || undefined) as Status | undefined })
          }
          className="rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
        >
          <option value="">Open (default)</option>
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        {showTeam && !teamLocked && (
          <TeamSelect
            value={filters.team ?? ""}
            onChange={(v) => update({ team: v || undefined })}
            teams={teams}
          />
        )}
        {showSource && !sourceLocked && (
          <select
            value={filters.source ?? ""}
            onChange={(e) => update({ source: e.target.value || undefined })}
            className="rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
          >
            <option value="">All sources</option>
            {SOURCE_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        )}
        <select
          value={filters.sla ?? "any"}
          onChange={(e) => update({ sla: (e.target.value as SlaFilter) || "any" })}
          className="rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
        >
          <option value="any">SLA: any</option>
          <option value="breached">SLA: breached</option>
          <option value="ok">SLA: ok</option>
        </select>
      </div>

      {!isDefault && (
        <div>
          <button
            type="button"
            onClick={() => setFilters(DEFAULT_FILTERS)}
            className="text-xs text-neutral-400 underline-offset-2 hover:text-neutral-200 hover:underline"
          >
            reset to defaults (critical + high)
          </button>
        </div>
      )}
    </div>
  );
}
