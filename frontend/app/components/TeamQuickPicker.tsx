"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo } from "react";
import { ALL_TEAMS, devTeamKeysForPillar } from "../lib/component-map";
import {
  effectiveDeveloperTeams,
  resolveActiveDeveloperPillar,
} from "../lib/developer-scope";
import { teamRowLabel } from "../lib/team-registry";
import {
  DEVELOPER_PILLAR_TABS,
  type DeveloperPillarTab,
} from "../lib/team-roles";

// ---------------------------------------------------------------------------
// TeamQuickPicker — pillar tabs (Product / Retail / Data) with per-team pills
// under the active tab, mirroring `/platform`'s pillar switcher.
//
// URL state:
//   ?pillar=product|retail|data Active pillar tab (Product is the default).
//   ?team=<key>                  Narrow to one team within the pillar
// ---------------------------------------------------------------------------

export default function TeamQuickPicker() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const pillarParam = searchParams.get("pillar") ?? undefined;
  const selectionTeams = searchParams.getAll("team");

  const activePillar = useMemo(
    () => resolveActiveDeveloperPillar(pillarParam, selectionTeams),
    [pillarParam, selectionTeams],
  );

  const pillarTeams = useMemo(
    () => devTeamKeysForPillar(activePillar),
    [activePillar],
  );

  const effectiveTeams = useMemo(
    () => effectiveDeveloperTeams(activePillar, selectionTeams),
    [activePillar, selectionTeams],
  );

  const allPillarActive =
    selectionTeams.length === 0 ||
    (selectionTeams.length === effectiveTeams.length &&
      selectionTeams.every((t) => effectiveTeams.includes(t)));

  const singleActive =
    selectionTeams.length === 1 ? selectionTeams[0] : null;

  if (ALL_TEAMS.length === 0) return null;

  return (
    <div className="rounded-xl border border-white/5 bg-gradient-to-b from-neutral-900/60 to-neutral-950/60 px-3 py-2.5 shadow-sm space-y-2.5">
      <nav
        className="flex gap-1 rounded-lg border border-neutral-800 bg-neutral-900/50 p-1 w-fit"
        aria-label="Developer pillar"
      >
        {DEVELOPER_PILLAR_TABS.map((tab) => {
          const isActive = activePillar === tab.id;
          return (
            <button
              key={tab.id}
              type="button"
              aria-current={isActive ? "true" : undefined}
              onClick={() => onPillarChange(router, pathname, searchParams, tab.id)}
              className={`rounded-md px-4 py-1.5 text-sm font-medium transition-colors ${
                isActive
                  ? "bg-neutral-700 text-neutral-100"
                  : "text-neutral-400 hover:text-neutral-200 hover:bg-neutral-800/80"
              }`}
            >
              {tab.label}
            </button>
          );
        })}
      </nav>

      <div className="flex flex-wrap items-center gap-1.5">
        <ScopeChip
          label="All teams"
          active={allPillarActive}
          onClick={() =>
            pushScope(router, pathname, searchParams, {
              pillar: activePillar,
              teams: [],
            })
          }
        />
        {pillarTeams.map((team) => (
          <ScopeChip
            key={team}
            label={teamRowLabel(team)}
            active={singleActive === team}
            onClick={() =>
              pushScope(router, pathname, searchParams, {
                pillar: activePillar,
                teams: [team],
              })
            }
          />
        ))}
      </div>
    </div>
  );
}

function ScopeChip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`rounded-full border px-2.5 py-0.5 text-xs font-medium transition-all ${
        active
          ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-700 dark:text-emerald-200 shadow-[0_0_0_1px_rgba(16,185,129,0.25)]"
          : "border-white/5 bg-neutral-900/60 text-neutral-300 hover:border-white/20 hover:bg-neutral-800/80 hover:text-neutral-100"
      }`}
    >
      {label}
    </button>
  );
}

function onPillarChange(
  router: ReturnType<typeof useRouter>,
  pathname: string,
  searchParams: ReturnType<typeof useSearchParams>,
  pillar: DeveloperPillarTab,
): void {
  pushScope(router, pathname, searchParams, {
    pillar,
    teams: [],
    clearRefinements: true,
  });
}

function pushScope(
  router: ReturnType<typeof useRouter>,
  pathname: string,
  searchParams: ReturnType<typeof useSearchParams>,
  opts: {
    pillar: DeveloperPillarTab;
    teams: string[];
    clearRefinements?: boolean;
  },
): void {
  const next = new URLSearchParams(searchParams.toString());
  next.delete("team");

  if (opts.pillar === "product") next.delete("pillar");
  else next.set("pillar", opts.pillar);

  if (opts.clearRefinements) {
    next.delete("source");
    next.delete("severity");
    next.delete("details");
    next.delete("asset");
    next.delete("wiz_category");
  }

  for (const t of opts.teams) next.append("team", t);

  const qs = next.toString();
  router.push(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
}
