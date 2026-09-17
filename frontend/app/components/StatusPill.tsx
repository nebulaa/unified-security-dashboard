import type { Status } from "../lib/types";

// Severity-tone palettes (red / amber / blue / emerald / purple) aren't
// inverted by the palette swap — pale tints for light mode are paired with
// the dark-mode classes via the `dark:` prefix. Neutral pills auto-invert.
const STYLE: Record<Status, string> = {
  open:
    "bg-red-100 text-red-700 border-red-300 dark:bg-red-900/40 dark:text-red-200 dark:border-red-700",
  triaged:
    "bg-amber-100 text-amber-700 border-amber-300 dark:bg-amber-900/40 dark:text-amber-200 dark:border-amber-700",
  in_progress:
    "bg-blue-100 text-blue-700 border-blue-300 dark:bg-blue-900/40 dark:text-blue-200 dark:border-blue-700",
  fixed:
    "bg-emerald-100 text-emerald-700 border-emerald-300 dark:bg-emerald-900/40 dark:text-emerald-200 dark:border-emerald-700",
  auto_closed: "bg-neutral-800/60 text-neutral-300 border-neutral-600",
  risk_accepted:
    "bg-purple-100 text-purple-700 border-purple-300 dark:bg-purple-900/40 dark:text-purple-200 dark:border-purple-700",
  suppressed: "bg-neutral-800/60 text-neutral-400 border-neutral-700",
};

export default function StatusPill({ status }: { status: Status }) {
  return (
    <span
      className={`inline-flex rounded border px-2 py-0.5 text-xs uppercase tracking-wide ${STYLE[status]}`}
    >
      {status.replace("_", " ")}
    </span>
  );
}
