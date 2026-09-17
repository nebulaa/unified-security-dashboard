import type { ReactNode } from "react";

/**
 * Zero-JS disclosure wrapper for the findings table.
 *
 * The dashboard's first paint is charts-only on every role view; the
 * table sits behind this `<details>` so users opt in to the row-by-row exploration
 * rather than getting walls of data on landing. We use the native HTML element on
 * purpose: it works without React Query, without JS-blocking paint, and the open
 * state survives a full server round-trip when authored with `defaultOpen`.
 *
 * `summary` is the always-visible affordance ("Show 540 findings ▾"). When the user
 * clicks it, `children` mounts and the FindingsTable inside fires its initial fetch
 * (or hydrates from `initialData`). When collapsed, neither the table nor any of its
 * downstream queries renders.
 */
export default function FindingsDisclosure({
  summary,
  hint,
  children,
  defaultOpen = false,
}: {
  summary: ReactNode;
  hint?: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
}) {
  return (
    <details
      open={defaultOpen || undefined}
      className="group rounded-lg border border-neutral-800 bg-neutral-900/30 open:bg-neutral-900/40"
    >
      <summary className="flex cursor-pointer select-none items-center justify-between gap-3 px-4 py-3 text-sm hover:bg-neutral-900/60 [&::-webkit-details-marker]:hidden">
        <div className="flex items-center gap-2 text-neutral-200">
          <span
            aria-hidden
            className="inline-block w-3 transition-transform group-open:rotate-90 text-neutral-500"
          >
            ▸
          </span>
          <span className="font-medium">{summary}</span>
        </div>
        {hint ? <span className="text-xs text-neutral-500">{hint}</span> : null}
      </summary>
      <div className="border-t border-neutral-800 p-4">{children}</div>
    </details>
  );
}
