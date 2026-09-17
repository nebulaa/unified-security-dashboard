/** ExampleOrg team metadata used by the sample frontend configuration. */
export interface TeamRegistryEntry {
  id: string;
  summary: string;
  projectId: string;
  testProject?: string;
}

const TEAM_REGISTRY: Readonly<Record<string, TeamRegistryEntry>> = {
  storefront: { id: "WEB", summary: "Storefront", projectId: "WEB" },
  orders: { id: "ORD", summary: "Orders", projectId: "ORD" },
  retail: { id: "RTL", summary: "Retail", projectId: "RTL" },
  merchandising: {
    id: "MERCH",
    summary: "Merchandising",
    projectId: "MERCH",
  },
  "data-engineering": {
    id: "DATA",
    summary: "Data Engineering",
    projectId: "DATA",
  },
  analytics: { id: "AN", summary: "Analytics", projectId: "AN" },
  "product-platform": {
    id: "PPLAT",
    summary: "Product Platform",
    projectId: "PPLAT",
  },
  "platform-retail": {
    id: "RPLAT",
    summary: "Retail Platform",
    projectId: "RPLAT",
  },
  "data-platform": {
    id: "DPLAT",
    summary: "Data Platform",
    projectId: "DPLAT",
  },
};

export function lookupTeamRegistry(teamKey: string): TeamRegistryEntry | null {
  return TEAM_REGISTRY[teamKey] ?? null;
}

export function teamRowLabel(teamKey: string): string {
  const entry = lookupTeamRegistry(teamKey);
  return entry ? `${entry.summary} · ${entry.id}` : teamKey;
}
