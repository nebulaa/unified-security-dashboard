// ---------------------------------------------------------------------------
// Shared scaffolding for /platform routes:
//   /platform                  → Overview (ratings + trend) per product pillar
//   /platform/wiz              → Wiz findings by category
//   /platform/findings         → Explore findings
//   /platform/threat-intel     → Org-wide Threat Center advisories (flat list)
//
// Product pillar tab (`?pillar=`) is owned by PlatformPillarNav; sub-nav tabs
// preserve it when switching between Overview and Explore findings.
// Threat intel is a separate top-level section (PlatformSectionNav).
// ---------------------------------------------------------------------------

import { serverFetch } from "../lib/api/server";
import { defaultFindingsQuery } from "../lib/findings-defaults";
import {
  developerPillarLabel,
  resolvePlatformScope,
  THREAT_INTEL_PILLAR,
  type ProductPlatformPillarTab,
} from "../lib/team-roles";
import type {
  FilterState,
  FindingListResponse,
  MetricsTrend,
  SecurityPosture,
  WizFindingsByCategoryResponse,
} from "../lib/types";

export type ComponentRegistryIndexes = {
  wiz_service_to_team: Record<string, string>;
  wiz_teams_for_pillar: Record<string, string[]>;
};

async function loadRegistryIndexes(): Promise<ComponentRegistryIndexes> {
  const data = await serverFetch<{ indexes: ComponentRegistryIndexes }>(
    "/components",
  );
  return data.indexes;
}

/** Minimal scope line under the page title — active pillar tab only. */
export function buildPlatformSubtitle(pillar: ProductPlatformPillarTab): string {
  return developerPillarLabel(pillar);
}

/** Legacy deep links used `?pillar=threat-intel` on product-line routes. */
export function isThreatIntelPillarParam(
  sp: Record<string, string | string[]>,
): boolean {
  return toScalar(sp.pillar) === THREAT_INTEL_PILLAR;
}

export function toScalar(
  value: string | string[] | undefined,
): string | undefined {
  if (value == null) return undefined;
  return Array.isArray(value) ? value[0] : value;
}

export function scopeQueryString(
  teams: readonly string[],
  sources: readonly string[] | undefined,
): string {
  const parts: string[] = [];
  for (const t of teams) parts.push(`team=${encodeURIComponent(t)}`);
  if (sources) {
    for (const s of sources) parts.push(`source=${encodeURIComponent(s)}`);
  }
  return parts.join("&");
}

export interface PlatformScope {
  pillarParam: string | undefined;
  pillar: ReturnType<typeof resolvePlatformScope>["pillar"];
  codeTeams: readonly string[];
  wizTeams: readonly string[];
  teams: readonly string[];
  sources: readonly string[] | undefined;
  label: string;
  sourceHint: string;
  scopeQs: string;
  postureScopeQs: string;
  source: string | undefined;
  severity: string | undefined;
  initialFilters: FilterState | undefined;
  findingsExtra: Record<string, string | readonly string[]>;
}

export async function resolvePlatformPageScope(
  sp: Record<string, string | string[]>,
): Promise<PlatformScope> {
  const pillarParam = toScalar(sp.pillar);
  const indexes = await loadRegistryIndexes();
  const pillarScope = resolvePlatformScope(
    pillarParam,
    indexes.wiz_teams_for_pillar,
  );
  const { teams, sources, label, sourceHint, pillar, codeTeams, wizTeams } =
    pillarScope;

  const source = toScalar(sp.source);
  const severity = toScalar(sp.severity);
  const slaBreached = toScalar(sp.sla_breached) === "true";
  let initialFilters: FilterState | undefined =
    source || severity
      ? {
          source,
          severities: severity
            ? ([severity] as FilterState["severities"])
            : undefined,
        }
      : undefined;
  if (slaBreached) {
    initialFilters = { ...initialFilters, sla: "breached" };
  }

  // Trend + posture: pillar + teams only (not code-only source=dependabot|sonarcloud).
  const scopeQs = [
    `platform_pillar=${encodeURIComponent(pillar)}`,
    ...teams.map((t) => `team=${encodeURIComponent(t)}`),
  ].join("&");
  const postureScopeQs = scopeQs;

  const wizCategory = toScalar(sp.wiz_category);

  const findingsExtra: Record<string, string | readonly string[]> = {
    team: teams,
    limit: "200",
    platform_pillar: pillar,
    ...(source ? { source } : {}),
    ...(wizCategory ? { wiz_category: wizCategory } : {}),
  };
  if (slaBreached) {
    findingsExtra.sla_breached = "true";
  }

  return {
    pillarParam,
    pillar,
    codeTeams,
    wizTeams,
    teams,
    sources,
    label,
    sourceHint,
    scopeQs,
    postureScopeQs,
    source,
    severity,
    initialFilters,
    findingsExtra,
  };
}

/** Org-wide Wiz Threat Center advisories for `/platform/threat-intel`. */
export async function loadPlatformThreatIntelFindings(): Promise<FindingListResponse> {
  return serverFetch<FindingListResponse>(
    `/findings?${defaultFindingsQuery({
      platform_pillar: THREAT_INTEL_PILLAR,
      source: "wiz",
      status: "open",
      limit: "200",
    })}`,
  );
}

export async function loadPlatformOverviewMetrics(
  scope: PlatformScope,
): Promise<{ posture: SecurityPosture; trend: MetricsTrend }> {
  const postureParams = new URLSearchParams(scope.postureScopeQs);
  // Overview Wiz card: Issues only — full category breakdown lives on /platform/wiz.
  postureParams.set("platform_wiz_issues_only", "true");
  const trendParams = new URLSearchParams(scope.scopeQs);
  trendParams.set("platform_wiz_issues_only", "true");
  const [posture, trend] = await Promise.all([
    serverFetch<SecurityPosture>(
      `/metrics/security-posture?${postureParams.toString()}`,
    ),
    serverFetch<MetricsTrend>(
      `/metrics/trend?days=30&${trendParams.toString()}`,
    ),
  ]);
  return { posture, trend };
}

export async function loadPlatformFindingsList(
  findingsExtra: Record<string, string | readonly string[]>,
): Promise<FindingListResponse> {
  return serverFetch<FindingListResponse>(
    `/findings?${defaultFindingsQuery(findingsExtra)}`,
  );
}

/** Wiz tab: grouped by wiz_category with portal deep links. */
export async function loadPlatformWizByCategory(
  scope: PlatformScope,
): Promise<WizFindingsByCategoryResponse> {
  const params = new URLSearchParams();
  params.set("platform_pillar", scope.pillar);
  for (const t of scope.teams) {
    params.append("team", t);
  }
  if (scope.severity) {
    params.append("severity", scope.severity);
  }
  // Category pillar tabs filter client-side; API must return all groups for counts.
  if (toScalar(scope.findingsExtra.sla_breached as string) === "true") {
    params.set("sla_breached", "true");
  }
  return serverFetch<WizFindingsByCategoryResponse>(
    `/findings/wiz-by-category?${params.toString()}`,
  );
}

/** Query string suffix for sub-nav links (pillar + active filters). */
export function platformNavQueryString(
  sp: Record<string, string | string[]>,
): string {
  const params = new URLSearchParams();
  const pillar = toScalar(sp.pillar);
  if (pillar) params.set("pillar", pillar);
  const source = toScalar(sp.source);
  const severity = toScalar(sp.severity);
  const wizCategory = toScalar(sp.wiz_category);
  if (source) params.set("source", source);
  if (severity) params.set("severity", severity);
  if (wizCategory) params.set("wiz_category", wizCategory);
  if (toScalar(sp.sla_breached) === "true") {
    params.set("sla_breached", "true");
  }
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}
