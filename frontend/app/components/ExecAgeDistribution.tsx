// ---------------------------------------------------------------------------
// Age distribution of open critical+high.
//
// Answers the C-suite question "what's been ignored?". One horizontal stacked
// bar, four buckets, with the gt_90d bucket painted red so the slice that
// shouldn't exist is the visually loudest one. Each segment labels itself
// inline when it has enough room; the rest go to the legend underneath so
// the bar never gets clipped numbers.
//
// Buckets come pre-computed from the backend (`age_buckets_open_crit_high`)
// using `sla_started_at` — same anchor as SLA compliance, so a 6-month-old
// GitHub alert ingested yesterday correctly lands in `gt_90d`, not `lte_7d`.
// ---------------------------------------------------------------------------

import type { AgeBucketCounts } from "../lib/types";

export interface ExecAgeDistributionProps {
  buckets: AgeBucketCounts;
}

interface Bucket {
  key: keyof AgeBucketCounts;
  label: string;
  /** Hex colour used by the bar segment AND the legend swatch — kept in
   *  lockstep so the legend reliably maps to the bar segments. */
  colour: string;
  /** Text colour for the legend numeral; dark + light tuned. */
  labelTone: string;
  count: number;
}

function makeBuckets(b: AgeBucketCounts): Bucket[] {
  return [
    {
      key: "lte_7d",
      label: "≤ 7d",
      colour: "rgb(16 185 129 / 0.6)", // emerald — fresh, in normal triage budget
      labelTone: "text-emerald-700 dark:text-emerald-300",
      count: b.lte_7d,
    },
    {
      key: "lte_30d",
      label: "7–30d",
      colour: "rgb(245 158 11 / 0.6)", // amber — starting to drift
      labelTone: "text-amber-700 dark:text-amber-300",
      count: b.lte_30d,
    },
    {
      key: "lte_90d",
      label: "30–90d",
      colour: "rgb(249 115 22 / 0.7)", // orange — visibly stale
      labelTone: "text-orange-700 dark:text-orange-300",
      count: b.lte_90d,
    },
    {
      key: "gt_90d",
      label: "> 90d",
      colour: "rgb(220 38 38 / 0.85)", // red — should not exist
      labelTone: "text-red-700 dark:text-red-400",
      count: b.gt_90d,
    },
  ];
}

export default function ExecAgeDistribution({ buckets }: ExecAgeDistributionProps) {
  const slices = makeBuckets(buckets);
  const total = slices.reduce((sum, s) => sum + s.count, 0);

  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900/40 p-4">
      <div className="mb-3 flex items-baseline justify-between">
        <h2 className="text-sm uppercase tracking-wide text-neutral-300">
          Open critical + high · age distribution
        </h2>
        <span className="text-[11px] text-neutral-500">
          {total} open · anchored on SLA start
        </span>
      </div>

      {total === 0 ? (
        <div className="py-6 text-center text-sm text-neutral-500">
          No open critical or high findings in scope
        </div>
      ) : (
        <>
          <div
            className="flex h-7 w-full overflow-hidden rounded border border-neutral-800"
            role="img"
            aria-label="Age distribution of open critical + high findings"
          >
            {slices.map((slice) => {
              if (slice.count === 0) return null;
              const pct = (slice.count / total) * 100;
              const showInlineLabel = pct >= 10;
              return (
                <div
                  key={slice.key}
                  // Width is set inline because Tailwind can't generate
                  // `w-[37.2%]` at compile time from a runtime number.
                  style={{ width: `${pct}%`, backgroundColor: slice.colour }}
                  title={`${slice.label}: ${slice.count} (${pct.toFixed(0)}%)`}
                  className="flex items-center justify-center text-[11px] font-medium text-neutral-900"
                >
                  {showInlineLabel ? slice.count : null}
                </div>
              );
            })}
          </div>

          <ul className="mt-3 grid gap-x-4 gap-y-1 text-xs sm:grid-cols-4">
            {slices.map((slice) => (
              <li
                key={slice.key}
                className="flex items-center gap-2"
                aria-label={`${slice.label}: ${slice.count} findings`}
              >
                <span
                  aria-hidden="true"
                  className="inline-block h-2.5 w-2.5 shrink-0 rounded-sm"
                  style={{ backgroundColor: slice.colour }}
                />
                <span className="text-neutral-400">{slice.label}</span>
                <span className={`ml-auto font-mono ${slice.labelTone}`}>
                  {slice.count}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
