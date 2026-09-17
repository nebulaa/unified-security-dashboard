"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { DEFAULT_PLATFORM_WIZ_CATEGORY } from "./wiz/constants";

const TABS = [
  { href: "/platform", label: "Overview" },
  { href: "/platform/wiz", label: "Wiz findings" },
  { href: "/platform/findings", label: "Explore findings" },
] as const;

// Keep in sync with filters in `platform/_shared.ts`. `pillar` is the
// pillar-tab scope, not a disposable filter — never clear it here.
const CLEARABLE_PARAMS = [
  "source",
  "severity",
  "sla_breached",
  "details",
] as const;

export default function PlatformSubNav() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const activeCount = CLEARABLE_PARAMS.filter((key) =>
    searchParams.has(key),
  ).length;
  const hasFilters = activeCount > 0;

  function onClear() {
    const next = new URLSearchParams(searchParams.toString());
    for (const key of CLEARABLE_PARAMS) next.delete(key);
    const path = pathname ?? "/platform";
    const target = next.toString() ? `${path}?${next.toString()}` : path;
    router.push(target, { scroll: false });
  }

  return (
    <nav
      aria-label="Platform security sections"
      className="flex items-end justify-between gap-2 border-b border-white/5"
    >
      <ul className="flex flex-wrap items-end gap-1">
        {TABS.map((tab) => {
          const active = isActiveTab(pathname, tab.href);
          const href = tabHref(tab.href, searchParams);
          return (
            <li key={tab.href}>
              <Link
                href={href}
                aria-current={active ? "page" : undefined}
                className={`inline-flex items-center px-3 py-1.5 text-sm font-medium border-b-2 -mb-px transition-colors ${
                  active
                    ? "border-emerald-400 text-neutral-100"
                    : "border-transparent text-neutral-400 hover:text-neutral-100 hover:border-white/20"
                }`}
              >
                {tab.label}
              </Link>
            </li>
          );
        })}
      </ul>

      <button
        type="button"
        onClick={onClear}
        disabled={!hasFilters}
        className={`mb-1 inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium transition-colors ${
          hasFilters
            ? "border-neutral-700 bg-neutral-900 text-neutral-200 hover:border-neutral-500 hover:bg-neutral-800 hover:text-white cursor-pointer"
            : "border-neutral-800 bg-neutral-950 text-neutral-600 cursor-not-allowed"
        }`}
        title={
          hasFilters
            ? `Reset the ${activeCount} active filter${activeCount === 1 ? "" : "s"} (source, severity)`
            : "No filters applied"
        }
      >
        <span aria-hidden="true">×</span>
        <span>Clear filters</span>
        {hasFilters && (
          <span className="rounded-full bg-emerald-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-700 dark:text-emerald-300">
            {activeCount}
          </span>
        )}
      </button>
    </nav>
  );
}

function tabHref(href: string, searchParams: URLSearchParams): string {
  const params = new URLSearchParams(searchParams.toString());
  if (href === "/platform/wiz" && !params.has("wiz_category")) {
    params.set("wiz_category", DEFAULT_PLATFORM_WIZ_CATEGORY);
  }
  const qs = params.toString();
  return qs ? `${href}?${qs}` : href;
}

function isActiveTab(pathname: string | null, href: string): boolean {
  if (!pathname) return false;
  const norm = pathname.replace(/\/$/, "") || "/";
  if (href === "/platform") {
    return norm === "/platform";
  }
  return norm === href || norm.startsWith(`${href}/`);
}
