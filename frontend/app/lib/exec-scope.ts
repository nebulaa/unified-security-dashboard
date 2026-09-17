/**
 * Executive view rollup scope — team unions for /executive.
 *
 * Source scope is intentionally omitted: exec rollups include every in-scope
 * source (Sonar, Dependabot, Wiz, Jira pentest, …) so pillar badges reconcile
 * with the offender list and other detail panels below.
 */

import { isPillarMapped, teamKeysForPillar, type ExecPillarKey } from "./exec-pillars";

export const EXEC_DISPLAY_PILLARS: readonly ExecPillarKey[] = [
  "product",
  "retail",
  "data",
];

/** Team keys passed to /metrics/* for a pillar's exec rollup. */
export function rollupTeamKeysForPillar(key: ExecPillarKey): string[] {
  return [...teamKeysForPillar(key)];
}

export function buildExecScopeQuery(
  teams: readonly string[],
  sources?: readonly string[],
  opts?: { platformWizIssuesOnly?: boolean },
): string {
  const params = new URLSearchParams();
  for (const t of teams) params.append("team", t);
  if (sources) {
    for (const s of sources) params.append("source", s);
  }
  if (opts?.platformWizIssuesOnly) {
    params.set("platform_wiz_issues_only", "true");
  }
  return params.toString();
}

export function mappedDisplayPillars(): ExecPillarKey[] {
  return EXEC_DISPLAY_PILLARS.filter((key) => isPillarMapped(key));
}

/** Pill label counts — e.g. `21 critical · 128 high`. */
export function formatCritHighCounts(
  criticals: number | null,
  highs: number | null,
): string {
  if (criticals == null && highs == null) return "—";
  const c = criticals ?? 0;
  const h = highs ?? 0;
  return `${c} critical · ${h} high`;
}
