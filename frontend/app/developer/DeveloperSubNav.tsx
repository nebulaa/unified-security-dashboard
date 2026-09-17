"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

// Sub-navigation between the three /developer tabs. Lives below the page
// title + TeamQuickPicker on every developer route so the user always sees
// where they are within the developer view and can jump sideways without
// losing their place.
//
// Why this is a client component (instead of a layout-level server component):
// we want to PRESERVE the current `?team=`, `?asset=`, `?sla=`, etc. query
// string when the user switches tabs — those are the scoping filters and
// dropping them on a tab switch would be deeply annoying. Reading
// `useSearchParams()` requires "use client", and Next.js server layouts
// don't receive a searchParams prop (only pages do). A small client component
// is the path of least resistance.
//
// The right-aligned "Clear filters" affordance lives in this same bar so
// it's persistently available on every developer tab — there's no longer a
// per-section clear button to hunt for. It enables when any filter is
// active, mutes to "No filters" when nothing is set, and stays on the
// current tab so the user just sees the same view with the narrowing
// removed.

const TABS = [
  { href: "/developer", label: "Overview" },
  { href: "/developer/services", label: "Security by service" },
  { href: "/developer/findings", label: "Explore findings" },
] as const;

// URL params the "Clear filters" button removes. Keep in sync with
// `_shared.ts::resolveDeveloperScope`. `pillar` is the tab scope (like
// `/platform`) — preserved on clear. `details` is included because it's a
// disclosure-state param the per-source deep links set, and a user clicking
// "Clear filters" almost certainly wants to re-collapse the table too.
const CLEARABLE_PARAMS = [
  "team",
  "asset",
  "sla",
  "source",
  "severity",
  "details",
] as const;

export default function DeveloperSubNav() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const qs = searchParams.toString();

  // Count active filters so the button can show e.g. "Clear filters (3)" —
  // useful confirmation that the click will actually do something. `team`
  // can repeat (`?team=a&team=b` → 2 narrowings), so use getAll().
  const activeCount = countActiveFilters(searchParams);
  const hasFilters = activeCount > 0;

  function onClear() {
    const next = new URLSearchParams(searchParams.toString());
    for (const key of CLEARABLE_PARAMS) next.delete(key);
    const path = pathname ?? "/developer";
    const target = next.toString() ? `${path}?${next.toString()}` : path;
    // `{ scroll: false }` keeps the viewport pinned — same rationale as the
    // SLA pill writer in FindingsGroupedView. Clear-filters is a refinement,
    // not a navigation; yanking the page to the top would mis-cue the user.
    router.push(target, { scroll: false });
  }

  return (
    <nav
      aria-label="Developer view sections"
      className="flex items-end justify-between gap-2 border-b border-white/5"
    >
      <ul className="flex flex-wrap items-end gap-1">
        {TABS.map((tab) => {
          // `/developer` should be active only when the pathname is exactly
          // `/developer` (or `/developer/`). Otherwise `/developer/services`
          // would also activate the Overview tab. The other tabs use exact
          // matches too — there are no deeper routes today.
          const active = isActiveTab(pathname, tab.href);
          const href = qs ? `${tab.href}?${qs}` : tab.href;
          return (
            <li key={tab.href}>
              <Link
                href={href}
                aria-current={active ? "page" : undefined}
                // Underline-the-active-tab pattern reads as a tab strip
                // without needing chrome — keeps the page from feeling like
                // it's wrapped in another header bar (TeamQuickPicker is
                // already pulling that weight).
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
        // The button stays in the layout at all times. When no filters are
        // active it's muted to a low-contrast "off" state so it doesn't
        // shout at the user, but it's still there in the same spot so they
        // learn the location.
        className={`mb-1 inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium transition-colors ${
          hasFilters
            ? "border-neutral-700 bg-neutral-900 text-neutral-200 hover:border-neutral-500 hover:bg-neutral-800 hover:text-white cursor-pointer"
            : "border-neutral-800 bg-neutral-950 text-neutral-600 cursor-not-allowed"
        }`}
        title={
          hasFilters
            ? `Reset the ${activeCount} active filter${activeCount === 1 ? "" : "s"} (team, asset, SLA, source/severity)`
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

function isActiveTab(pathname: string | null, href: string): boolean {
  if (!pathname) return false;
  const norm = pathname.replace(/\/$/, "") || "/";
  if (href === "/developer") {
    return norm === "/developer";
  }
  return norm === href || norm.startsWith(`${href}/`);
}

function countActiveFilters(searchParams: URLSearchParams): number {
  let count = 0;
  for (const key of CLEARABLE_PARAMS) {
    // `team` is a multi-value param (?team=a&team=b counts as two narrowings);
    // every other clearable param is scalar (one value max).
    if (key === "team") {
      count += searchParams.getAll(key).length;
    } else if (searchParams.has(key)) {
      count += 1;
    }
  }
  return count;
}
