import ExecAgeDistribution from "./ExecAgeDistribution";
import ExecMomentumStrip from "./ExecMomentumStrip";
import ExecOffenderList from "./ExecOffenderList";
import TrendChart from "./TrendChart";
import type {
  MetricsSummary,
  MetricsTrend,
  TopAssetPoint,
  TopTeamPoint,
} from "../lib/types";

export default function ExecPillarDetailColumn({
  label,
  summary,
  trend,
  topTeams,
  topServices,
}: {
  label: string;
  summary: MetricsSummary | null;
  trend: MetricsTrend;
  topTeams: TopTeamPoint[];
  topServices: TopAssetPoint[];
}) {
  return (
    <div className="space-y-6">
      <h3 className="border-b border-neutral-800/80 pb-2 text-lg font-semibold text-neutral-100">
        {label}
      </h3>

      <div className="space-y-4">
        <ExecMomentumStrip summary={summary} />
        <ExecAgeDistribution
          buckets={
            summary?.age_buckets_open_crit_high ?? {
              lte_7d: 0,
              lte_30d: 0,
              lte_90d: 0,
              gt_90d: 0,
            }
          }
        />
      </div>

      <div>
        <h4 className="mb-2 text-sm uppercase tracking-wide text-neutral-500">
          Open findings by severity · {trend.window_days}d
        </h4>
        <TrendChart trend={trend} />
      </div>

      <ExecOffenderList
        teams={topTeams}
        services={topServices}
        emptyHint={`no open critical or high findings in ${label}`}
      />
    </div>
  );
}
