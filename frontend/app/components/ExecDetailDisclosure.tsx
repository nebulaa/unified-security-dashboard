"use client";

import type { ReactNode } from "react";

/** Collapsed-by-default wrapper for exec drill-down panels (momentum, trend, …). */
export default function ExecDetailDisclosure({
  children,
}: {
  children: ReactNode;
}) {
  return (
    <details className="group w-full rounded-xl border border-neutral-800/80 bg-neutral-900/20">
      <summary className="flex cursor-pointer select-none items-center justify-center gap-2 px-4 py-3 text-sm font-medium uppercase tracking-wide text-neutral-500 transition-colors hover:text-neutral-300 [&::-webkit-details-marker]:hidden">
        <span>Detail</span>
        <span
          aria-hidden
          className="inline-block text-xs transition-transform group-open:rotate-180"
        >
          ▾
        </span>
      </summary>
      <div className="space-y-6 border-t border-neutral-800/80 p-5 pt-6">
        {children}
      </div>
    </details>
  );
}
