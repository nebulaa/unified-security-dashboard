import FindingsTable from "../../components/FindingsTable";
import TeamQuickPicker from "../../components/TeamQuickPicker";
import DeveloperSubNav from "../DeveloperSubNav";
import type { FilterState } from "../../lib/types";
import {
  buildSubtitle,
  loadDeveloperIdentity,
  loadFindingsList,
  resolveDeveloperScope,
} from "../_shared";

/**
 * Developer view — "Explore findings" tab.
 *
 * Flat findings table for every source in scope (Sonar, Dependabot, Wiz,
 * Jira pentest, …). Per-source deep links from the Overview rating cards land
 * here with `?source=` / `?severity=` pre-filtered.
 *
 * Scope locking: the dev-view scope (the 16-team union, plus the optional
 * `?asset=` deep link) is threaded into `FindingsTable` as `extraParams` /
 * `lockedTeams` / `lockedParams.asset`. Without these, any in-table filter
 * change (severity toggle, status / source dropdown, etc.) would refetch
 * with an unscoped query and silently bleed in findings from outside the
 * developer view.
 */
export default async function DeveloperFindings(props: {
  searchParams: Promise<Record<string, string | string[]>>;
}) {
  const sp = await props.searchParams;
  const scope = resolveDeveloperScope(sp);

  const [identity, list] = await Promise.all([
    loadDeveloperIdentity(),
    loadFindingsList(scope),
  ]);

  const subtitle = buildSubtitle(
    scope,
    identity.isAdmin,
    identity.developerTeams,
  );

  // Mirror the SSR fetch scope (loadFindingsList → scope.scopeParams) so the
  // client refetch on filter changes keeps the dev-view team union intact.
  const extraParams: Record<string, string> = {
    limit: "200",
  };
  const lockedFilters: Partial<FilterState> = {};
  if (scope.selectionAsset) lockedFilters.asset = scope.selectionAsset;

  return (
    <div className="space-y-4">
      <div className="space-y-0.5">
        <h1 className="text-2xl font-semibold tracking-tight bg-gradient-to-r from-white to-neutral-400 bg-clip-text text-transparent">
          Explore findings
          <span className="ml-2 align-middle font-mono text-sm text-neutral-500">
            ({list.total})
          </span>
        </h1>
        <p className="text-xs text-neutral-400">{subtitle}</p>
      </div>

      <TeamQuickPicker />

      <DeveloperSubNav />

      <FindingsTable
        initialData={list}
        initialFilters={scope.initialFilters}
        lockedTeams={scope.effectiveTeams}
        lockedParams={lockedFilters}
        extraParams={extraParams}
      />
    </div>
  );
}
