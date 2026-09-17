import { Suspense } from "react";
import { redirect } from "next/navigation";
import PlatformPillarNav from "../components/PlatformPillarNav";
import { PostureRatings, PostureTrend } from "../components/PosturePanel";
import PlatformSubNav from "./PlatformSubNav";
import {
  buildPlatformSubtitle,
  isThreatIntelPillarParam,
  loadPlatformOverviewMetrics,
  platformNavQueryString,
  resolvePlatformPageScope,
  toScalar,
} from "./_shared";

/**
 * Platform security — Overview tab (ratings + trend).
 *
 * Explore findings lives on `/platform/findings` (same pattern as /developer).
 */
export default async function PlatformOverview(props: {
  searchParams: Promise<Record<string, string | string[]>>;
}) {
  const sp = await props.searchParams;
  if (isThreatIntelPillarParam(sp)) {
    redirect("/platform/threat-intel");
  }
  const scope = await resolvePlatformPageScope(sp);
  const { pillar } = scope;

  // Deep links from rating cards used `?details=open` on the single-page layout.
  // Send those (and per-source filters) straight to the findings tab.
  const detailsOpen =
    sp.details === "open" ||
    !!scope.source ||
    !!scope.severity ||
    toScalar(sp.sla_breached) === "true";
  if (detailsOpen) {
    const source = toScalar(sp.source);
    const target =
      source === "wiz"
        ? `/platform/wiz${platformNavQueryString(sp)}`
        : `/platform/findings${platformNavQueryString(sp)}`;
    redirect(target);
  }

  const metrics = await loadPlatformOverviewMetrics(scope);

  return (
    <div className="space-y-4">
      <div className="space-y-4">
        <div className="space-y-0.5">
          <h1 className="text-2xl font-semibold tracking-tight bg-gradient-to-r from-white to-neutral-400 bg-clip-text text-transparent">
            Platform security
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

      <PostureRatings
        posture={metrics.posture}
        basePath="/platform/findings"
        wizBasePath="/platform/wiz"
        wizTeams={scope.wizTeams}
        persistParams={pillar !== "product" ? { pillar } : undefined}
      />
      <PostureTrend trend={metrics.trend} />
    </div>
  );
}
