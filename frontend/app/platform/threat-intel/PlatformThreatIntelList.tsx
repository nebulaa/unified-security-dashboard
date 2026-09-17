"use client";

import type { FindingSummary } from "../../lib/types";
import SeverityPill from "../../components/SeverityPill";

function ThreatIntelRow({ f }: { f: FindingSummary }) {
  return (
    <li className="flex flex-wrap items-start gap-x-3 gap-y-1 px-4 py-3 text-sm">
      <SeverityPill severity={f.severity} />
      <div className="min-w-0 flex-1">
        <div className="font-medium text-neutral-100">{f.title}</div>
        <div className="mt-0.5 text-xs text-neutral-500">
          Published {Math.round(f.age_days)}d ago
          {f.sla_breached ? (
            <span className="ml-1 text-red-400">SLA breached</span>
          ) : null}
        </div>
      </div>
      {f.upstream_url ? (
        <a
          href={f.upstream_url}
          target="_blank"
          rel="noopener noreferrer"
          className="shrink-0 text-xs font-medium text-emerald-400 hover:text-emerald-300"
        >
          Open in Wiz ↗
        </a>
      ) : null}
    </li>
  );
}

export default function PlatformThreatIntelList({
  items,
  total,
}: {
  items: FindingSummary[];
  total: number;
}) {
  if (total === 0) {
    return (
      <p className="rounded-lg border border-white/5 bg-neutral-900/50 px-4 py-8 text-sm text-neutral-400">
        No Wiz Threat Center advisories affecting your environment in the last
        30 days.
      </p>
    );
  }

  return (
    <div className="space-y-2">
      <p className="text-xs text-neutral-500">
        {total} active advisor{total === 1 ? "y" : "ies"} with impact in your
        environment.
        {total > items.length
          ? ` Showing ${items.length} (increase limit to see more).`
          : null}
      </p>
      <ul className="divide-y divide-white/5 rounded-lg border border-white/5 bg-neutral-900/40">
        {items.map((f) => (
          <ThreatIntelRow key={f.id} f={f} />
        ))}
      </ul>
    </div>
  );
}
