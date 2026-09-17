import { Suspense } from "react";
import { redirect } from "next/navigation";
import FindingsTable from "../../components/FindingsTable";
import PlatformPillarNav from "../../components/PlatformPillarNav";
import PlatformSubNav from "../PlatformSubNav";
import {
  buildPlatformSubtitle,
  isThreatIntelPillarParam,
  loadPlatformFindingsList,
  resolvePlatformPageScope,
} from "../_shared";

/**
 * Platform view — "Explore findings" tab.
 *
 * Row-by-row findings table on its own page (no disclosure wrapper). Inherits
 * the active pillar scope and per-source deep links
 * from the Overview rating cards.
 */
export default async function PlatformFindings(props: {
  searchParams: Promise<Record<string, string | string[]>>;
}) {
  const sp = await props.searchParams;
  if (isThreatIntelPillarParam(sp)) {
    redirect("/platform/threat-intel");
  }
  const scope = await resolvePlatformPageScope(sp);
  const { pillar } = scope;

  const list = await loadPlatformFindingsList(scope.findingsExtra);

  return (
    <div className="space-y-4">
      <div className="space-y-4">
        <div className="space-y-0.5">
          <h1 className="text-2xl font-semibold tracking-tight">
            Explore findings
            <span className="ml-2 align-middle font-mono text-sm text-neutral-500">
              ({list.total})
            </span>
          </h1>
          <p className="text-xs text-neutral-400">
            {buildPlatformSubtitle(pillar)}
          </p>
        </div>
        <Suspense
          fallback={
            <div className="h-9 w-64 animate-pulse rounded-lg bg-neutral-800" />
          }
        >
          <PlatformPillarNav active={pillar} />
        </Suspense>
      </div>

      <PlatformSubNav />

      <FindingsTable
        initialData={list}
        initialFilters={scope.initialFilters}
        lockedTeams={scope.teams}
        lockedSources={undefined}
        extraParams={{ limit: "200" }}
      />
    </div>
  );
}
