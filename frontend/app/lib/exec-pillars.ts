import { teamLabel } from "./component-map";

export type ExecPillarKey = "product" | "retail" | "data";

export interface ExecSubTeam {
  label: string;
  teamKey: string | null;
}

export interface ExecPillar {
  key: ExecPillarKey;
  label: string;
  description: string;
  subTeams: readonly ExecSubTeam[];
}

export const EXEC_PILLARS: readonly ExecPillar[] = [
  {
    key: "product",
    label: "Product",
    description: "Customer-facing products and services",
    subTeams: [
      { label: "Storefront", teamKey: "storefront" },
      { label: "Orders", teamKey: "orders" },
      { label: "Product Platform", teamKey: "product-platform" },
    ],
  },
  {
    key: "retail",
    label: "Retail",
    description: "Retail services and shared retail platform capabilities",
    subTeams: [
      { label: "Retail", teamKey: "retail" },
      { label: "Merchandising", teamKey: "merchandising" },
      { label: "Retail Platform", teamKey: "platform-retail" },
    ],
  },
  {
    key: "data",
    label: "Data",
    description: "Data engineering and analytics capabilities",
    subTeams: [
      { label: "Data Engineering", teamKey: "data-engineering" },
      { label: "Analytics", teamKey: "analytics" },
      {
        label: "Data Platform",
        teamKey: "data-platform",
      },
    ],
  },
] as const;

const PILLAR_BY_KEY = new Map(
  EXEC_PILLARS.map((pillar) => [pillar.key, pillar]),
);

export const DEFAULT_EXEC_PILLAR: ExecPillarKey = "product";

export function resolveExecPillar(
  raw: string | string[] | undefined,
): ExecPillarKey {
  const value = Array.isArray(raw) ? raw[0] : raw;
  if (value && PILLAR_BY_KEY.has(value as ExecPillarKey)) {
    return value as ExecPillarKey;
  }
  return DEFAULT_EXEC_PILLAR;
}

export function getExecPillar(key: ExecPillarKey): ExecPillar {
  const pillar = PILLAR_BY_KEY.get(key);
  if (!pillar) throw new Error(`Unknown executive pillar: ${key}`);
  return pillar;
}

export function teamKeysForPillar(key: ExecPillarKey): string[] {
  return getExecPillar(key)
    .subTeams.map((team) => team.teamKey)
    .filter((team): team is string => team !== null);
}

export function unmappedSubTeams(key: ExecPillarKey): readonly string[] {
  return getExecPillar(key)
    .subTeams.filter((team) => team.teamKey === null)
    .map((team) => team.label);
}

export function isPillarMapped(key: ExecPillarKey): boolean {
  return teamKeysForPillar(key).length > 0;
}

export function execSubTeamLabel(teamKey: string): string {
  for (const pillar of EXEC_PILLARS) {
    const team = pillar.subTeams.find((item) => item.teamKey === teamKey);
    if (team) return team.label;
  }
  return teamLabel(teamKey);
}
