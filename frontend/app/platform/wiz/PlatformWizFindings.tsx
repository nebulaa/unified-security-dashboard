"use client";

import { useState } from "react";
import type {
  WizCategoryGroup,
  WizFindingsByCategoryResponse,
  WizTitleGroup,
} from "../../lib/types";
import SeverityPill from "../../components/SeverityPill";
import {
  PLATFORM_WIZ_CATEGORY_TABS,
  type PlatformWizCategoryTab,
} from "./constants";

type FindingItem = WizFindingsByCategoryResponse["categories"][0]["items"][0];

function FindingRow({
  f,
  compact = false,
}: {
  f: FindingItem;
  compact?: boolean;
}) {
  return (
    <li className="flex flex-wrap items-start gap-x-2 gap-y-1 px-3 py-2 text-sm">
      <SeverityPill severity={f.severity} />
      <div className="min-w-0 flex-1">
        {compact ? (
          <>
            <div className="font-medium text-neutral-100">{f.asset_display}</div>
            <div className="mt-0.5 text-xs text-neutral-500">
              {f.owner_team} · {Math.round(f.age_days)}d
              {f.sla_breached ? (
                <span className="ml-1 text-red-400">SLA breached</span>
              ) : null}
            </div>
          </>
        ) : (
          <>
            <div className="font-medium text-neutral-100">{f.title}</div>
            <div className="mt-0.5 text-xs text-neutral-500">
              {f.asset_display} · {f.owner_team} · {Math.round(f.age_days)}d
              {f.sla_breached ? (
                <span className="ml-1 text-red-400">SLA breached</span>
              ) : null}
            </div>
          </>
        )}
      </div>
      {f.upstream_url ? (
        <a
          href={f.upstream_url}
          target="_blank"
          rel="noopener noreferrer"
          className="shrink-0 text-xs font-medium text-emerald-400 hover:text-emerald-300"
        >
          Wiz ↗
        </a>
      ) : null}
    </li>
  );
}

type TitleGroupPalette = {
  border: string;
  openBorder: string;
  card: string;
  chevron: string;
  openChevron?: string;
  badge: string;
  listBg: string;
  defaultBar: string;
  hover: string;
};

/** Neutral + emerald — matches platform nav, pillar tabs, and disclosure cards. */
const PLATFORM_TITLE_GROUP_PALETTE: TitleGroupPalette[] = [
  {
    border: "border-neutral-800",
    openBorder: "border-emerald-500/35 ring-emerald-500/10",
    card: "bg-neutral-900/50",
    chevron: "text-neutral-500",
    openChevron: "text-emerald-400",
    badge: "bg-neutral-800 text-neutral-300 ring-neutral-700",
    listBg: "bg-neutral-950/50",
    defaultBar: "bg-neutral-600",
    hover: "hover:bg-neutral-800/40",
  },
];

function severityBarClass(
  items: FindingItem[],
  fallback: string,
): string {
  if (items.some((f) => f.severity === "critical")) return "bg-orange-500";
  if (items.some((f) => f.severity === "high")) return "bg-amber-400";
  return fallback;
}

function countBadgeClass(items: FindingItem[], palette: TitleGroupPalette): string {
  if (items.some((f) => f.severity === "critical")) {
    return "bg-orange-500/25 text-orange-100 ring-1 ring-orange-400/35";
  }
  return `ring-1 ${palette.badge}`;
}

function TitleGroupsGrid({
  titleGroups,
  palette,
  moreLabel,
}: {
  titleGroups: WizTitleGroup[];
  palette: TitleGroupPalette[];
  moreLabel: string;
}) {
  const [expanded, setExpanded] = useState<string | null>(null);

  function toggle(title: string) {
    setExpanded((prev) => (prev === title ? null : title));
  }

  return (
    <div className="grid gap-2.5 sm:grid-cols-2">
      {titleGroups.map((titleGroup, index) => {
        const isOpen = expanded === titleGroup.title;
        const accent = palette[index % palette.length];
        return (
          <div
            key={titleGroup.title}
            className={`relative overflow-hidden rounded-lg border transition-colors ${
              accent.card
            } ${isOpen ? accent.openBorder : accent.border} ${
              isOpen ? "sm:col-span-2 ring-1 shadow-md shadow-black/20" : ""
            }`}
          >
            <div
              aria-hidden
              className={`absolute inset-y-0 left-0 w-1 ${severityBarClass(titleGroup.items, accent.defaultBar)}`}
            />
            <button
              type="button"
              onClick={() => toggle(titleGroup.title)}
              aria-expanded={isOpen}
              className={`flex w-full items-center gap-2 py-2.5 pl-4 pr-3 text-left text-sm transition-colors ${accent.hover}`}
            >
              <span
                aria-hidden
                className={`shrink-0 transition-transform ${
                  isOpen ? (accent.openChevron ?? accent.chevron) : accent.chevron
                } ${isOpen ? "rotate-90" : ""}`}
              >
                ▸
              </span>
              <span className="min-w-0 flex-1 font-medium leading-snug text-neutral-100 line-clamp-2">
                {titleGroup.title}
              </span>
              <span
                className={`shrink-0 rounded-full px-2.5 py-0.5 text-xs font-semibold tabular-nums ${countBadgeClass(titleGroup.items, accent)}`}
              >
                {titleGroup.count}
              </span>
            </button>
            {isOpen ? (
              <ul
                className={`divide-y divide-neutral-800 border-t border-neutral-800 ${accent.listBg}`}
              >
                {titleGroup.items.map((f) => (
                  <FindingRow key={f.id} f={f} compact />
                ))}
                {titleGroup.count > titleGroup.items.length ? (
                  <li className="px-3 py-1.5 text-xs text-neutral-400">
                    +{titleGroup.count - titleGroup.items.length} more with this{" "}
                    {moreLabel}
                  </li>
                ) : null}
              </ul>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

function CategoryBody({ group }: { group: WizCategoryGroup }) {
  if (group.wiz_category === "issue" && group.title_groups?.length) {
    return (
      <TitleGroupsGrid
        titleGroups={group.title_groups}
        palette={PLATFORM_TITLE_GROUP_PALETTE}
        moreLabel="issue"
      />
    );
  }

  if (group.wiz_category === "cloud_config" && group.title_groups?.length) {
    return (
      <TitleGroupsGrid
        titleGroups={group.title_groups}
        palette={PLATFORM_TITLE_GROUP_PALETTE}
        moreLabel="control"
      />
    );
  }

  if (group.wiz_category === "vulnerability" && group.title_groups?.length) {
    return (
      <TitleGroupsGrid
        titleGroups={group.title_groups}
        palette={PLATFORM_TITLE_GROUP_PALETTE}
        moreLabel="resource"
      />
    );
  }

  return (
    <ul className="divide-y divide-white/5">
      {group.items.map((f) => (
        <FindingRow key={f.id} f={f} />
      ))}
      {group.count > group.items.length ? (
        <li className="px-4 py-2 text-xs text-neutral-500">
          +{group.count - group.items.length} more in this category (not shown)
        </li>
      ) : null}
    </ul>
  );
}

export default function PlatformWizFindings({
  data,
  activeCategory,
}: {
  data: WizFindingsByCategoryResponse;
  activeCategory: PlatformWizCategoryTab;
}) {
  const group = data.categories.find((g) => g.wiz_category === activeCategory);
  const visibleTotal = group?.count ?? 0;

  if (visibleTotal === 0) {
    const label =
      PLATFORM_WIZ_CATEGORY_TABS.find((t) => t.id === activeCategory)?.label ??
      activeCategory;
    return (
      <p className="rounded-lg border border-white/5 bg-neutral-900/50 px-4 py-8 text-sm text-neutral-400">
        No open {label.toLowerCase()} in this pillar scope.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <p className="text-xs text-neutral-500">
        {visibleTotal} open finding{visibleTotal === 1 ? "" : "s"}
        {group?.title_groups?.length
          ? ` in ${group.title_groups.length} ${
              activeCategory === "issue"
                ? "issue"
                : activeCategory === "cloud_config"
                  ? "control"
                  : "CVE"
            } group${group.title_groups.length === 1 ? "" : "s"} — expand one to see affected resources.`
          : " (up to 50 rows per group)."}
      </p>
      {group ? (
        <section
          id={`wiz-${group.wiz_category}`}
          className={
            group.title_groups?.length
              ? undefined
              : "rounded-lg border border-white/5 bg-neutral-900/40"
          }
        >
          <CategoryBody group={group} />
        </section>
      ) : null}
    </div>
  );
}
