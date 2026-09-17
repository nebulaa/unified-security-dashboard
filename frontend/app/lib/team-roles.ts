// ExampleOrg baseline scopes. Team and pillar keys mirror the sample
// component map and can be replaced by deployment-specific configuration.

export const PLATFORM_PRODUCT_TEAMS = ["product-platform"] as const;
export const PLATFORM_RETAIL_TEAMS = ["platform-retail"] as const;
export const PLATFORM_DATA_TEAMS = ["data-platform"] as const;
export const PLATFORM_CODE_SOURCES = ["dependabot", "sonarcloud"] as const;

export const PLATFORM_VIEW_ONLY_TEAMS = [
  ...PLATFORM_PRODUCT_TEAMS,
  ...PLATFORM_RETAIL_TEAMS,
  ...PLATFORM_DATA_TEAMS,
] as const;

export const PLATFORM_TEAMS = [
  ...PLATFORM_PRODUCT_TEAMS,
  ...PLATFORM_RETAIL_TEAMS,
  ...PLATFORM_DATA_TEAMS,
] as const;
export type PlatformTeamKey = (typeof PLATFORM_TEAMS)[number];

export const PLATFORM_TEAM_LABEL = "Platform Engineering";

export type ProductPlatformPillarTab = "product" | "retail" | "data";

export const THREAT_INTEL_PILLAR = "threat-intel";

export const PLATFORM_PILLAR_TABS: ReadonlyArray<{
  id: ProductPlatformPillarTab;
  label: string;
}> = [
  { id: "product", label: "Product" },
  { id: "retail", label: "Retail" },
  { id: "data", label: "Data" },
] as const;

export const PRODUCT_PLATFORM_PILLAR_TABS = PLATFORM_PILLAR_TABS;
export type DeveloperPillarTab = ProductPlatformPillarTab;
export const DEVELOPER_PILLAR_TABS = PRODUCT_PLATFORM_PILLAR_TABS;

const DEFAULT_DEVELOPER_PILLAR: DeveloperPillarTab = "product";

export function resolveDeveloperPillar(
  pillar: string | undefined,
): DeveloperPillarTab {
  if (pillar === "retail" || pillar === "data") return pillar;
  return DEFAULT_DEVELOPER_PILLAR;
}

export function developerPillarLabel(pillar: DeveloperPillarTab): string {
  return DEVELOPER_PILLAR_TABS.find((tab) => tab.id === pillar)?.label ?? pillar;
}

const DEFAULT_PLATFORM_PILLAR: ProductPlatformPillarTab = "product";

export function wizTeamsForPillar(
  pillar: ProductPlatformPillarTab,
  wizTeamsByPillar: Record<string, readonly string[]>,
): readonly string[] {
  return wizTeamsByPillar[pillar] ?? [];
}

function codeTeamsForPillar(
  pillar: ProductPlatformPillarTab,
): readonly string[] {
  if (pillar === "data") return PLATFORM_DATA_TEAMS;
  if (pillar === "retail") return PLATFORM_RETAIL_TEAMS;
  return PLATFORM_PRODUCT_TEAMS;
}

export function platformUnionTeams(
  pillar: ProductPlatformPillarTab,
  wizTeamsByPillar: Record<string, readonly string[]>,
): readonly string[] {
  return [
    ...new Set([
      ...codeTeamsForPillar(pillar),
      ...wizTeamsForPillar(pillar, wizTeamsByPillar),
    ]),
  ];
}

export function resolvePlatformScope(
  pillar: string | undefined,
  wizTeamsByPillar: Record<string, readonly string[]> = {},
): {
  pillar: ProductPlatformPillarTab;
  codeTeams: readonly string[];
  wizTeams: readonly string[];
  teams: readonly string[];
  sources: readonly string[] | undefined;
  label: string;
  sourceHint: string;
} {
  const resolved =
    pillar === "retail" || pillar === "data"
      ? pillar
      : DEFAULT_PLATFORM_PILLAR;
  const codeTeams = codeTeamsForPillar(resolved);
  const wizTeams = wizTeamsForPillar(resolved, wizTeamsByPillar);
  const teams = platformUnionTeams(resolved, wizTeamsByPillar);
  const label =
    PLATFORM_PILLAR_TABS.find((tab) => tab.id === resolved)?.label ?? resolved;
  const wizHint = wizTeams.length > 0 ? `; Wiz on ${wizTeams.join(", ")}` : "";
  return {
    pillar: resolved,
    codeTeams,
    wizTeams,
    teams,
    sources: PLATFORM_CODE_SOURCES,
    label,
    sourceHint: `Dependabot + SonarCloud on ${codeTeams.join(", ")} repos${wizHint}`,
  };
}

export const DEVELOPER_VIEW_PILLARS: readonly DeveloperPillarTab[] = [
  "product",
  "retail",
  "data",
] as const;

const DEVELOPER_VIEW_EXCLUDED_TEAMS: ReadonlySet<string> = new Set(
  PLATFORM_VIEW_ONLY_TEAMS,
);

export function filterToDeveloperViewTeams(
  teamKeys: readonly string[],
  pillarByTeam: ReadonlyMap<string, string | null>,
): string[] {
  return teamKeys.filter((key) => {
    if (DEVELOPER_VIEW_EXCLUDED_TEAMS.has(key)) return false;
    const pillar = pillarByTeam.get(key);
    return (
      pillar != null &&
      DEVELOPER_VIEW_PILLARS.includes(pillar as DeveloperPillarTab)
    );
  });
}
