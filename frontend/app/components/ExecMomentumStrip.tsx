// ---------------------------------------------------------------------------
// Inflow vs. outflow burn-down.
//
// Answers the C-suite question "are we winning?". Renders two columns per
// window (7d / 30d):
//   - New critical events  (discovered ∪ reopened on the event log)
//   - Closed critical events (fixed ∪ auto_closed)
// And a NET verdict beneath each window: burning down (-N) / accumulating
// (+N) / stable (0). When the in-scope observation history is younger than
// the window, the backend nulls both inflow and outflow — we render
// `history < 7d` / `history < 30d` instead of misleading zeros.
//
// Critical-only on purpose: the burn-down is the exec headline, and mixing
// in highs dilutes the signal that "the most severe stuff is on the move".
// The trend chart below already covers every severity over 90 days.
// ---------------------------------------------------------------------------

import type { MetricsSummary } from "../lib/types";

export interface ExecMomentumStripProps {
  summary: MetricsSummary | null;
}

interface WindowStat {
  label: string;
  newCount: number | null;
  closedCount: number | null;
  /** Hint shown beneath the verdict when both counts are null (history gap). */
  historyHint: string;
}

function buildWindows(summary: MetricsSummary | null): WindowStat[] {
  return [
    {
      label: "Last 7 days",
      newCount: summary?.new_critical_7d ?? null,
      closedCount: summary?.closed_critical_7d ?? null,
      historyHint: "history < 7d",
    },
    {
      label: "Last 30 days",
      newCount: summary?.new_critical_30d ?? null,
      closedCount: summary?.closed_critical_30d ?? null,
      historyHint: "history < 30d",
    },
  ];
}

export default function ExecMomentumStrip({ summary }: ExecMomentumStripProps) {
  const windows = buildWindows(summary);
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900/40 p-4">
      <div className="mb-3 flex items-baseline justify-between">
        <h2 className="text-sm uppercase tracking-wide text-neutral-300">
          Critical burn-down
        </h2>
        <span className="text-[11px] text-neutral-500">
          new vs. closed critical events
        </span>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        {windows.map((w) => (
          <BurnDownWindow key={w.label} window={w} />
        ))}
      </div>
    </div>
  );
}

function BurnDownWindow({ window }: { window: WindowStat }) {
  const hasData = window.newCount != null && window.closedCount != null;
  const net = hasData ? window.newCount! - window.closedCount! : null;
  const verdict = renderVerdict(net);
  return (
    <div className="rounded border border-neutral-800/80 bg-neutral-950/40 p-3">
      <div className="mb-2 text-[11px] uppercase tracking-wide text-neutral-500">
        {window.label}
      </div>
      <div className="grid grid-cols-2 gap-2">
        <Stat label="New" tone="bad" value={window.newCount} />
        <Stat label="Closed" tone="ok" value={window.closedCount} />
      </div>
      <div className="mt-2 flex items-baseline justify-between border-t border-neutral-900 pt-2">
        <span className="text-[11px] uppercase tracking-wide text-neutral-500">
          Net
        </span>
        {hasData ? (
          <span className={`text-sm font-semibold ${verdict.toneClass}`}>
            {verdict.label}
          </span>
        ) : (
          <span className="text-[11px] text-neutral-500">
            {window.historyHint}
          </span>
        )}
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | null;
  tone: "ok" | "bad";
}) {
  const toneClass =
    tone === "bad"
      ? "text-red-700 dark:text-red-300"
      : "text-emerald-700 dark:text-emerald-300";
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-neutral-500">
        {label}
      </div>
      <div className={`mt-0.5 font-mono text-xl font-semibold ${toneClass}`}>
        {value == null ? "—" : value}
      </div>
    </div>
  );
}

interface Verdict {
  label: string;
  toneClass: string;
}

function renderVerdict(net: number | null): Verdict {
  if (net == null) return { label: "—", toneClass: "text-neutral-500" };
  if (net < 0) {
    return {
      label: `Burning down (${net})`,
      toneClass: "text-emerald-700 dark:text-emerald-300",
    };
  }
  if (net > 0) {
    return {
      label: `Accumulating (+${net})`,
      toneClass: "text-red-700 dark:text-red-300",
    };
  }
  return { label: "Stable (0)", toneClass: "text-neutral-300" };
}
