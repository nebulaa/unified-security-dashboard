"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import type { DlqEventItem, DlqListResponse } from "../lib/types";

export default function DlqEventsPanel({
  initial,
}: {
  initial: DlqListResponse;
}) {
  const router = useRouter();
  const [items, setItems] = useState(initial.items);
  const [unresolvedCount, setUnresolvedCount] = useState(initial.unresolved_count);
  const [pendingId, setPendingId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function resolveEvent(id: number) {
    setPendingId(id);
    setError(null);
    try {
      const res = await fetch(`/api/proxy/admin/dlq/${id}/resolve`, {
        method: "POST",
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(
          (body as { detail?: string }).detail ?? `resolve failed (${res.status})`,
        );
      }
      const updated = (await res.json()) as DlqEventItem;
      setItems((prev) =>
        prev.map((row) => (row.id === id ? { ...row, ...updated } : row)),
      );
      if (updated.resolved_at) {
        setUnresolvedCount((c) => Math.max(0, c - 1));
      }
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "resolve failed");
    } finally {
      setPendingId(null);
    }
  }

  if (items.length === 0) {
    return (
      <div className="rounded border border-neutral-800 bg-neutral-900/30 px-4 py-6 text-center text-sm text-neutral-400">
        No failed ingests in the dead-letter queue.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {error ? (
        <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
      ) : null}
      <p className="text-xs text-neutral-500">
        {unresolvedCount} unresolved · mark resolved after triage (no automatic replay)
      </p>
      <table className="w-full overflow-hidden rounded border border-neutral-800 text-sm">
        <thead className="bg-neutral-900/80 text-xs uppercase tracking-wide text-neutral-400">
          <tr>
            <th className="px-3 py-2 text-left">Received</th>
            <th className="px-3 py-2 text-left">Source</th>
            <th className="px-3 py-2 text-left">Poll</th>
            <th className="px-3 py-2 text-left">Attempts</th>
            <th className="px-3 py-2 text-left">Reason</th>
            <th className="px-3 py-2 text-right">Action</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-neutral-900">
          {items.map((row) => (
            <tr
              key={row.id}
              className={`bg-neutral-950/40 ${row.resolved_at ? "opacity-60" : ""}`}
            >
              <td className="px-3 py-2 text-neutral-400">{row.received_at}</td>
              <td className="px-3 py-2 font-mono text-neutral-200">
                {row.source ?? "—"}
              </td>
              <td className="px-3 py-2 font-mono text-xs text-neutral-400">
                {row.poll_id ?? "—"}
              </td>
              <td className="px-3 py-2 text-neutral-300">{row.delivery_attempt}</td>
              <td className="px-3 py-2 text-neutral-400">
                {row.failure_reason ?? "—"}
              </td>
              <td className="px-3 py-2 text-right">
                {row.resolved_at ? (
                  <span className="text-xs text-neutral-500">resolved</span>
                ) : (
                  <button
                    type="button"
                    disabled={pendingId === row.id}
                    onClick={() => resolveEvent(row.id)}
                    className="rounded border border-neutral-700 px-2 py-1 text-xs text-neutral-200 hover:bg-neutral-800 disabled:opacity-50"
                  >
                    {pendingId === row.id ? "…" : "Mark resolved"}
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
