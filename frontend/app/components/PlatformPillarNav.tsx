"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import {
  PLATFORM_PILLAR_TABS,
  type ProductPlatformPillarTab,
} from "../lib/team-roles";

/** Product / Retail / Data pillar switcher for `/platform`. Clears pillar-specific
 *  filters when switching tabs. */
export default function PlatformPillarNav({
  active,
}: {
  active: ProductPlatformPillarTab;
}) {
  const pathname = usePathname();
  const searchParams = useSearchParams();

  return (
    <nav
      className="flex gap-1 rounded-lg border border-neutral-800 bg-neutral-900/50 p-1 w-fit"
      aria-label="Platform pillar"
    >
      {PLATFORM_PILLAR_TABS.map((tab) => {
        const params = new URLSearchParams(searchParams.toString());
        if (tab.id === "product") {
          params.delete("pillar");
        } else {
          params.set("pillar", tab.id);
        }
        // Default tab is Product (no query param).
        // Source filters are pillar-specific; drop them on switch.
        params.delete("source");
        params.delete("severity");
        params.delete("details");
        const qs = params.toString();
        const href = qs ? `${pathname}?${qs}` : pathname;
        const isActive = active === tab.id;
        return (
          <Link
            key={tab.id}
            href={href}
            className={`rounded-md px-4 py-1.5 text-sm font-medium transition-colors ${
              isActive
                ? "bg-neutral-700 text-neutral-100"
                : "text-neutral-400 hover:text-neutral-200 hover:bg-neutral-800/80"
            }`}
            aria-current={isActive ? "page" : undefined}
          >
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}
