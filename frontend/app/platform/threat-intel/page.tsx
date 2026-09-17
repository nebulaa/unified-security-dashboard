import PlatformThreatIntelList from "./PlatformThreatIntelList";
import { loadPlatformThreatIntelFindings } from "../_shared";

/** Org-wide Wiz Threat Center advisories — no product-line scope or sub-tabs. */
export default async function PlatformThreatIntelPage() {
  const list = await loadPlatformThreatIntelFindings();

  return (
    <div className="space-y-4">
      <div className="space-y-0.5">
        <h1 className="text-2xl font-semibold tracking-tight bg-gradient-to-r from-white to-neutral-400 bg-clip-text text-transparent">
          Threat intel
          <span className="ml-2 align-middle font-mono text-sm text-neutral-500">
            ({list.total})
          </span>
        </h1>
        <p className="text-xs text-neutral-400">
          Wiz Threat Center advisories affecting your environment (last 30 days)
        </p>
      </div>

      <PlatformThreatIntelList items={list.items} total={list.total} />
    </div>
  );
}
