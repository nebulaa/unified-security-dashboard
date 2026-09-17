/** One coverage metric: RAG percentage, the raw X/Y, exceptions and gaps. */
import CoverageSparkline from "./CoverageSparkline";
import {
  RAG_ACCENT,
  RAG_TEXT,
  deltaTone,
  formatCounts,
  formatDelta,
  formatExceptions,
  formatPct,
  gapPreview,
} from "../lib/coverage";
import type { CoverageMetric } from "../lib/types";

export default function CoverageTile({ metric }: { metric: CoverageMetric }) {
  const delta = formatDelta(metric.delta_pts);
  const gaps = gapPreview(metric.gap_items);
  const unavailable = metric.unavailable_sources.length > 0;

  return (
    <div
      className={`flex h-full flex-col rounded-lg border border-t-[3px] border-neutral-800/80 ${RAG_ACCENT[metric.rag]} bg-neutral-900/40 p-4`}
    >
      <h4 className="text-sm font-semibold text-neutral-100">{metric.label}</h4>
      <p className="mt-1 min-h-[2.5rem] text-xs leading-snug text-neutral-500">
        {metric.definition}
      </p>

      <div className="mt-2 flex items-end gap-3">
        <span
          className={`text-4xl font-semibold tabular-nums leading-none ${RAG_TEXT[metric.rag]}`}
        >
          {unavailable ? "n/a" : formatPct(metric.ratio.pct)}
        </span>
        {delta && (
          <span className={`pb-1 text-xs ${deltaTone(metric.delta_pts)}`}>{delta}</span>
        )}
      </div>

      <CoverageSparkline points={metric.trend} rag={metric.rag} label={metric.label} />

      {unavailable ? (
        <p className="mt-1 text-xs text-amber-700 dark:text-amber-300">
          Incomplete source data: {metric.unavailable_sources.join(", ")}
        </p>
      ) : (
        <>
          <p className="mt-1 text-xs text-neutral-400">
            <span className="font-semibold text-neutral-100 tabular-nums">
              {formatCounts(metric.ratio, metric.unit)}
            </span>
          </p>
          <p className="mt-0.5 text-xs text-neutral-500" title={gaps}>
            {formatExceptions(metric.ratio)}
          </p>
        </>
      )}

      {metric.secondary && !unavailable && (
        // Supporting figure, deliberately without a RAG colour — it is context
        // for the tile above it, not a commitment of its own.
        <p className="mt-3 border-t border-dashed border-neutral-800 pt-2 text-xs text-neutral-500">
          {metric.secondary.label}: {formatPct(metric.secondary.ratio.pct)} —{" "}
          {formatCounts(metric.secondary.ratio, metric.secondary.unit)}
        </p>
      )}
    </div>
  );
}
