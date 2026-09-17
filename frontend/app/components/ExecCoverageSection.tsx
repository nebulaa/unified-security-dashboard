/**
 * Cloud security coverage on /executive.
 *
 * Sits alongside the findings KPIs rather than inside them: findings measure
 * what is wrong with what we can see, coverage measures how much we can see at
 * all.
 */
import CoverageProjectMatrix from "./CoverageProjectMatrix";
import CoverageTile from "./CoverageTile";
import { formatAsOf } from "../lib/coverage";
import type { CoverageResponse } from "../lib/types";

export default function ExecCoverageSection({
  coverage,
}: {
  coverage: CoverageResponse;
}) {
  return (
    <section className="flex w-full flex-col gap-6">
      <header className="flex flex-wrap items-baseline justify-between gap-2 border-b border-neutral-800/80 pb-2">
        <h2 className="text-lg font-semibold tracking-tight">Cloud security coverage</h2>
        <span className="text-xs text-neutral-500">
          Refreshed daily · last run {formatAsOf(coverage.as_of)} UTC
        </span>
      </header>

      {coverage.stale && (
        // Last good numbers stay on screen; a collector outage must not read as
        // a coverage collapse.
        <p className="rounded border border-amber-700/50 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
          Snapshot is older than the refresh window — showing the last successful
          collection.
        </p>
      )}

      {coverage.collection_mode === "sample" && (
        <p className="rounded border border-violet-700/50 bg-violet-500/10 px-3 py-2 text-xs text-violet-700 dark:text-violet-300">
          Prototype data — these figures were generated locally and are not live coverage.
        </p>
      )}

      {coverage.degraded_sources.length > 0 && (
        <p className="rounded border border-amber-700/50 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
          Live collection is incomplete. Missing or failed sources:{" "}
          {coverage.degraded_sources.join(", ")}. Affected percentages are partial and
          must not be treated as organization-wide coverage.
        </p>
      )}

      {coverage.layers.map((layer) => (
        <div key={layer.key}>
          <div className="mb-3 flex flex-wrap items-baseline gap-3">
            <h3 className="text-sm font-semibold text-neutral-100">{layer.label}</h3>
            <span className="text-xs text-neutral-500">{layer.scope}</span>
          </div>
          <div
            className={`grid grid-cols-1 gap-4 ${
              layer.metrics.length >= 3 ? "lg:grid-cols-3" : "lg:grid-cols-2"
            }`}
          >
            {layer.metrics.map((metric) => (
              <CoverageTile key={metric.key} metric={metric} />
            ))}
          </div>
        </div>
      ))}

      <div>
        <h3 className="mb-3 text-sm font-semibold text-neutral-100">
          Coverage by key project
        </h3>
        <CoverageProjectMatrix
          projects={coverage.projects}
          unmapped={coverage.unmapped}
        />
      </div>

      <p className="text-xs text-neutral-500">
        Thresholds: green ≥ {coverage.green_pct}%, amber {coverage.amber_pct}–
        {coverage.green_pct - 1}%, red &lt; {coverage.amber_pct}%. Excepted items leave
        the denominator; every exception has an owner, reason and expiry.
      </p>
    </section>
  );
}
