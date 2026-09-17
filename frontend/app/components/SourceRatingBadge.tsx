import { mergeQueryHref } from "../lib/nav-query";
import type { SourceRating } from "../lib/types";

// Compact per-source A-D badge for the Developer landing page.
// Distinct from `SecurityRatingBadge` (the legacy composite, still used on
// /executive). Three of these stack across the top row of /developer:
// Sonar / Dependabot / Jira pentest.

// Subtle bg-gradient + ring instead of flat border gives the cards a hint of
// elevation without going into shadow-heavy territory. Same colour family per
// grade, but the gradient adds a small "lit from above" depth cue that reads
// as a modern surface (Linear / Vercel / GitHub adopt the same pattern).
//
// Light-mode pair: pale gradient from the X-50 → X-100 ramp, dark text on the
// X-700 / X-800 end of the same hue, and a subtle X-400 border so the card
// reads as the same semantic tone on a white background.
const GRADE_STYLES = {
  A: "border-emerald-300 bg-gradient-to-br from-emerald-50 to-emerald-100 text-emerald-700 ring-1 ring-inset ring-emerald-500/20 dark:border-emerald-500/30 dark:from-emerald-950/70 dark:to-emerald-950/30 dark:text-emerald-300 dark:ring-emerald-500/10",
  B: "border-blue-300 bg-gradient-to-br from-blue-50 to-blue-100 text-blue-700 ring-1 ring-inset ring-blue-500/20 dark:border-blue-500/30 dark:from-blue-950/70 dark:to-blue-950/30 dark:text-blue-300 dark:ring-blue-500/10",
  C: "border-amber-300 bg-gradient-to-br from-amber-50 to-amber-100 text-amber-700 ring-1 ring-inset ring-amber-500/20 dark:border-amber-500/30 dark:from-amber-950/70 dark:to-amber-950/30 dark:text-amber-300 dark:ring-amber-500/10",
  D: "border-red-300 bg-gradient-to-br from-red-50 to-red-100 text-red-700 ring-1 ring-inset ring-red-500/20 dark:border-red-500/30 dark:from-red-950/70 dark:to-red-950/30 dark:text-red-400 dark:ring-red-500/10",
} as const;

const SOURCE_LABELS: Record<SourceRating["source"], string> = {
  sonarcloud: "SonarCloud",
  dependabot: "Dependabot",
  wiz: "Wiz",
  pentest: "Jira pentest",
};

function sourceFilterHref(
  basePath: string,
  source: SourceRating["source"],
  severity: string,
  teamParams?: readonly string[],
  persistParams?: Record<string, string>,
): string {
  let href = mergeQueryHref(basePath, {
    source,
    severity,
    details: "open",
    ...persistParams,
  });
  if (teamParams?.length) {
    const q = href.indexOf("?");
    const path = q >= 0 ? href.slice(0, q) : href;
    const params = new URLSearchParams(q >= 0 ? href.slice(q + 1) : "");
    for (const t of teamParams) {
      params.append("team", t);
    }
    href = `${path}?${params.toString()}`;
  }
  return href;
}

export default function SourceRatingBadge({
  rating,
  basePath = "/developer",
  teamParams,
  persistParams,
}: {
  rating: SourceRating;
  basePath?: string;
  /** Wiz card on /platform passes pillar wiz teams for drill-down scope. */
  teamParams?: readonly string[];
  /** Query params preserved on drill-down (e.g. `pillar=io` on /platform). */
  persistParams?: Record<string, string>;
}) {
  const cfg = GRADE_STYLES[rating.grade];
  const label = SOURCE_LABELS[rating.source];
  // Jira pentest mediums matter; for code scans they're hidden behind the default
  // critical+high filter so we don't show the medium count.
  const showMediums = rating.source === "pentest";

  return (
    // p-3 + gap-2 + text-4xl grade (was p-4 / gap-3 / text-5xl) — same
    // information density, ~25-30px shorter per card. Stacking 4 across a
    // row that previously hit ~210px now fits in ~170px, which is the
    // chunk we need to get the Overview's trend chart fully above the
    // fold on a 800-840px viewport.
    <div className={`rounded-xl border ${cfg} p-3 flex flex-col gap-2 shadow-sm`}>
      <div className="flex items-start justify-between">
        <div className="text-xs font-semibold uppercase tracking-[0.08em] opacity-90">
          {label}
        </div>
        <div className="text-4xl font-black leading-none tabular-nums drop-shadow-sm">
          {rating.grade}
        </div>
      </div>
      <div className="space-y-1 text-sm">
        <CountLink
          label="Critical"
          count={rating.open_criticals}
          href={sourceFilterHref(
            basePath,
            rating.source,
            "critical",
            teamParams,
            persistParams,
          )}
        />
        <CountLink
          label="High"
          count={rating.open_highs}
          href={sourceFilterHref(
            basePath,
            rating.source,
            "high",
            teamParams,
            persistParams,
          )}
        />
        {showMediums && (
          <CountLink
            label="Medium"
            count={rating.open_mediums}
            href={sourceFilterHref(
              basePath,
              rating.source,
              "medium",
              teamParams,
              persistParams,
            )}
          />
        )}
      </div>
      <div className="text-[11px] text-neutral-300 leading-snug border-t border-white/10 pt-1.5">
        {rating.rationale}
      </div>
    </div>
  );
}

function CountLink({
  label,
  count,
  href,
}: {
  label: string;
  count: number;
  href: string;
}) {
  // Zero-count rows render plain text — nothing to drill into.
  if (count === 0) {
    return (
      <div className="flex items-center justify-between text-neutral-400">
        <span>{label}</span>
        <span className="font-mono tabular-nums text-neutral-500">0</span>
      </div>
    );
  }
  return (
    <a
      href={href}
      className="flex items-center justify-between text-neutral-200 hover:text-white hover:underline"
    >
      <span>{label}</span>
      <span className="font-mono tabular-nums font-semibold">{count}</span>
    </a>
  );
}
