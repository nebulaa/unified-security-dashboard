import { Suspense } from "react";
import { redirect } from "next/navigation";
import PlatformPillarNav from "../../components/PlatformPillarNav";
import PlatformSubNav from "../PlatformSubNav";
import PlatformWizCategoryNav from "./PlatformWizCategoryNav";
import PlatformWizFindings from "./PlatformWizFindings";
import {
  isCanonicalPlatformWizCategoryParam,
  parsePlatformWizCategoryParam,
} from "./constants";
import {
  buildPlatformSubtitle,
  isThreatIntelPillarParam,
  loadPlatformWizByCategory,
  resolvePlatformPageScope,
  toScalar,
} from "../_shared";

/**
 * Platform view — Wiz findings tab: open Wiz rows grouped by wiz_category.
 */
export default async function PlatformWizPage(props: {
  searchParams: Promise<Record<string, string | string[]>>;
}) {
  const sp = await props.searchParams;
  if (isThreatIntelPillarParam(sp)) {
    redirect("/platform/threat-intel");
  }
  const wizCategoryParam = toScalar(sp.wiz_category);
  if (!isCanonicalPlatformWizCategoryParam(wizCategoryParam)) {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(sp)) {
      if (key === "wiz_category") continue;
      const scalar = toScalar(value);
      if (scalar) params.set(key, scalar);
    }
    params.set("wiz_category", parsePlatformWizCategoryParam(wizCategoryParam));
    redirect(`/platform/wiz?${params.toString()}`);
  }

  const scope = await resolvePlatformPageScope(sp);
  const { pillar } = scope;
  const activeCategory = wizCategoryParam;

  const data = await loadPlatformWizByCategory(scope);
  const categoryCounts = Object.fromEntries(
    data.categories.map((g) => [g.wiz_category, g.count]),
  );
  const visibleTotal = categoryCounts[activeCategory] ?? 0;

  return (
    <div className="space-y-4">
      <div className="space-y-4">
        <div className="space-y-0.5">
          <h1 className="text-2xl font-semibold tracking-tight">
            Wiz findings
            <span className="ml-2 align-middle font-mono text-sm text-neutral-500">
              ({visibleTotal})
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

      <Suspense
        fallback={
          <div className="h-9 w-full max-w-2xl animate-pulse rounded-lg bg-neutral-800" />
        }
      >
        <PlatformWizCategoryNav counts={categoryCounts} active={activeCategory} />
      </Suspense>

      <PlatformWizFindings data={data} activeCategory={activeCategory} />
    </div>
  );
}
