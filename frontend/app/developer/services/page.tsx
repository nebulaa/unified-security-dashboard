import { PostureServices } from "../../components/PosturePanel";
import TeamQuickPicker from "../../components/TeamQuickPicker";
import DeveloperSubNav from "../DeveloperSubNav";
import {
  buildSubtitle,
  loadDeveloperIdentity,
  loadFindingsList,
  resolveDeveloperScope,
} from "../_shared";

/**
 * Developer view — "Security by service" tab.
 *
 * Renders the per-service grouped breakdown (FindingsGroupedView) on its own
 * page so it gets the full vertical real estate. The Overview tab
 * (`/developer`) carries the ratings + trend; this tab carries the
 * drill-into-services flow. See `_shared.ts` for the URL conventions; this
 * tab honours the SLA pill (?sla=breached|within), the team chips (?team=)
 * and the asset selection (?asset=), all shared across the three tabs.
 *
 * We deliberately skip the posture + trend fetches here — they're only used
 * by the Overview tab. The findings list is the only data this tab needs
 * (FindingsGroupedView aggregates per-service metrics from it client-side).
 */
export default async function DeveloperServices(props: {
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

  return (
    // space-y-4 / space-y-0.5: same density pass as /developer; see the
    // Overview page comment for rationale.
    <div className="space-y-4">
      <div className="space-y-0.5">
        <h1 className="text-2xl font-semibold tracking-tight bg-gradient-to-r from-white to-neutral-400 bg-clip-text text-transparent">
          Security by service
        </h1>
        <p className="text-xs text-neutral-400">{subtitle}</p>
      </div>

      <TeamQuickPicker />

      <DeveloperSubNav />

      <PostureServices list={list} />
    </div>
  );
}
