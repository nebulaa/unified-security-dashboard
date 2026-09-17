"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import {
  PLATFORM_WIZ_CATEGORY_TABS,
  type PlatformWizCategoryTab,
} from "./constants";

export default function PlatformWizCategoryNav({
  counts,
  active,
}: {
  counts: Record<string, number>;
  active: PlatformWizCategoryTab;
}) {
  const pathname = usePathname();
  const searchParams = useSearchParams();

  function hrefFor(category: PlatformWizCategoryTab): string {
    const params = new URLSearchParams(searchParams.toString());
    params.set("wiz_category", category);
    const qs = params.toString();
    const path = pathname ?? "/platform/wiz";
    return qs ? `${path}?${qs}` : path;
  }

  return (
    <nav
      className="flex flex-wrap gap-1 rounded-lg border border-neutral-800 bg-neutral-900/50 p-1 w-fit"
      aria-label="Wiz finding categories"
    >
      {PLATFORM_WIZ_CATEGORY_TABS.map((tab) => {
        const isActive = active === tab.id;
        return (
          <Link
            key={tab.id}
            href={hrefFor(tab.id)}
            scroll={false}
            className={`inline-flex items-center gap-2 rounded-md px-4 py-1.5 text-sm font-medium transition-colors ${
              isActive
                ? "bg-neutral-700 text-neutral-100"
                : "text-neutral-400 hover:text-neutral-200 hover:bg-neutral-800/80"
            }`}
            aria-current={isActive ? "page" : undefined}
          >
            <span>{tab.label}</span>
            <span
              className={`rounded-full px-2 py-0.5 text-xs tabular-nums ${
                isActive
                  ? "bg-neutral-600 text-neutral-100"
                  : "bg-neutral-800 text-neutral-400"
              }`}
            >
              {counts[tab.id] ?? 0}
            </span>
          </Link>
        );
      })}
    </nav>
  );
}
