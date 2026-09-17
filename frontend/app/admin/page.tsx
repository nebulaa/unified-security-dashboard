import { Fragment } from "react";
import DlqEventsPanel from "../components/DlqEventsPanel";
import OwnershipReresolvePanel from "../components/OwnershipReresolvePanel";
import PollersPanel from "../components/PollersPanel";
import FindingsDisclosure from "../components/FindingsDisclosure";
import FindingsTable from "../components/FindingsTable";
import { serverFetch } from "../lib/api/server";
import {
  DEFAULT_OPEN_STATUSES,
  defaultFindingsQuery,
} from "../lib/findings-defaults";
import type {
  FindingListResponse,
  Me,
  ScannerHealthResponse,
  SecurityPosture,
  SourceRating,
  DlqListResponse,
  OwnershipStatusResponse,
  PollerListResponse,
} from "../lib/types";

const SOURCE_LABELS: Record<SourceRating["source"], string> = {
  sonarcloud: "SonarCloud",
  dependabot: "Dependabot",
  wiz: "Wiz",
  pentest: "Jira pentest",
};

const ORGANIZATION_NAME =
  process.env.NEXT_PUBLIC_ORGANIZATION_NAME?.trim() || "ExampleOrg";

type SonarOrgBreakdown = {
  rows: { org: string; label: string; count: number }[];
  total: number;
  loaded: number;
  truncated: boolean;
};

// Two-tier RBAC guard: only admins can render the page. Members
// reach the same URL via the nav (it's hidden but still bookmarkable) and
// see this panel instead of triggering a backend 403 cascade.
function NotAuthorized({ email }: { email: string }) {
  return (
    <div className="mx-auto max-w-xl rounded-lg border border-neutral-800 bg-neutral-900/40 p-8 text-center">
      <h1 className="text-2xl font-semibold text-neutral-100">Not authorized</h1>
      <p className="mt-3 text-sm text-neutral-400">
        The admin page is restricted to security operators. You are signed in
        as <span className="font-mono text-neutral-300">{email}</span>.
      </p>
      <p className="mt-2 text-xs text-neutral-500">
        Need access? Ask the dashboard owner to add your email to{" "}
        <code className="font-mono">config/rbac.yaml</code>{" "}
        <code className="font-mono">admin_emails</code>.
      </p>
    </div>
  );
}

// Admin chart surface: small KPI strip + scanner health + disclosure-wrapped
// unowned table. The page is chart-first; the details list lives
// behind the disclosure, accessible in one click.
//
// Sections, in order:
//   1. Unowned posture — findings where owner_team='unowned' that are not
//      already visible on /developer or /platform (backend admin-triage filter)
//   2. Exclusion list — findings stamped `owner_team='excluded'` from
//      `ownership.yaml` `excluded_repos` (deliberate non-ownership).
//   3. Trivy in SonarCloud posture — admin-only `sonarcloud_trivy` bucket
//      suppressed from dev/exec/platform totals and from rows 1–2 above
//   4. Scanner health
//   5. Failed ingests (DLQ)
//   6. Unowned findings details (disclosure)
//   7. Excluded findings details (disclosure)
//   8. Trivy issues in SonarCloud (disclosure) — SonarCloud-hosted external
//      Trivy issues (Finding.source='sonarcloud_trivy'). Admin-only by
//      backend contract; hidden from /developer, /executive, /platform and
//      from the Unowned/Excluded sections above so they don't pollute the
//      org-wide numbers.

const SONARCLOUD_TRIVY_SOURCE = "sonarcloud_trivy";

/** Query for the admin-only Trivy-in-SonarCloud bucket (open findings only). */
function trivyFindingsQuery(
  extra: Record<string, string | readonly string[]> = {},
): string {
  const params = new URLSearchParams();
  params.append("source", SONARCLOUD_TRIVY_SOURCE);
  for (const s of DEFAULT_OPEN_STATUSES) params.append("status", s);
  appendQueryParams(params, extra);
  return params.toString();
}

function appendQueryParams(
  params: URLSearchParams,
  extra: Record<string, string | readonly string[]>,
): void {
  for (const [k, v] of Object.entries(extra)) {
    if (Array.isArray(v)) {
      for (const item of v) params.append(k, item);
    } else {
      params.append(k, v as string);
    }
  }
}

/** Open criticals only — used for SonarCloud org drill-down on /admin. */
function openCriticalsQuery(
  extra: Record<string, string | readonly string[]> = {},
): string {
  const params = new URLSearchParams();
  for (const s of DEFAULT_OPEN_STATUSES) params.append("status", s);
  params.append("severity", "critical");
  appendQueryParams(params, extra);
  return params.toString();
}

/** Sonar org key is the segment before the first `/` in `native_id`. */
function sonarOrgFromNativeId(nativeId: string): string {
  const slash = nativeId.indexOf("/");
  return slash > 0 ? nativeId.slice(0, slash) : nativeId;
}

function sonarOrgLabel(org: string): string {
  return `${ORGANIZATION_NAME} (${org})`;
}

function buildSonarOrgBreakdown(list: FindingListResponse): SonarOrgBreakdown {
  const counts = new Map<string, number>();
  for (const f of list.items) {
    const org = sonarOrgFromNativeId(f.native_id);
    counts.set(org, (counts.get(org) ?? 0) + 1);
  }
  return {
    rows: Array.from(counts.entries())
      .map(([org, count]) => ({ org, label: sonarOrgLabel(org), count }))
      .sort((a, b) => b.count - a.count),
    total: list.total,
    loaded: list.items.length,
    truncated: list.total > list.items.length,
  };
}

function CriticalsBySourceTable({
  posture,
  totalLabel,
  sonarOrgBreakdown,
}: {
  posture: SecurityPosture;
  totalLabel: string;
  sonarOrgBreakdown?: SonarOrgBreakdown;
}) {
  const rows = posture.source_ratings
    .filter((r) => r.open_criticals > 0)
    .sort((a, b) => b.open_criticals - a.open_criticals);
  if (rows.length === 0) return null;

  const total = posture.open_criticals;
  const sonarRating = rows.find((r) => r.source === "sonarcloud");

  return (
    <div className="mt-4">
      <div className="overflow-hidden rounded border border-neutral-800">
        <table className="w-full text-sm">
          <thead className="bg-neutral-900/80 text-xs uppercase tracking-wide text-neutral-400">
            <tr>
              <th className="px-3 py-2 text-left">Source</th>
              <th className="px-3 py-2 text-right">Open criticals</th>
              <th className="px-3 py-2 text-right">Share</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-neutral-900">
            {rows.map((row) => (
              <Fragment key={row.source}>
                <tr className="bg-neutral-950/40">
                  <td className="px-3 py-2 text-neutral-200">
                    {SOURCE_LABELS[row.source]}
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-neutral-300">
                    {row.open_criticals}
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-neutral-500">
                    {total > 0
                      ? `${Math.round((100 * row.open_criticals) / total)}%`
                      : "—"}
                  </td>
                </tr>
                {row.source === "sonarcloud" &&
                  sonarOrgBreakdown &&
                  sonarOrgBreakdown.rows.length > 0 &&
                  sonarOrgBreakdown.rows.map((orgRow) => (
                    <tr
                      key={`sonar-${orgRow.org}`}
                      className="bg-neutral-950/20 text-neutral-400"
                    >
                      <td className="px-3 py-1.5 pl-8 text-xs">
                        ↳ {orgRow.label}
                      </td>
                      <td className="px-3 py-1.5 text-right font-mono text-neutral-400">
                        {orgRow.count}
                        {sonarOrgBreakdown.truncated ? "+" : ""}
                      </td>
                      <td className="px-3 py-1.5 text-right font-mono text-neutral-600">
                        {sonarRating && sonarRating.open_criticals > 0
                          ? `${Math.round(
                              (100 * orgRow.count) / sonarRating.open_criticals,
                            )}%`
                          : "—"}
                      </td>
                    </tr>
                  ))}
              </Fragment>
            ))}
            <tr className="bg-neutral-900/50 font-medium">
              <td className="px-3 py-2 text-neutral-300">{totalLabel}</td>
              <td className="px-3 py-2 text-right font-mono text-neutral-100">
                {total}
              </td>
              <td className="px-3 py-2 text-right font-mono text-neutral-500">
                100%
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      {sonarOrgBreakdown?.truncated && (
        <p className="mt-1.5 text-xs text-neutral-500">
          SonarCloud org split from the first {sonarOrgBreakdown.loaded} of{" "}
          {sonarOrgBreakdown.total} criticals — sub-row counts may be
          incomplete when paginated.
        </p>
      )}
    </div>
  );
}

function UnownedKpi({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | string;
  tone: "bad" | "neutral";
}) {
  // Bad tone keeps a red wash in both themes; light-mode uses the pale 50/100
  // end of the red ramp, dark-mode keeps the deep 900/950 wash that's been
  // here since the original admin page.
  const colors =
    tone === "bad"
      ? "border-red-300 bg-red-50 text-red-700 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-300"
      : "border-neutral-800 bg-neutral-900/40 text-neutral-200";
  return (
    <div className={`rounded-lg border p-4 ${colors}`}>
      <div className="text-xs uppercase tracking-wide opacity-70">{label}</div>
      <div className="mt-2 text-3xl font-bold font-mono">{value}</div>
    </div>
  );
}

export default async function AdminView(props: {
  searchParams: Promise<Record<string, string | string[]>>;
}) {
  const sp = await props.searchParams;
  const detailsOpen = sp.details === "open";

  // Guard before any admin-only data fetch. /me is cheap and fails closed.
  const me = await serverFetch<Me>("/me");
  if (!me.is_admin) {
    return <NotAuthorized email={me.email} />;
  }

  // First-pass fetches: unowned, excluded, scanner health, and the admin-only
  // Trivy-in-SonarCloud bucket.
  const emptyFindings = (): FindingListResponse => ({
    items: [],
    total: 0,
    limit: 200,
    offset: 0,
  });

  const [
    unowned,
    excluded,
    scanners,
    dlq,
    pollers,
    ownership,
    posture,
    excludedPosture,
    sonarTrivy,
    sonarTrivyOpenTotal,
    sonarTrivyCritical,
    sonarTrivyHigh,
    unownedSonarCriticals,
  ] = await Promise.all([
    serverFetch<FindingListResponse>(
      `/findings?${defaultFindingsQuery({ team: "unowned", limit: "200" })}`,
    ),
    serverFetch<FindingListResponse>(
      `/findings?${defaultFindingsQuery({ team: "excluded", limit: "200" })}`,
    ),
    serverFetch<ScannerHealthResponse>("/scanners/health"),
    serverFetch<DlqListResponse>("/admin/dlq?limit=50"),
    serverFetch<PollerListResponse>("/admin/pollers"),
    serverFetch<OwnershipStatusResponse>("/admin/ownership"),
    serverFetch<SecurityPosture>("/metrics/security-posture?team=unowned"),
    serverFetch<SecurityPosture>("/metrics/security-posture?team=excluded"),
    // Trivy-in-SonarCloud is gated to admin on the backend (`source=
    // sonarcloud_trivy` returns 403 for non-admins). We render an empty
    // state for non-admins instead of crashing the whole /admin route.
    serverFetch<FindingListResponse>(
      // No default severity filter here: this section is a triage list,
      // showing all severities so the admin can see the full Trivy backlog
      // (mirrors how the Unowned section also avoids pre-filtering away
      // medium/low entries the security team may want to act on).
      `/findings?${trivyFindingsQuery({ limit: "200" })}`,
    ).catch(emptyFindings),
    // Lightweight count queries for the KPI strip (limit=1; total is authoritative).
    serverFetch<FindingListResponse>(
      `/findings?${trivyFindingsQuery({ limit: "1" })}`,
    ).catch(() => ({ items: [], total: 0, limit: 1, offset: 0 } satisfies FindingListResponse)),
    serverFetch<FindingListResponse>(
      `/findings?${trivyFindingsQuery({ severity: "critical", limit: "1" })}`,
    ).catch(() => ({ items: [], total: 0, limit: 1, offset: 0 } satisfies FindingListResponse)),
    serverFetch<FindingListResponse>(
      `/findings?${trivyFindingsQuery({ severity: "high", limit: "1" })}`,
    ).catch(() => ({ items: [], total: 0, limit: 1, offset: 0 } satisfies FindingListResponse)),
    serverFetch<FindingListResponse>(
      `/findings?${openCriticalsQuery({
        team: "unowned",
        source: "sonarcloud",
        limit: "200",
      })}`,
    ),
  ]);

  const distinctAssets = new Set(unowned.items.map((f) => f.asset_display)).size;
  const excludedDistinctAssets = new Set(
    excluded.items.map((f) => f.asset_display),
  ).size;
  const excludedTruncated = excluded.total > excluded.items.length;

  const sonarTrivyDistinctAssets = new Set(
    sonarTrivy.items.map((f) => f.asset_display),
  ).size;
  const sonarTrivyTruncated = sonarTrivy.total > sonarTrivy.items.length;
  const unownedSonarOrgBreakdown = buildSonarOrgBreakdown(unownedSonarCriticals);

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold">Admin view</h1>
        <p className="text-sm text-neutral-400">
          ownership gaps, failed ingests, and scanner health
        </p>
      </div>

      {/* Row 1 — Unowned KPI strip (the dashboard-as-chart contract) */}
      <div>
        <h2 className="mb-3 text-sm uppercase tracking-wide text-neutral-400">
          Unowned posture
        </h2>
        <div className="grid gap-4 md:grid-cols-4">
          <UnownedKpi
            label="Open criticals (unowned)"
            value={posture.open_criticals}
            tone={posture.open_criticals > 0 ? "bad" : "neutral"}
          />
          <UnownedKpi
            label="Open highs (unowned)"
            value={posture.open_highs}
            tone={posture.open_highs > 0 ? "bad" : "neutral"}
          />
          <UnownedKpi
            label="Total unowned (loaded)"
            value={unowned.total}
            tone="neutral"
          />
          <UnownedKpi
            label="Distinct assets to triage"
            value={`${distinctAssets}${unowned.total > unowned.items.length ? "+" : ""}`}
            tone="neutral"
          />
        </div>
        {posture.open_criticals > 0 && (
          <CriticalsBySourceTable
            posture={posture}
            totalLabel="Total open criticals (unowned)"
            sonarOrgBreakdown={unownedSonarOrgBreakdown}
          />
        )}
        {sonarTrivyCritical.total > 0 && (
          <p className="mt-2 text-xs text-neutral-500">
            Trivy-in-SonarCloud criticals ({sonarTrivyCritical.total}) are
            excluded from this breakdown — see the suppressed Trivy section
            below.
          </p>
        )}
      </div>

      {/* Row 2 — Exclusion list (`excluded_repos` in ownership.yaml) */}
      <div>
        <div className="mb-3 flex items-baseline justify-between">
          <h2 className="text-sm uppercase tracking-wide text-neutral-400">
            Exclusion list
          </h2>
          <p className="text-xs text-neutral-500">
            repos in <code className="text-neutral-400">excluded_repos</code> —
            stamped <code className="text-neutral-400">owner_team=excluded</code>
          </p>
        </div>
        <div className="grid gap-4 md:grid-cols-4">
          <UnownedKpi
            label="Open criticals (excluded)"
            value={excludedPosture.open_criticals}
            tone={excludedPosture.open_criticals > 0 ? "bad" : "neutral"}
          />
          <UnownedKpi
            label="Open highs (excluded)"
            value={excludedPosture.open_highs}
            tone={excludedPosture.open_highs > 0 ? "bad" : "neutral"}
          />
          <UnownedKpi
            label="Total excluded (loaded)"
            value={`${excluded.total}${excludedTruncated ? "+" : ""}`}
            tone="neutral"
          />
          <UnownedKpi
            label="Distinct assets"
            value={`${excludedDistinctAssets}${excludedTruncated ? "+" : ""}`}
            tone="neutral"
          />
        </div>
      </div>

      {/* Row 3 — Trivy in SonarCloud (suppressed from org-wide reporting) */}
      <div>
        <div className="mb-3 flex items-baseline justify-between">
          <h2 className="text-sm uppercase tracking-wide text-neutral-400">
            Trivy in SonarCloud (suppressed from reporting)
          </h2>
          <p className="text-xs text-neutral-500">
            excluded from /developer, /executive, /platform, and the unowned /
            exclusion-list totals above
          </p>
        </div>
        <div className="grid gap-4 md:grid-cols-4">
          <UnownedKpi
            label="Open criticals (Trivy)"
            value={sonarTrivyCritical.total}
            tone={sonarTrivyCritical.total > 0 ? "bad" : "neutral"}
          />
          <UnownedKpi
            label="Open highs (Trivy)"
            value={sonarTrivyHigh.total}
            tone={sonarTrivyHigh.total > 0 ? "bad" : "neutral"}
          />
          <UnownedKpi
            label="Total open (Trivy)"
            value={sonarTrivyOpenTotal.total}
            tone="neutral"
          />
          <UnownedKpi
            label="Distinct assets (loaded)"
            value={`${sonarTrivyDistinctAssets}${sonarTrivyTruncated ? "+" : ""}`}
            tone="neutral"
          />
        </div>
      </div>

      {/* Row 4 — Ownership re-resolve */}
      <div>
        <h2 className="mb-3 text-sm uppercase tracking-wide text-neutral-400">
          Ownership re-resolve
        </h2>
        <OwnershipReresolvePanel initial={ownership} />
      </div>

      {/* Row 5 — Manual poller runs */}
      <div>
        <h2 className="mb-3 text-sm uppercase tracking-wide text-neutral-400">
          Run pollers
        </h2>
        <PollersPanel initial={pollers} />
      </div>

      {/* Row 6 — Scanner health */}
      <div>
        <h2 className="mb-2 text-sm uppercase tracking-wide text-neutral-400">
          Scanner health
        </h2>
        <table className="w-full overflow-hidden rounded border border-neutral-800 text-sm">
          <thead className="bg-neutral-900/80 text-xs uppercase tracking-wide text-neutral-400">
            <tr>
              <th className="px-3 py-2 text-left">Source</th>
              <th className="px-3 py-2 text-left">Last seen</th>
              <th className="px-3 py-2 text-right">Cadence (s)</th>
              <th className="px-3 py-2 text-left">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-neutral-900">
            {scanners.items.map((s) => (
              <tr key={s.source} className="bg-neutral-950/40">
                <td className="px-3 py-2 text-neutral-200">{s.source}</td>
                <td className="px-3 py-2 text-neutral-400">{s.last_seen_at ?? "—"}</td>
                <td className="px-3 py-2 text-right text-neutral-400">
                  {s.expected_cadence_seconds ?? "manual"}
                </td>
                <td
                  className={`px-3 py-2 ${
                    s.status === "active"
                      ? "text-emerald-700 dark:text-emerald-400"
                      : s.status === "stale"
                        ? "text-amber-700 dark:text-amber-400"
                        : s.status === "dark"
                          ? "text-red-700 dark:text-red-400"
                          : "text-neutral-500"
                  }`}
                >
                  {s.status}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Row 7 — Failed ingests (DLQ) */}
      <div>
        <h2 className="mb-3 text-sm uppercase tracking-wide text-neutral-400">
          Failed ingests (DLQ)
        </h2>
        <div className="mb-4 grid gap-4 md:grid-cols-4">
          <UnownedKpi
            label="Unresolved DLQ events"
            value={dlq.unresolved_count}
            tone={dlq.unresolved_count > 0 ? "bad" : "neutral"}
          />
        </div>
        <FindingsDisclosure
          defaultOpen={dlq.unresolved_count > 0}
          summary={
            <>
              Explore failed ingest envelopes
              <span className="ml-2 font-mono text-neutral-400">
                ({dlq.items.length})
              </span>
            </>
          }
          hint="snapshots that exhausted Pub/Sub retries — triage raw_uri in GCS, then mark resolved"
        >
          <DlqEventsPanel initial={dlq} />
        </FindingsDisclosure>
      </div>

      {/* Row 8 — Unowned findings details behind disclosure */}
      <FindingsDisclosure
        defaultOpen={detailsOpen}
        summary={
          <>
            Explore unowned findings
            <span className="ml-2 font-mono text-neutral-400">({unowned.total})</span>
          </>
        }
        hint="resolve by adding `assets[*]` entries to ownership.yaml"
      >
        <FindingsTable
          initialData={unowned}
          lockedParams={{ team: "unowned" }}
          hideColumns={new Set(["team"])}
        />
      </FindingsDisclosure>

      {/* Row 9 — Excluded findings details behind disclosure */}
      {excluded.total > 0 && (
        <FindingsDisclosure
          defaultOpen={false}
          summary={
            <>
              Explore excluded findings
              <span className="ml-2 font-mono text-neutral-400">
                ({excluded.total})
              </span>
            </>
          }
          hint="repos listed in `ownership.yaml` `excluded_repos` — remove from the list to re-enable ownership"
        >
          <FindingsTable
            initialData={excluded}
            lockedParams={{ team: "excluded" }}
            hideColumns={new Set(["team"])}
          />
        </FindingsDisclosure>
      )}

      {/* Row 10 — Trivy issues hosted in SonarCloud. SonarCloud lets teams
          import third-party scanner reports as "external issues"; today
          some Sonar projects carry Trivy CVE rows that sit alongside native
          Sonar rule violations on `/api/issues/search`. Per the customer
          ask, those Trivy entries are excluded from /developer, /executive
          and /platform (and from the Unowned / Exclusion-list sections
          above) so they don't double-count against teams whose Trivy
          findings are already tracked elsewhere. The bucket is admin-only
          on the backend (`source=sonarcloud_trivy` → 403 for non-admins),
          so this section is the *only* surface in the dashboard where they
          appear. */}
      <FindingsDisclosure
        defaultOpen={false}
        summary={
          <>
            Explore Trivy issues in SonarCloud
            <span className="ml-2 font-mono text-neutral-400">
              ({sonarTrivyOpenTotal.total})
            </span>
          </>
        }
        hint="SonarCloud-hosted external Trivy entries — excluded from dev/exec/platform views and from org-wide totals"
      >
        <FindingsTable
          initialData={sonarTrivy}
          lockedParams={{ source: SONARCLOUD_TRIVY_SOURCE }}
          hideColumns={new Set(["source"])}
        />
      </FindingsDisclosure>
    </div>
  );
}
