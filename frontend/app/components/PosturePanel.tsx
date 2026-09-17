import FindingsDisclosure from "./FindingsDisclosure";
import FindingsGroupedView from "./FindingsGroupedView";
import FindingsTable from "./FindingsTable";
import SourceRatingBadge from "./SourceRatingBadge";
import TrendChart from "./TrendChart";
import { mergeQueryHref } from "../lib/nav-query";
import type {
  FilterState,
  FindingListResponse,
  MetricsTrend,
  SecurityPosture,
  SourceRating,
} from "../lib/types";

// ---------------------------------------------------------------------------
// Shared posture surface for /developer and /platform.
//
// Two consumption patterns:
//   1. /platform splits across `/platform` (overview) and `/platform/findings`
//      like /developer; `<PosturePanel … />` remains for callers that want
//      the stacked layout (e.g. tests).
//   2. /developer splits the same panels across three sibling routes
//      (`/developer` overview, `/developer/services`, `/developer/findings`)
//      by importing the named exports `PostureRatings`, `PostureTrend`,
//      `PostureServices` and `PostureFindingsTable` directly. Each tab fetches
//      only the data it needs (overview skips the findings list; services /
//      findings skip the posture + trend).
//
// Keeping a single source of truth — same JSX, same styling — was the whole
// point of this file when it was created for /platform + /developer parity
//. The 3-tab split below preserves that: the layout you see on
// /developer is literally the same chunks of code, just split across pages.
//
// Jira pentest findings do not need a dedicated stand-alone panel. The source
// still has full first-class treatment:
//   - top 4-up rating card shows its A-D grade and per-severity counts.
//   - clicking those counts deep-links into the findings table with
//     `?source=pentest&severity=…` pre-filtered.
//   - per-service columns in `FindingsGroupedView` include the Jira pentest count.
// The dedicated panel was redundant once the rating card learned to drill in,
// and on quiet weeks it was reserving prime real estate for "zero" — moving
// the detail to a click respects that calmer steady state.
//
// ---------------------------------------------------------------------------

function findRating(
  ratings: SourceRating[],
  source: SourceRating["source"],
): SourceRating {
  // Defensive: backend always emits the three sources in fixed order, but a
  // stale prod cache could in theory hand back a smaller list. Surface a
  // clean "no data" rating in that case rather than crashing the page.
  return (
    ratings.find((r) => r.source === source) ?? {
      source,
      grade: "A",
      open_criticals: 0,
      open_highs: 0,
      open_mediums: 0,
      rationale: "no data",
    }
  );
}

function FindingsCard({
  posture,
  basePath,
  persistParams,
}: {
  posture: SecurityPosture;
  basePath: string;
  persistParams?: Record<string, string>;
}) {
  // Merged 2026-05-18 — was previously two cards (TotalsCard + SlaCard). One
  // card per severity, each carrying BOTH the open total (dominant number) and
  // the SLA-breach count (smaller secondary stat that lights up red when > 0).
  // The two numbers are independently clickable: the big number deep-links to
  // `?severity=X&details=open`; the breach line deep-links to the same plus
  // `&sla_breached=true`.
  const hasBreach = posture.criticals_out_of_sla > 0 || posture.highs_out_of_sla > 0;
  return (
    // p-3 + gap-2 (was p-4 + gap-3) — matches the trimmed SourceRatingBadge
    // siblings so the 4-up row stays at uniform height after the density
    // pass.
    <div
      className={`rounded-xl border p-3 flex flex-col gap-2 shadow-sm ring-1 ring-inset ${
        hasBreach
          ? "border-red-300 bg-gradient-to-br from-red-50 to-red-100 ring-red-500/20 dark:border-red-500/30 dark:from-red-950/40 dark:to-red-950/10 dark:ring-red-500/10"
          : "border-white/5 bg-gradient-to-br from-neutral-900/60 to-neutral-950/40 ring-white/5"
      }`}
    >
      <div className="text-xs font-semibold uppercase tracking-[0.08em] text-neutral-300">
        Findings (open)
      </div>
      <div className="flex flex-col gap-1.5 mt-auto">
        <SeverityFindingsRow
          tone="crit"
          label="Critical"
          openCount={posture.open_criticals}
          breachCount={posture.criticals_out_of_sla}
          basePath={basePath}
          severityParam="critical"
          persistParams={persistParams}
        />
        <SeverityFindingsRow
          tone="high"
          label="High"
          openCount={posture.open_highs}
          breachCount={posture.highs_out_of_sla}
          basePath={basePath}
          severityParam="high"
          persistParams={persistParams}
        />
      </div>
    </div>
  );
}

function SeverityFindingsRow({
  tone,
  label,
  openCount,
  breachCount,
  basePath,
  severityParam,
  persistParams,
}: {
  tone: "crit" | "high";
  label: string;
  openCount: number;
  breachCount: number;
  basePath: string;
  severityParam: "critical" | "high";
  persistParams?: Record<string, string>;
}) {
  // Per-severity card tints: pale 50/100 fill + 300 border in light, dark
  // 900/950 wash in dark. Label text stays muted (red-700/orange-700 light;
  // 400/70 dark) so the big number can dominate.
  const palette =
    tone === "crit"
      ? {
          border: "border-red-300 dark:border-red-900/60",
          bg: "bg-red-50 dark:bg-red-950/30",
          labelText: "text-red-700/80 dark:text-red-400/70",
          number: "text-red-700 dark:text-red-300",
        }
      : {
          border: "border-orange-300 dark:border-orange-900/60",
          bg: "bg-orange-50 dark:bg-orange-950/30",
          labelText: "text-orange-700/80 dark:text-orange-400/70",
          number: "text-orange-700 dark:text-orange-300",
        };

  return (
    // px-2.5 py-1.5 (was px-3 py-2.5) + text-2xl number (was text-3xl) +
    // mt-1 (was mt-2) — saves ~16px per row, ~32px per Findings card.
    <div
      className={`rounded-lg border ${palette.border} ${palette.bg} px-2.5 py-1.5`}
    >
      <div className="flex items-baseline justify-between gap-2">
        <a
          href={mergeQueryHref(basePath, {
            severity: severityParam,
            details: "open",
            ...persistParams,
          })}
          className={`text-sm font-medium ${palette.labelText} hover:underline`}
        >
          {label}
        </a>
        <a
          href={mergeQueryHref(basePath, {
            severity: severityParam,
            details: "open",
            ...persistParams,
          })}
          className={`text-2xl font-bold font-mono leading-none tabular-nums ${palette.number} hover:underline`}
        >
          {openCount}
        </a>
      </div>
      <a
        href={mergeQueryHref(basePath, {
          severity: severityParam,
          sla_breached: "true",
          details: "open",
          ...persistParams,
        })}
        className={`mt-1 flex items-baseline justify-between text-[11px] ${
          breachCount > 0
            ? "text-red-700 hover:text-red-900 dark:text-red-300 dark:hover:text-red-200"
            : "text-neutral-500 hover:text-neutral-300"
        }`}
      >
        <span>out of SLA</span>
        <span className="font-mono tabular-nums">{breachCount}</span>
      </a>
    </div>
  );
}


function RatingExplainer({ showWiz = false }: { showWiz?: boolean }) {
  // Inline disclosure so anyone looking at their grade can see what would
  // push them to A or pull them to C, without leaving the dashboard.
  // Source of truth is; this is a faithful summary, not a fork.
  return (
    <details className="text-xs text-neutral-500">
      <summary className="cursor-pointer hover:text-neutral-300 select-none">
        How are these graded?
      </summary>
      <div className="mt-3 rounded-lg border border-neutral-800 bg-neutral-900/40 p-4 space-y-3 text-neutral-300">
        <p>
          Each grade reflects open <span className="text-neutral-100">critical</span> and{" "}
          <span className="text-neutral-100">high</span> findings in your scope (Jira pentest
          also counts mediums). First matching row wins, top-to-bottom.
        </p>
        <div
          className={`grid gap-4 ${showWiz ? "md:grid-cols-2 xl:grid-cols-4" : "md:grid-cols-3"}`}
        >
          <RatingTable
            title="SonarCloud / Dependabot / Wiz"
            rows={[
              ["A", "0 critical AND 0 high"],
              ["B", "≤2 critical AND ≤10 high"],
              ["C", "≤10 critical AND ≤30 high"],
              ["D", ">10 critical OR >30 high"],
            ]}
          />
          {showWiz && (
            <div className="space-y-2">
              <div className="text-[11px] font-semibold uppercase tracking-wide text-neutral-400">
                Wiz team scope
              </div>
              <p className="text-[11px] leading-snug text-neutral-400">
                On /platform, Sonar and Dependabot stay on the platform team for
                the tab; Wiz spans every team in the pillar with a{" "}
                <span className="font-mono">wiz_service:</span> registry entry.
                On Application Security, Wiz follows the same team scope as the
                other sources.
              </p>
            </div>
          )}
          <RatingTable
            title="Jira pentest (stricter)"
            rows={[
              ["A", "0 critical AND 0 high AND 0 medium"],
              ["B", "0 critical AND 0 high AND ≤2 medium"],
              ["C", "1 critical OR 1-2 high OR ≥3 medium"],
              ["D", "≥2 critical OR ≥3 high"],
            ]}
          />
          <div className="space-y-2">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-neutral-400">
              Why Jira pentest differs
            </div>
            <p className="text-[11px] leading-snug text-neutral-400">
              Jira pentest findings are rare, manual, and each is a deliberate professional
              alarm — a single critical lands at C, not B. Continuous scans (Sonar,
              Dependabot) tolerate small backlog at B because a fresh CVE in a popular
              package shouldn&apos;t flip the grade every poll.
            </p>
          </div>
        </div>
      </div>
    </details>
  );
}

function RatingTable({
  title,
  rows,
}: {
  title: string;
  rows: ReadonlyArray<readonly [string, string]>;
}) {
  const gradeColor = {
    A: "text-emerald-700 dark:text-emerald-300",
    B: "text-blue-700 dark:text-blue-300",
    C: "text-amber-700 dark:text-amber-300",
    D: "text-red-700 dark:text-red-400",
  } as const;
  return (
    <div className="space-y-1.5">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-neutral-400">
        {title}
      </div>
      <div className="space-y-1">
        {rows.map(([grade, cond]) => (
          <div key={grade} className="flex items-baseline gap-3 text-[11px]">
            <span
              className={`font-mono font-bold ${
                gradeColor[grade as keyof typeof gradeColor]
              }`}
            >
              {grade}
            </span>
            <span className="text-neutral-400">{cond}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-panels (named exports) — composable pieces that the /developer tabs
// each import directly. Same JSX the full PosturePanel uses; just split so
// callers can pick exactly the bits they want without the data fetches that
// the other bits would require.
// ---------------------------------------------------------------------------

/** Row 1 — the 4-up rating card row + the "How are these graded?" explainer.
 *  Used as the headline summary on every posture-bearing page. The 4-card
 *  layout collapses to 2-up on tablets and a single column on phones so the
 *  labels stay legible at narrow widths. */
export function PostureRatings({
  posture,
  basePath,
  wizBasePath,
  wizTeams,
  persistParams,
}: {
  posture: SecurityPosture;
  basePath: string;
  /** Platform Wiz tab path; defaults to basePath when omitted. */
  wizBasePath?: string;
  /** When set (Platform view), render the Wiz rating card with pillar team scope. */
  wizTeams?: readonly string[];
  /** Query params preserved on drill-down (e.g. `pillar=io` on /platform). */
  persistParams?: Record<string, string>;
}) {
  const wizPath = wizBasePath ?? basePath;
  const sonarRating = findRating(posture.source_ratings, "sonarcloud");
  const dependabotRating = findRating(posture.source_ratings, "dependabot");
  const wizRating = posture.source_ratings.find((r) => r.source === "wiz");
  const pentestRating = findRating(posture.source_ratings, "pentest");
  const showWiz = wizRating !== undefined;
  return (
    <div className="space-y-2">
      <div
        className={`grid gap-4 sm:grid-cols-2 ${
          showWiz ? "lg:grid-cols-3 xl:grid-cols-5" : "lg:grid-cols-4"
        }`}
      >
        <SourceRatingBadge
          rating={sonarRating}
          basePath={basePath}
          persistParams={persistParams}
        />
        <SourceRatingBadge
          rating={dependabotRating}
          basePath={basePath}
          persistParams={persistParams}
        />
        {showWiz && wizRating && (
          <SourceRatingBadge
            rating={wizRating}
            basePath={wizPath}
            teamParams={wizTeams}
            persistParams={persistParams}
          />
        )}
        <SourceRatingBadge
          rating={pentestRating}
          basePath={basePath}
          persistParams={persistParams}
        />
        <FindingsCard
          posture={posture}
          basePath={basePath}
          persistParams={persistParams}
        />
      </div>
      <RatingExplainer showWiz={showWiz} />
    </div>
  );
}

/** Row 2 — the 30-day trend chart, with its section heading. */
export function PostureTrend({ trend }: { trend: MetricsTrend }) {
  return (
    <div>
      {/* mb-2 + smaller heading (was mb-3 / text-sm) — keeps the label
          readable while pulling the chart up another ~8px. */}
      <h2 className="mb-2 text-xs font-semibold uppercase tracking-[0.1em] text-neutral-300">
        Open by severity · last 30 days
      </h2>
      <TrendChart trend={trend} />
    </div>
  );
}

/** "Security by service" — the per-service grouped breakdown.
 *  Developer view only; /platform's flat findings disclosure already covers
 *  the per-team narrative for IPE + Cloudops without needing this. */
export function PostureServices({
  list,
}: {
  list: FindingListResponse;
}) {
  // The Services tab already carries its own page-level <h1>Security by
  // service</h1> in the page header, so this inner section heading is
  // redundant chrome that just pushes the table further down. Drop it on
  // the per-page render — anyone using PosturePanel (full panel mode, e.g.
  // /platform) still gets the labelled section because that path doesn't
  // come through this entry point.
  return <FindingsGroupedView initialData={list} />;
}

/** Findings disclosure — collapsed-by-default wrapper around FindingsTable.
 *  Used by /admin (and legacy stacked layouts). /platform and /developer
 *  route findings to dedicated tabs and bypass the disclosure
 *  entirely and renders `<FindingsTable />` inline on its own tab — the
 *  collapse affordance loses its purpose when the table IS the page. */
export function PostureFindingsDisclosure({
  list,
  basePath,
  detailsOpen = false,
  initialFilters,
  lockedTeams,
  lockedSources,
  extraParams,
}: {
  list: FindingListResponse;
  basePath: string;
  detailsOpen?: boolean;
  initialFilters?: FilterState;
  lockedTeams?: readonly string[];
  lockedSources?: readonly string[];
  /** Locked query params (e.g. `limit=200`) that must ride along on every
   *  client refetch, so a filter change inside the table doesn't silently
   *  drop the narrowing the SSR fetch applied. */
  extraParams?: Record<string, string>;
}) {
  return (
    <FindingsDisclosure
      defaultOpen={detailsOpen}
      summary={
        <>
          Explore findings
          <span className="ml-2 font-mono text-neutral-400">({list.total})</span>
        </>
      }
      hint={
        initialFilters?.source ? (
          <>
            filtered: {initialFilters.source}
            {initialFilters.severities?.[0] ? ` / ${initialFilters.severities[0]}` : ""}
            {" · "}
            <a href={basePath} className="underline hover:text-neutral-300">
              clear
            </a>
          </>
        ) : (
          "click to open the row-by-row view"
        )
      }
    >
      <FindingsTable
        initialData={list}
        initialFilters={initialFilters}
        lockedTeams={lockedTeams}
        lockedSources={lockedSources}
        extraParams={extraParams}
      />
    </FindingsDisclosure>
  );
}

// ---------------------------------------------------------------------------
// Public entry — full posture panel.
//
// Used when a page wants every section stacked (e.g. admin). /platform and
// /developer
// composes the named exports above instead because its 3-tab split needs
// finer control over which section each tab renders + which fetches each
// tab pays for.
// ---------------------------------------------------------------------------

export interface PosturePanelProps {
  posture: SecurityPosture;
  trend: MetricsTrend;
  list: FindingListResponse;
  /** /developer or /platform — used for the per-source / per-SLA deep links. */
  basePath: string;
  /** Set to true to expand the findings disclosure on first paint (e.g. when
   *  the user landed via a per-source deep link or carries explicit filters). */
  detailsOpen?: boolean;
  /** Pre-seed the table's filter from a deep link. Same shape as FindingsTable. */
  initialFilters?: FilterState;
  /** Additional locked-team scope for the embedded findings table (e.g.
   *  /platform pins both PLATFORM_TEAMS so the disclosure-expanded table
   *  matches the chart-level scope). */
  lockedTeams?: readonly string[];
  lockedSources?: readonly string[];
  /** Locked query params (e.g. `limit=200`) the SSR fetch applied —
   *  threaded so that in-table filter changes keep the same scope rather
   *  than silently broadening. */
  extraParams?: Record<string, string>;
  /**
   * When true, renders the Application / Service / Team grouped breakdown
   * section above the raw findings disclosure. Currently unused on /platform;
   * kept for backwards compatibility with deep links that depended on the
   * old shape.
   */
  showGrouped?: boolean;
}

export default function PosturePanel({
  posture,
  trend,
  list,
  basePath,
  detailsOpen = false,
  initialFilters,
  lockedTeams,
  lockedSources,
  extraParams,
  showGrouped = false,
}: PosturePanelProps) {
  return (
    <>
      <PostureRatings posture={posture} basePath={basePath} />
      <PostureTrend trend={trend} />
      {showGrouped && <PostureServices list={list} />}
      <PostureFindingsDisclosure
        list={list}
        basePath={basePath}
        detailsOpen={detailsOpen}
        initialFilters={initialFilters}
        lockedTeams={lockedTeams}
        lockedSources={lockedSources}
        extraParams={extraParams}
      />
    </>
  );
}
