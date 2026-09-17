"use client";

import { useState } from "react";

import type { PollerInfo, PollerListResponse, PollerRunResponse } from "../lib/types";

const LABELS: Record<string, string> = {
  dependabot: "Dependabot",
  sonarcloud: "SonarCloud",
};

export default function PollersPanel({ initial }: { initial: PollerListResponse }) {
  const [items] = useState(initial.items);
  const [slackConfigured] = useState(initial.slack_configured);
  const [pending, setPending] = useState<string | null>(null);
  const [lastRun, setLastRun] = useState<PollerRunResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function runPoller(source: string) {
    setPending(source);
    setError(null);
    try {
      const res = await fetch(`/api/proxy/admin/pollers/${source}/run`, {
        method: "POST",
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(
          (body as { detail?: string }).detail ?? `run failed (${res.status})`,
        );
      }
      setLastRun((await res.json()) as PollerRunResponse);
    } catch (e) {
      setError(e instanceof Error ? e.message : "run failed");
    } finally {
      setPending(null);
    }
  }

  return (
    <div className="space-y-3">
      {error ? (
        <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
      ) : null}
      {lastRun ? (
        <p className="text-xs text-emerald-700 dark:text-emerald-400">
          {lastRun.message}
          {lastRun.execution_name ? (
            <span className="ml-2 font-mono text-neutral-500">
              {lastRun.execution_name}
            </span>
          ) : null}
        </p>
      ) : null}
      <p className="text-xs text-neutral-500">
        {items[0]?.trigger_mode === "cloud_run"
          ? "Starts the same Cloud Run Jobs as the 30-minute scheduler."
          : "Runs pollers in-process (local dev)."}
        {slackConfigured
          ? " DLQ ingest failures post to Slack."
          : " Slack webhook not configured — DLQ alerts are admin-page only."}
      </p>
      <div className="flex flex-wrap gap-3">
        {items.map((p: PollerInfo) => (
          <button
            key={p.source}
            type="button"
            disabled={pending === p.source}
            onClick={() => runPoller(p.source)}
            className="rounded border border-neutral-700 bg-neutral-900/50 px-4 py-2 text-sm text-neutral-100 hover:bg-neutral-800 disabled:opacity-50"
          >
            {pending === p.source
              ? "Starting…"
              : `Run ${LABELS[p.source] ?? p.source}`}
          </button>
        ))}
      </div>
    </div>
  );
}
