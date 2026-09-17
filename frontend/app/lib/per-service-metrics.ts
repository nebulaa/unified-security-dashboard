/**
 * Per-service security metrics derived from the loaded findings list.
 *
 * The backend's `/metrics/security-posture` emits ONE rating per source for
 * the active RBAC + selection scope (see `_compute_source_rating` in
 * `backend/app/api/routes_metrics.py`). The Developer view's per-service
 * table needs *per-service* ratings — i.e. each row gets its own A-D grade
 * based only on that service's findings.
 *
 * Rather than add an N-row variant to the backend, this module mirrors the
 * grading ladders on the frontend and applies them to the subset
 * of findings that maps to each service. The findings list is already loaded
 * server-side (capped at 200 crit+high in scope), so the math is local +
 * cheap.
 *
 * CAVEAT: if the loaded findings list is truncated (= the backend has more
 * than `limit` crit+high findings in scope for the active user), per-service
 * counts will under-report for the affected services. Today the cap is 200
 * and the sample Developer view scope is intentionally small. If we breach
 * that, the right fix is the per-service variant
 * of /metrics/security-posture, not raising the cap.
 */

import type { FindingSummary } from "./types";
import { lookupComponent, type ServiceInfo } from "./component-map";

export type Grade = "A" | "B" | "C" | "D";

/** Sonar / Dependabot ladder — first matching condition wins, top-to-bottom. */
export function gradeSonarLike(criticals: number, highs: number): Grade {
  if (criticals === 0 && highs === 0) return "A";
  if (criticals <= 2 && highs <= 10) return "B";
  if (criticals <= 10 && highs <= 30) return "C";
  return "D";
}

/** Jira pentest ladder — stricter because findings are rare and deliberate. */
export function gradePentest(
  criticals: number,
  highs: number,
  mediums: number,
): Grade {
  if (criticals === 0 && highs === 0 && mediums === 0) return "A";
  if (criticals === 0 && highs === 0 && mediums <= 2) return "B";
  if (criticals === 1 || (highs >= 1 && highs <= 2) || mediums >= 3) return "C";
  return "D";
}

export interface ServiceMetrics {
  service: ServiceInfo;

  // Per-source crit + high counts (raw numbers, also used in the Detailed
  // view's columns).
  sonarCriticals: number;
  sonarHighs: number;
  dependabotCriticals: number;
  dependabotHighs: number;
  pentestCriticals: number;
  pentestHighs: number;
  pentestMediums: number;

  // SLA breach counts — combined across every source, because the "is this
  // out of SLA?" question is source-agnostic (a critical's a critical, the
  // SLA window doesn't care who reported it).
  criticalSlaBreached: number;
  highSlaBreached: number;

  // Derived grades — A-D per source.
  sonarGrade: Grade;
  dependabotGrade: Grade;
  pentestGrade: Grade;

  // Convenience totals for the table sort.
  totalCriticals: number;
  totalHighs: number;
  totalOpen: number;
}

function emptyMetrics(service: ServiceInfo): ServiceMetrics {
  return {
    service,
    sonarCriticals: 0,
    sonarHighs: 0,
    dependabotCriticals: 0,
    dependabotHighs: 0,
    pentestCriticals: 0,
    pentestHighs: 0,
    pentestMediums: 0,
    criticalSlaBreached: 0,
    highSlaBreached: 0,
    sonarGrade: "A",
    dependabotGrade: "A",
    pentestGrade: "A",
    totalCriticals: 0,
    totalHighs: 0,
    totalOpen: 0,
  };
}

/**
 * Roll up a flat findings list into per-service metrics, keyed by service name.
 *
 * Findings whose `asset_display` doesn't resolve to a known service in the
 * dev-view map are silently dropped from this view (they still show up in the
 * "Explore findings" disclosure at the bottom of the page). That's a deliberate
 * choice: the per-service table answers "what does each of my services look
 * like?" — an asset that doesn't appear in the map by definition isn't one of
 * "my services" and would be noise here.
 */
export function aggregateByService(
  services: readonly ServiceInfo[],
  findings: readonly FindingSummary[],
): Map<string, ServiceMetrics> {
  const out = new Map<string, ServiceMetrics>();
  for (const svc of services) out.set(svc.service, emptyMetrics(svc));

  for (const f of findings) {
    const info = lookupComponent(f.asset_display);
    if (!info) continue;
    const m = out.get(info.service);
    if (!m) continue;

    if (f.source === "sonarcloud") {
      if (f.severity === "critical") m.sonarCriticals += 1;
      else if (f.severity === "high") m.sonarHighs += 1;
    } else if (f.source === "dependabot") {
      if (f.severity === "critical") m.dependabotCriticals += 1;
      else if (f.severity === "high") m.dependabotHighs += 1;
    } else if (f.source === "pentest") {
      if (f.severity === "critical") m.pentestCriticals += 1;
      else if (f.severity === "high") m.pentestHighs += 1;
      else if (f.severity === "medium") m.pentestMediums += 1;
    }

    if (f.sla_breached) {
      if (f.severity === "critical") m.criticalSlaBreached += 1;
      else if (f.severity === "high") m.highSlaBreached += 1;
    }
  }

  // Grade computation + totals — done in a second pass once counts are final.
  for (const m of out.values()) {
    m.sonarGrade = gradeSonarLike(m.sonarCriticals, m.sonarHighs);
    m.dependabotGrade = gradeSonarLike(m.dependabotCriticals, m.dependabotHighs);
    m.pentestGrade = gradePentest(m.pentestCriticals, m.pentestHighs, m.pentestMediums);
    m.totalCriticals = m.sonarCriticals + m.dependabotCriticals + m.pentestCriticals;
    m.totalHighs = m.sonarHighs + m.dependabotHighs + m.pentestHighs;
    m.totalOpen = m.totalCriticals + m.totalHighs;
  }

  return out;
}

// ---------------------------------------------------------------------------
// Group-level aggregates (used by the FindingsGroupedView "Group by"
// segmented control — application / service / team).
//
// `worstGrade` mirrors the "weakest link in the chain" semantics that the
// per-source ratings use: if ANY service in the group has a D, the whole
// group reads as D. This matches how SLA-breach colouring works in the
// merged FindingsCard and other per-team aggregate views.
// ---------------------------------------------------------------------------

const GRADE_RANK: Record<Grade, number> = { A: 0, B: 1, C: 2, D: 3 };
const RANK_TO_GRADE = ["A", "B", "C", "D"] as const satisfies readonly Grade[];

export interface GroupAggregate {
  /** Worst grade across the group (max rank wins). */
  worstGrade: Grade;
  totalCriticals: number;
  totalHighs: number;
  totalSlaBreached: number;
  serviceCount: number;
}

export function aggregateGroup(
  services: readonly ServiceMetrics[],
): GroupAggregate {
  if (services.length === 0) {
    return {
      worstGrade: "A",
      totalCriticals: 0,
      totalHighs: 0,
      totalSlaBreached: 0,
      serviceCount: 0,
    };
  }
  let worstRank = 0;
  let totalCriticals = 0;
  let totalHighs = 0;
  let totalSlaBreached = 0;
  for (const s of services) {
    worstRank = Math.max(
      worstRank,
      GRADE_RANK[s.sonarGrade],
      GRADE_RANK[s.dependabotGrade],
      GRADE_RANK[s.pentestGrade],
    );
    totalCriticals += s.totalCriticals;
    totalHighs += s.totalHighs;
    totalSlaBreached += s.criticalSlaBreached + s.highSlaBreached;
  }
  return {
    worstGrade: RANK_TO_GRADE[worstRank],
    totalCriticals,
    totalHighs,
    totalSlaBreached,
    serviceCount: services.length,
  };
}

export { GRADE_RANK };

// ---------------------------------------------------------------------------
// External URL builders for the row icons
// ---------------------------------------------------------------------------

const GITHUB_ORG =
  process.env.NEXT_PUBLIC_GITHUB_ORG?.trim() || "ExampleOrg";
const SONAR_BASE_URL = "https://sonarcloud.io";

export function githubUrlFor(service: ServiceInfo): string {
  return `https://github.com/${GITHUB_ORG}/${service.repo}`;
}

/**
 * SonarCloud project URL. Most services have exactly one Sonar project; the
 * Services may have multiple projects. We link to the first project as the
 * canonical "open in Sonar" landing.
 */
export function sonarUrlFor(service: ServiceInfo): string | null {
  const key = service.sonarProjects[0];
  if (!key) return null;
  return `${SONAR_BASE_URL}/project/overview?id=${encodeURIComponent(key)}`;
}
