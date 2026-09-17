// ---------------------------------------------------------------------------
// Shared scaffolding for the /developer routes:
//   /developer            → Overview     (ratings + trend)
//   /developer/services   → Security by service
//   /developer/findings   → Explore findings (all sources, including Wiz)
//
// All three pages read the same URL conventions, build the same scope, and
// render the same header + scope picker. This module centralises that so
// each route only owns its own panel-specific JSX and fetches.
//
// URL conventions (mirror of the original /developer page.tsx docstring):
//
//   ?pillar=product|retail|data Active pillar tab (Product default).
//   ?team=<key>[&team=<key>]    Narrow every metric and finding to the union
//                               of the listed teams.
//   ?asset=<substring>          Narrow to findings whose asset_display matches
//                               (ILIKE).
//   ?source=<key>&severity=<s>  Per-source deep links from the 4-up rating
//                               row and the per-severity findings card.
//   ?sla=breached|within        FindingsGroupedView's tri-state SLA filter;
//                               threaded into the /findings query.
//   ?details=open               Forces the findings tab/disclosure open.
//
// The leading underscore on this filename keeps Next.js from picking it up as
// a route.
// ---------------------------------------------------------------------------

import { serverFetch } from "../lib/api/server";
import { defaultFindingsQuery } from "../lib/findings-defaults";
import {
  effectiveDeveloperTeams,
  resolveActiveDeveloperPillar,
} from "../lib/developer-scope";
import {
  developerPillarLabel,
  filterToDeveloperViewTeams,
  type DeveloperPillarTab,
} from "../lib/team-roles";
import {
  ALL_APPLICATIONS,
  ALL_SERVICES,
  DEV_VIEW_TEAM_KEYS,
  teamLabel,
} from "../lib/component-map";
import type {
  FilterState,
  FindingListResponse,
  Me,
  MetricsTrend,
  SecurityPosture,
  TeamListResponse,
} from "../lib/types";

// ---- URL param parsing ----------------------------------------------------

export function toList(value: string | string[] | undefined): string[] {
  if (value == null) return [];
  return Array.isArray(value) ? value : [value];
}

export function toScalar(
  value: string | string[] | undefined,
): string | undefined {
  if (value == null) return undefined;
  return Array.isArray(value) ? value[0] : value;
}

export function appendParams(
  path: string,
  params: Array<[string, string]>,
): string {
  if (params.length === 0) return path;
  const sep = path.includes("?") ? "&" : "?";
  const enc = params
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
    .join("&");
  return `${path}${sep}${enc}`;
}

export type SlaMode = "off" | "breached" | "within";

// ---- Selection narration --------------------------------------------------

/** Translate the active selection into a friendly subtitle for the page
 *  header. An `?asset=<repo>` can either narrow to one service (single-
 *  service repo) or span multiple services. Detect the multi-service case and
 *  label it as a repo-level selection. Wording is terse — these strings sit
 *  in the page subtitle slot and need to read at a glance. */
export function describeSelection(
  teams: string[],
  asset: string | undefined,
): string | null {
  if (asset) {
    const repoMatches = ALL_SERVICES.filter((s) => s.repo === asset);
    if (repoMatches.length > 1) {
      return `Repo · ${asset} · ${repoMatches.length} services`;
    }
    const svc = ALL_SERVICES.find(
      (s) => s.repo === asset || s.sonarProjects.includes(asset),
    );
    return svc
      ? `Service · ${svc.service} · ${svc.application}`
      : `Asset · ${asset}`;
  }
  if (teams.length === 1) return `Team · ${teamLabel(teams[0])}`;
  if (teams.length > 1) {
    const app = ALL_APPLICATIONS.find(
      (a) =>
        a.teams.length === teams.length &&
        a.teams.every((t) => teams.includes(t)),
    );
    if (app) return `Application · ${app.label}`;
    return `${teams.length} teams · ${teams.map(teamLabel).join(" · ")}`;
  }
  return null;
}

// ---- Scope resolver -------------------------------------------------------

export interface DeveloperScope {
  /** Active pillar tab (from `?pillar=` or inferred from `?team=`). */
  pillar: DeveloperPillarTab;
  /** Raw selection from `?team=` (may be empty). */
  selectionTeams: string[];
  /** Raw `?asset=` value (may be undefined). */
  selectionAsset: string | undefined;
  /** Effective team scope: explicit `?team=` selections, or all teams in `pillar`. */
  effectiveTeams: readonly string[];
  /** Params passed to every metrics + findings fetch on a developer tab. */
  scopeParams: Array<[string, string]>;
  /** Tri-state SLA narrowing (FindingsGroupedView pill). */
  slaMode: SlaMode;
  slaActive: boolean;
  /** Per-source deep-link state. */
  source: string | undefined;
  severity: string | undefined;
  initialFilters: FilterState | undefined;
  /** Whether the "Explore findings" tab/disclosure should default-open. */
  detailsOpen: boolean;
}

export function resolveDeveloperScope(
  sp: Record<string, string | string[]>,
): DeveloperScope {
  const selectionTeams = toList(sp.team);
  const selectionAsset = toScalar(sp.asset);
  const pillar = resolveActiveDeveloperPillar(
    toScalar(sp.pillar),
    selectionTeams,
  );

  const slaParam = toScalar(sp.sla);
  const slaMode: SlaMode =
    slaParam === "breached"
      ? "breached"
      : slaParam === "within"
        ? "within"
        : "off";
  const slaActive = slaMode !== "off";

  const source = toScalar(sp.source);
  const severity = toScalar(sp.severity);
  const initialFilters: FilterState | undefined =
    source || severity
      ? {
          source,
          severities: severity
            ? ([severity] as FilterState["severities"])
            : undefined,
        }
      : undefined;

  const detailsOpen =
    sp.details === "open" ||
    !!source ||
    !!severity ||
    selectionTeams.length > 0 ||
    !!selectionAsset ||
    slaActive;

  // Default scope = all teams in the active pillar tab. Explicit ?team=
  // selections take over.
  const effectiveTeams = effectiveDeveloperTeams(pillar, selectionTeams);

  const scopeParams: Array<[string, string]> = effectiveTeams.map(
    (t) => ["team", t] as [string, string],
  );
  if (selectionAsset) scopeParams.push(["asset", selectionAsset]);

  return {
    pillar,
    selectionTeams,
    selectionAsset,
    effectiveTeams,
    scopeParams,
    slaMode,
    slaActive,
    source,
    severity,
    initialFilters,
    detailsOpen,
  };
}

// ---- Per-page fetch helpers ----------------------------------------------

/** /me + /teams + the developer-view filtered team list. Every developer
 *  tab needs this for the TeamQuickPicker and subtitle, so we fetch it once
 *  via the per-page Promise.all next to the tab-specific data. */
export async function loadDeveloperIdentity(): Promise<{
  me: Me;
  teamList: TeamListResponse;
  developerTeams: string[];
  isAdmin: boolean;
}> {
  const [me, teamList] = await Promise.all([
    serverFetch<Me>("/me"),
    serverFetch<TeamListResponse>("/teams"),
  ]);
  const pillarByTeam = new Map(
    teamList.items.map((t) => [t.name, t.pillar] as const),
  );
  // No per-user team list any more — every authenticated user gets the full
  // dev-view team set as their default scope. The TeamQuickPicker reads
  // this list to render its chips.
  const developerTeams = filterToDeveloperViewTeams(
    [...DEV_VIEW_TEAM_KEYS],
    pillarByTeam,
  );
  return { me, teamList, developerTeams, isAdmin: me.is_admin };
}

/** Posture + 30-day trend (no findings list). Used by the Overview tab. */
export async function loadOverviewMetrics(
  scope: DeveloperScope,
): Promise<{ posture: SecurityPosture; trend: MetricsTrend }> {
  const [posture, trend] = await Promise.all([
    serverFetch<SecurityPosture>(
      appendParams("/metrics/security-posture", scope.scopeParams),
    ),
    serverFetch<MetricsTrend>(
      appendParams("/metrics/trend?days=30", scope.scopeParams),
    ),
  ]);
  return { posture, trend };
}

/** Query string suffix for sub-nav links (team/asset + active filters). */
export function developerNavQueryString(
  sp: Record<string, string | string[]>,
): string {
  const params = new URLSearchParams();
  const pillar = toScalar(sp.pillar);
  if (pillar && pillar !== "product") params.set("pillar", pillar);
  for (const t of toList(sp.team)) {
    params.append("team", t);
  }
  const asset = toScalar(sp.asset);
  const source = toScalar(sp.source);
  const severity = toScalar(sp.severity);
  if (asset) params.set("asset", asset);
  if (source) params.set("source", source);
  if (severity) params.set("severity", severity);
  if (toScalar(sp.sla) === "breached") params.set("sla", "breached");
  else if (toScalar(sp.sla) === "within") params.set("sla", "within");
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

/** Findings list narrowed by scope + per-source + SLA. Used by the Services
 *  and Findings tabs. Metrics endpoints don't accept the SLA filter, so
 *  Overview tab does NOT receive a pre-narrowed posture even when ?sla= is
 *  set — that's intentional ("absolute posture" stays honest while the
 *  service/findings tabs respect the narrowing). */
export async function loadFindingsList(
  scope: DeveloperScope,
): Promise<FindingListResponse> {
  const findingsQuery = defaultFindingsQuery({ limit: "200" });
  const findingsParams: Array<[string, string]> = [...scope.scopeParams];
  if (scope.source) findingsParams.push(["source", scope.source]);
  if (scope.severity) findingsParams.push(["severity", scope.severity]);
  if (scope.slaMode === "breached") {
    findingsParams.push(["sla_breached", "true"]);
  } else if (scope.slaMode === "within") {
    findingsParams.push(["sla_breached", "false"]);
  }
  return serverFetch<FindingListResponse>(
    appendParams(`/findings?${findingsQuery}`, findingsParams),
  );
}

// ---- Subtitle composer ---------------------------------------------------

/** Build the per-page subtitle string. Precedence:
 *    1. Active selection wins (most specific narration of "you're looking at
 *       X right now").
 *    2. Otherwise describe the structural scope as "All teams" — the
 *       TeamQuickPicker right below already shows the per-team chips for
 *       narrowing, so enumerating 16+ team keys would just be noise.
 *    3. Append SLA narrowing (cross-cutting) AFTER the scope label.
 *
 * `isAdmin` and `developerTeams` were used by the old role-shaped fallback
 * and are kept on the signature for callsite stability; today both paths
 * fall through to "All teams" so the parameters go unread.
 */
export function buildSubtitle(
  scope: DeveloperScope,
  _isAdmin: boolean,
  _developerTeams: string[],
): string {
  const selectionLabel = describeSelection(
    scope.selectionTeams,
    scope.selectionAsset,
  );
  let subtitle = selectionLabel
    ? `Filtered · ${selectionLabel}`
    : `${developerPillarLabel(scope.pillar)} · all teams`;
  if (scope.slaMode === "breached") {
    subtitle = `${subtitle} · SLA breaches only`;
  } else if (scope.slaMode === "within") {
    subtitle = `${subtitle} · Within SLA only`;
  }
  return subtitle;
}
