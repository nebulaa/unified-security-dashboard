import { redirect } from "next/navigation";
import { PostureRatings, PostureTrend } from "../components/PosturePanel";
import TeamQuickPicker from "../components/TeamQuickPicker";
import DeveloperSubNav from "./DeveloperSubNav";
import {
  buildSubtitle,
  developerNavQueryString,
  loadDeveloperIdentity,
  loadOverviewMetrics,
  resolveDeveloperScope,
} from "./_shared";

/**
 * Developer view — Overview tab.
 *
 * The /developer route used to render the full posture panel (ratings +
 * trend + per-service breakdown + findings disclosure) all on one page.
 * 2026-05-18: split into three sibling routes so each surface gets the
 * vertical space it deserves and the page stays scannable:
 *
 *   /developer            → this file: ratings + trend (the "is everyone
 *                            healthy?" landing read)
 *   /developer/services   → "Security by service" (the per-service drill-in)
 *   /developer/findings   → "Explore findings" (all sources, including Wiz)
 *
 * All three share the page header, TeamQuickPicker, and DeveloperSubNav so
 * the user always knows where they are and can sideways-jump between tabs
 * without losing their scope. URL conventions documented in `_shared.ts`.
 */
export default async function DeveloperOverview(props: {
  searchParams: Promise<Record<string, string | string[]>>;
}) {
  const sp = await props.searchParams;
  const scope = resolveDeveloperScope(sp);

  // Rating-card deep links carry ?source= / ?severity= / ?details=open — send
  // those to Explore findings. Team / pillar / SLA scope stays on Overview.
  if (scope.source || scope.severity || sp.details === "open") {
    redirect(`/developer/findings${developerNavQueryString(sp)}`);
  }

  // Identity fetch (needed for TeamQuickPicker + subtitle) is independent
  // from the metrics fetch — kick them off in parallel.
  const [identity, metrics] = await Promise.all([
    loadDeveloperIdentity(),
    loadOverviewMetrics(scope),
  ]);

  const subtitle = buildSubtitle(
    scope,
    identity.isAdmin,
    identity.developerTeams,
  );

  return (
    // space-y-4 (was space-y-6) tightens the vertical rhythm between the
    // header / scope picker / sub-nav / panels — saves ~16px across the page
    // without making sections feel cramped.
    <div className="space-y-4">
      <div className="space-y-0.5">
        <h1 className="text-2xl font-semibold tracking-tight bg-gradient-to-r from-white to-neutral-400 bg-clip-text text-transparent">
          Application Security
        </h1>
        <p className="text-xs text-neutral-400">{subtitle}</p>
      </div>

      <TeamQuickPicker />

      <DeveloperSubNav />

      <PostureRatings
        posture={metrics.posture}
        basePath="/developer/findings"
        wizTeams={scope.effectiveTeams}
      />
      <PostureTrend trend={metrics.trend} />
    </div>
  );
}
