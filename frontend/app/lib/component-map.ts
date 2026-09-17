/**
 * ExampleOrg service metadata used to render stable empty rows and resolve
 * scanner asset identifiers. Deployments can replace this baseline by wiring
 * the existing `/components` API into these views.
 */

import {
  DEVELOPER_VIEW_PILLARS,
  type DeveloperPillarTab,
} from "./team-roles";

export interface MasterRow {
  teams: readonly string[];
  application: string;
  applicationKey: string;
  service: string;
  repo: string;
  sonarProjects: readonly string[];
  pillar: DeveloperPillarTab;
  execShowRepoLinks?: boolean;
}

export const MASTER_ROWS: readonly MasterRow[] = [
  {
    teams: ["storefront"],
    application: "Commerce",
    applicationKey: "commerce",
    service: "Web Store",
    repo: "web-store",
    sonarProjects: ["ExampleOrg_web-store"],
    pillar: "product",
  },
  {
    teams: ["orders"],
    application: "Commerce",
    applicationKey: "commerce",
    service: "Orders API",
    repo: "orders-api",
    sonarProjects: ["ExampleOrg_orders-api"],
    pillar: "product",
  },
  {
    teams: ["retail"],
    application: "Retail",
    applicationKey: "retail",
    service: "Retail API",
    repo: "retail-api",
    sonarProjects: ["ExampleOrg_retail-api"],
    pillar: "retail",
  },
  {
    teams: ["merchandising"],
    application: "Retail",
    applicationKey: "retail",
    service: "Catalog API",
    repo: "catalog-api",
    sonarProjects: ["ExampleOrg_catalog-api"],
    pillar: "retail",
  },
  {
    teams: ["data-engineering"],
    application: "Data Platform",
    applicationKey: "data-platform",
    service: "Event Pipeline",
    repo: "event-pipeline",
    sonarProjects: ["ExampleOrg_event-pipeline"],
    pillar: "data",
  },
  {
    teams: ["analytics"],
    application: "Analytics",
    applicationKey: "analytics",
    service: "Analytics API",
    repo: "analytics-api",
    sonarProjects: ["ExampleOrg_analytics-api"],
    pillar: "data",
  },
] as const;

export const PLATFORM_ENGINEERING_ROWS: readonly MasterRow[] = [
  {
    teams: ["product-platform"],
    application: "Product Platform",
    applicationKey: "product-platform",
    service: "Product Platform",
    repo: "product-platform",
    sonarProjects: ["ExampleOrg_product-platform"],
    pillar: "product",
  },
  {
    teams: ["platform-retail"],
    application: "Retail Platform",
    applicationKey: "retail-platform",
    service: "Retail Platform",
    repo: "retail-platform",
    sonarProjects: ["ExampleOrg_retail-platform"],
    pillar: "retail",
  },
  {
    teams: ["data-platform"],
    application: "Data Platform",
    applicationKey: "data-platform",
    service: "Data Foundation",
    repo: "data-foundation",
    sonarProjects: ["ExampleOrg_data-foundation"],
    pillar: "data",
  },
] as const;

const ALL_MAPPING_ROWS: readonly MasterRow[] = [
  ...MASTER_ROWS,
  ...PLATFORM_ENGINEERING_ROWS,
];

export interface ComponentInfo {
  service: string;
  application: string;
  applicationKey: string;
  ownerTeam: string;
  allTeams: readonly string[];
  pillar: DeveloperPillarTab;
  execShowRepoLinks: boolean;
}

function infoFromRow(row: MasterRow): ComponentInfo {
  return {
    service: row.service,
    application: row.application,
    applicationKey: row.applicationKey,
    ownerTeam: row.teams[0],
    allTeams: row.teams,
    pillar: row.pillar,
    execShowRepoLinks: row.execShowRepoLinks !== false,
  };
}

const COMPONENT_MAP: ReadonlyMap<string, ComponentInfo> = (() => {
  const map = new Map<string, ComponentInfo>();
  for (const row of ALL_MAPPING_ROWS) {
    const info = infoFromRow(row);
    map.set(row.repo, info);
    for (const project of row.sonarProjects) map.set(project, info);
  }
  return map;
})();

export function assetKey(assetDisplay: string): string {
  const stripped = assetDisplay.replace(/^(repo:|sonarproj:)/, "");
  const slash = stripped.lastIndexOf("/");
  return slash >= 0 ? stripped.slice(slash + 1) : stripped;
}

export interface LookupComponentOptions {
  ownerTeam?: string;
}

export function lookupComponent(
  assetDisplay: string,
  opts?: LookupComponentOptions,
): ComponentInfo | null {
  const hit = COMPONENT_MAP.get(assetKey(assetDisplay));
  if (hit) return hit;
  if (opts?.ownerTeam) {
    const row = PLATFORM_ENGINEERING_ROWS.find((item) =>
      item.teams.some((team) => team === opts.ownerTeam),
    );
    if (row) return infoFromRow(row);
  }
  return null;
}

export function serviceLabel(assetDisplay: string): string {
  return lookupComponent(assetDisplay)?.service ?? assetKey(assetDisplay);
}

export function applicationLabel(assetDisplay: string): string {
  return lookupComponent(assetDisplay)?.application ?? "Other";
}

export function applicationKey(assetDisplay: string): string {
  return lookupComponent(assetDisplay)?.applicationKey ?? "__other__";
}

const TEAM_ACRONYMS = new Set(["api", "sre"]);

export function teamLabel(key: string): string {
  return key
    .split("-")
    .map((part) =>
      TEAM_ACRONYMS.has(part)
        ? part.toUpperCase()
        : part.charAt(0).toUpperCase() + part.slice(1),
    )
    .join(" ");
}

export interface ApplicationInfo {
  key: string;
  label: string;
  services: readonly string[];
  repos: readonly string[];
  teams: readonly string[];
  pillar: DeveloperPillarTab;
}

export interface ServiceInfo extends ComponentInfo {
  repo: string;
  sonarProjects: readonly string[];
}

export interface TeamInfo {
  key: string;
  applicationKeys: readonly string[];
  serviceKeys: readonly string[];
  pillar: DeveloperPillarTab;
}

export const ALL_SERVICES: readonly ServiceInfo[] = MASTER_ROWS.map((row) => ({
  ...infoFromRow(row),
  repo: row.repo,
  sonarProjects: row.sonarProjects,
}));

export const ALL_EXEC_SERVICES: readonly ServiceInfo[] = ALL_MAPPING_ROWS.map(
  (row) => ({
    ...infoFromRow(row),
    repo: row.repo,
    sonarProjects: row.sonarProjects,
  }),
);

export const ALL_APPLICATIONS: readonly ApplicationInfo[] = (() => {
  const applications = new Map<string, ApplicationInfo>();
  for (const row of MASTER_ROWS) {
    const current = applications.get(row.applicationKey);
    applications.set(row.applicationKey, {
      key: row.applicationKey,
      label: row.application,
      services: [...new Set([...(current?.services ?? []), row.service])],
      repos: [...new Set([...(current?.repos ?? []), row.repo])],
      teams: [...new Set([...(current?.teams ?? []), ...row.teams])],
      pillar: row.pillar,
    });
  }
  return [...applications.values()];
})();

export interface RepoInfo {
  repo: string;
  services: readonly string[];
  teams: readonly string[];
  application: string;
  applicationKey: string;
}

export const ALL_REPOS: readonly RepoInfo[] = MASTER_ROWS.map((row) => ({
  repo: row.repo,
  services: [row.service],
  teams: row.teams,
  application: row.application,
  applicationKey: row.applicationKey,
}));

export const ALL_TEAMS: readonly TeamInfo[] = (() => {
  const teams = new Map<string, TeamInfo>();
  for (const row of MASTER_ROWS) {
    for (const key of row.teams) {
      const current = teams.get(key);
      teams.set(key, {
        key,
        applicationKeys: [
          ...new Set([...(current?.applicationKeys ?? []), row.applicationKey]),
        ],
        serviceKeys: [
          ...new Set([...(current?.serviceKeys ?? []), row.service]),
        ],
        pillar: row.pillar,
      });
    }
  }
  return [...teams.values()];
})();

export const DEV_VIEW_TEAM_KEYS: readonly string[] = ALL_TEAMS.map(
  (team) => team.key,
);

export function devTeamKeysForPillar(
  pillar: DeveloperPillarTab,
): readonly string[] {
  return ALL_TEAMS.filter((team) => team.pillar === pillar).map(
    (team) => team.key,
  );
}

export interface SelectionFilter {
  teams?: readonly string[];
  asset?: string;
}

export function selectionForTeam(team: string): SelectionFilter {
  return { teams: [team] };
}

export function selectionForService(service: ServiceInfo): SelectionFilter {
  return { asset: service.repo };
}

export function selectionForApplication(app: ApplicationInfo): SelectionFilter {
  return { teams: app.teams };
}

export function selectionForRepo(repo: RepoInfo): SelectionFilter {
  return { asset: repo.repo };
}

for (const row of MASTER_ROWS) {
  if (!DEVELOPER_VIEW_PILLARS.includes(row.pillar)) {
    throw new Error(`Unknown developer pillar: ${row.pillar}`);
  }
}
