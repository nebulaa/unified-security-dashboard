/**
 * URL-driven scope for `/developer` — safe to import from client components.
 * Server pages use the same helpers via `developer/_shared.ts`.
 */

import { ALL_TEAMS, devTeamKeysForPillar } from "./component-map";
import {
  resolveDeveloperPillar,
  type DeveloperPillarTab,
} from "./team-roles";

/** Active pillar tab — inferred from selected team(s) when unambiguous. */
export function resolveActiveDeveloperPillar(
  pillarParam: string | undefined,
  selectionTeams: readonly string[],
): DeveloperPillarTab {
  if (selectionTeams.length > 0) {
    const pillars = new Set<DeveloperPillarTab>();
    for (const key of selectionTeams) {
      const info = ALL_TEAMS.find((t) => t.key === key);
      if (info?.pillar) pillars.add(info.pillar);
    }
    if (pillars.size === 1) return [...pillars][0];
  }
  return resolveDeveloperPillar(pillarParam);
}

/** Team keys sent to metrics/findings: explicit `?team=` or full active pillar. */
export function effectiveDeveloperTeams(
  pillar: DeveloperPillarTab,
  selectionTeams: readonly string[],
): readonly string[] {
  if (selectionTeams.length > 0) return selectionTeams;
  return devTeamKeysForPillar(pillar);
}
