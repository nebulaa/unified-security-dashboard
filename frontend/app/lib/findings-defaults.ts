// Pure helpers for the findings table's default filter/sort state.
//
// Lives in its own module (no React, no "use client") so it can be imported by
// both the client `FindingsTable` component and the server pages that prefetch
// the same dataset for SSR `initialData`. Next 16 enforces the server/client
// import boundary, so we cannot import these from a "use client" file.

import type { Severity, Status } from "./types";

// Security review focuses on criticals + highs by default; the user can toggle
// medium/low/info on as needed.
export const DEFAULT_SEVERITIES: Severity[] = ["critical", "high"];

/** Active lifecycle states shown in list views (excludes auto_closed, fixed, …). */
export const DEFAULT_OPEN_STATUSES: Status[] = [
  "open",
  "triaged",
  "in_progress",
];

/**
 * Build the same query string the table will use on first render, so server-side
 * pages can prefetch the matching dataset and pass it as `initialData`.
 *
 * Pass `extra` for things like `limit=200` or `team=unowned` (locked params).
 * Array values are emitted as repeated query params (FastAPI parses repeats
 * into a list) — e.g. `{ team: ["a", "b"] }` produces `?team=a&team=b`. This
 * is how the Platform view pins teams per pillar tab.
 */
export function defaultFindingsQuery(
  extra: Record<string, string | readonly string[]> = {},
): string {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(extra)) {
    if (Array.isArray(v)) {
      for (const item of v) params.append(k, item);
    } else {
      params.append(k, v as string);
    }
  }
  for (const s of DEFAULT_SEVERITIES) params.append("severity", s);
  if (!extra.status) {
    for (const s of DEFAULT_OPEN_STATUSES) params.append("status", s);
  }
  params.append("sort_by", "severity");
  params.append("sort_dir", "asc");
  return params.toString();
}
