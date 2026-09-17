import ExecCoverageSection from "../components/ExecCoverageSection";
import ExecDetailDisclosure from "../components/ExecDetailDisclosure";
import ExecPillarBadge from "../components/ExecPillarBadge";
import ExecPillarDetailColumn from "../components/ExecPillarDetailColumn";
import ExecPillarKpiStrip from "../components/ExecPillarKpiStrip";
import {
  buildExecScopeQuery,
  mappedDisplayPillars,
  rollupTeamKeysForPillar,
} from "../lib/exec-scope";
import { getExecPillar, type ExecPillarKey } from "../lib/exec-pillars";
import { serverFetch } from "../lib/api/server";
import type {
  CoverageResponse,
  MetricsSummary,
  MetricsTrend,
  SecurityPosture,
  TopAssetPoint,
  TopTeamPoint,
} from "../lib/types";

interface PillarRollupData {
  pillar: ExecPillarKey;
  posture: SecurityPosture | null;
  summary: MetricsSummary | null;
}

interface PillarDetailData {
  pillar: ExecPillarKey;
  label: string;
  summary: MetricsSummary;
  trend: MetricsTrend;
  topTeams: TopTeamPoint[];
  topServices: TopAssetPoint[];
}

async function loadPillarRollup(pillar: ExecPillarKey): Promise<PillarRollupData> {
  const teams = rollupTeamKeysForPillar(pillar);
  if (teams.length === 0) {
    return { pillar, posture: null, summary: null };
  }
  const qs = buildExecScopeQuery(teams, undefined, {
    platformWizIssuesOnly: true,
  });
  const [posture, summary] = await Promise.all([
    serverFetch<SecurityPosture>(`/metrics/security-posture?${qs}`),
    serverFetch<MetricsSummary>(`/metrics/summary?${qs}`),
  ]);
  return { pillar, posture, summary };
}

async function loadDetailPanels(pillar: ExecPillarKey): Promise<PillarDetailData> {
  const teams = rollupTeamKeysForPillar(pillar);
  const qs = buildExecScopeQuery(teams, undefined, {
    platformWizIssuesOnly: true,
  });
  const [summary, trend, topTeams, topServices] = await Promise.all([
    serverFetch<MetricsSummary>(`/metrics/summary?${qs}`),
    serverFetch<MetricsTrend>(`/metrics/trend?days=90&${qs}`),
    serverFetch<TopTeamPoint[]>(`/metrics/top-teams?limit=50&${qs}`),
    serverFetch<TopAssetPoint[]>(`/metrics/top-services?limit=200&${qs}`),
  ]);
  return {
    pillar,
    label: getExecPillar(pillar).label,
    summary,
    trend,
    topTeams,
    topServices,
  };
}

// Coverage has its own collection cycle, so a missing or failed snapshot must
// not take the findings view down with it.
async function loadCoverage(): Promise<CoverageResponse | null> {
  try {
    return await serverFetch<CoverageResponse>("/metrics/coverage");
  } catch {
    return null;
  }
}

export default async function ExecutiveView() {
  const displayPillars = mappedDisplayPillars();

  const [rollups, details, coverage] = await Promise.all([
    Promise.all(displayPillars.map(loadPillarRollup)),
    Promise.all(displayPillars.map(loadDetailPanels)),
    loadCoverage(),
  ]);
  const rollupByPillar = new Map(rollups.map((r) => [r.pillar, r]));

  return (
    <div className="flex w-full flex-col gap-6">
      <header className="border-b border-neutral-800/80 pb-4">
        <h1 className="text-2xl font-semibold tracking-tight">Executive view</h1>
      </header>

      <div>
        <div className="mb-3 text-sm font-medium uppercase tracking-wider text-neutral-500">
          Product pillars
        </div>
        <div className="grid w-full grid-cols-1 gap-4 lg:grid-cols-2">
          {displayPillars.map((key) => {
            const def = getExecPillar(key);
            const rollup = rollupByPillar.get(key);
            return (
              <ExecPillarBadge
                key={key}
                label={def.label}
                description={def.description}
                openCriticals={rollup?.posture?.open_criticals ?? null}
                openHighs={rollup?.posture?.open_highs ?? null}
              />
            );
          })}
        </div>
      </div>

      <hr className="border-neutral-800/80" />

      <div className="grid w-full grid-cols-1 gap-6 lg:grid-cols-2">
        {displayPillars.map((key) => {
          const def = getExecPillar(key);
          const rollup = rollupByPillar.get(key);
          return (
            <ExecPillarKpiStrip
              key={key}
              label={def.label}
              summary={rollup?.summary ?? null}
            />
          );
        })}
      </div>

      {coverage ? (
        <>
          <hr className="border-neutral-800/80" />
          <ExecCoverageSection coverage={coverage} />
        </>
      ) : (
        <p className="text-xs text-neutral-500">
          Cloud security coverage is not available — no snapshot has been collected
          yet (<code>make coverage-sample</code> for local data).
        </p>
      )}

      {details.length > 0 && (
        <ExecDetailDisclosure>
          <div className="grid grid-cols-1 gap-8 xl:grid-cols-2 xl:divide-x xl:divide-neutral-800/80">
            {details.map((detail, index) => (
              <div
                key={detail.pillar}
                className={index === 0 ? "xl:pr-6" : "xl:pl-6"}
              >
                <ExecPillarDetailColumn
                  label={detail.label}
                  summary={detail.summary}
                  trend={detail.trend}
                  topTeams={detail.topTeams}
                  topServices={detail.topServices}
                />
              </div>
            ))}
          </div>
        </ExecDetailDisclosure>
      )}
    </div>
  );
}
