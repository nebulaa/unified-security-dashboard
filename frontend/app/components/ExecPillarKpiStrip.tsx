import KpiCard from "./KpiCard";
import type { MetricsSummary } from "../lib/types";
import {
  buildMttrHint,
  buildWeekOverWeekDisplay,
  formatMttr,
  formatOldestAge,
  observationDays,
  oldestAgeTone,
} from "../lib/exec-metrics";

export default function ExecPillarKpiStrip({
  label,
  summary,
}: {
  label: string;
  summary: MetricsSummary | null;
}) {
  const obsDays = observationDays(summary?.observed_since ?? null);
  const wow = buildWeekOverWeekDisplay(summary, obsDays);
  const mttrHint = buildMttrHint(summary, obsDays);

  return (
    <section className="flex h-full flex-col gap-3">
      <h2 className="text-sm font-medium uppercase tracking-wider text-neutral-500">
        {label} · SLA / MTTR
      </h2>
      <div className="grid flex-1 grid-cols-1 gap-4 sm:grid-cols-2">
        <KpiCard
          label="Open criticals"
          value={summary?.open_criticals ?? "—"}
          delta={wow.text !== "—" ? wow.text : undefined}
          hint={wow.hint}
          tone={
            summary == null
              ? "neutral"
              : summary.open_criticals > 0
                ? "bad"
                : "ok"
          }
        />
        <KpiCard
          label="SLA compliance"
          value={summary ? `${summary.sla_compliance_pct}%` : "—"}
          tone={
            summary == null
              ? "neutral"
              : summary.sla_compliance_pct >= 95
                ? "ok"
                : summary.sla_compliance_pct >= 80
                  ? "warn"
                  : "bad"
          }
        />
        <KpiCard
          label="MTTR (criticals, 30d)"
          value={formatMttr(summary?.mttr_critical_30d_seconds ?? null)}
          hint={mttrHint}
        />
        <KpiCard
          label="Oldest open critical"
          value={formatOldestAge(
            summary?.oldest_open_critical_age_seconds ?? null,
          )}
          tone={oldestAgeTone(
            summary?.oldest_open_critical_age_seconds ?? null,
          )}
          hint={
            summary == null
              ? undefined
              : summary.oldest_open_critical_age_seconds == null
                ? "no open criticals"
                : "since SLA start"
          }
        />
      </div>
    </section>
  );
}
