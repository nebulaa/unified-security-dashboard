"use client";

import { useState } from "react";

import type {
  OwnershipReresolveResponse,
  OwnershipStatusResponse,
} from "../lib/types";

export default function OwnershipReresolvePanel({
  initial,
}: {
  initial: OwnershipStatusResponse;
}) {
  const [status] = useState(initial);
  const [pending, setPending] = useState(false);
  const [lastRun, setLastRun] = useState<OwnershipReresolveResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function reresolve() {
    setPending(true);
    setError(null);
    try {
      const res = await fetch("/api/proxy/admin/ownership/reresolve", {
        method: "POST",
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(
          (body as { detail?: string }).detail ?? `run failed (${res.status})`,
        );
      }
      setLastRun((await res.json()) as OwnershipReresolveResponse);
    } catch (e) {
      setError(e instanceof Error ? e.message : "run failed");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-xs text-neutral-500">
        Re-stamps <code className="text-neutral-400">Finding.owner_team</code> from{" "}
        <code className="text-neutral-400">ownership.yaml</code> and emits{" "}
        <code className="text-neutral-400">ownership_changed</code> events. Unowned:{" "}
        <span className="font-mono text-neutral-300">{status.unowned_count}</span>
        {status.excluded_count > 0 ? (
          <>
            {" "}
            · excluded:{" "}
            <span className="font-mono text-neutral-300">{status.excluded_count}</span>
          </>
        ) : null}
        {status.ownership_changed_7d > 0 ? (
          <>
            {" "}
            · {status.ownership_changed_7d} ownership changes (7d)
          </>
        ) : null}
      </p>
      {error ? (
        <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
      ) : null}
      {lastRun ? (
        <div className="space-y-1 text-xs text-emerald-700 dark:text-emerald-400">
          <p>{lastRun.message}</p>
          {lastRun.updated != null && lastRun.scanned != null ? (
            <p>
              Updated {lastRun.updated} of {lastRun.scanned} findings
              {lastRun.rollup_triggered ? " · 30d rollup backfill ran" : ""}
            </p>
          ) : null}
          {lastRun.by_transition && Object.keys(lastRun.by_transition).length > 0 ? (
            <ul className="font-mono text-neutral-500">
              {Object.entries(lastRun.by_transition)
                .slice(0, 8)
                .map(([k, v]) => (
                  <li key={k}>
                    {k}: {v}
                  </li>
                ))}
            </ul>
          ) : null}
          {lastRun.execution_name ? (
            <p className="font-mono text-neutral-500">{lastRun.execution_name}</p>
          ) : null}
          {lastRun.mode === "cloud_run" ? (
            <p className="text-neutral-500">
              Check the ownership re-resolution job logs for full per-team
              deltas.
            </p>
          ) : null}
        </div>
      ) : null}
      <p className="text-xs text-neutral-500">
        {status.trigger_mode === "cloud_run"
          ? "Starts ownership re-resolution on Cloud SQL (chains a 30-day rollup when rows change)."
          : "Runs in-process against local Postgres."}
      </p>
      <button
        type="button"
        disabled={pending}
        onClick={reresolve}
        className="rounded border border-neutral-700 bg-neutral-900/50 px-4 py-2 text-sm text-neutral-100 hover:bg-neutral-800 disabled:opacity-50"
      >
        {pending ? "Running…" : "Re-resolve ownership"}
      </button>
    </div>
  );
}
