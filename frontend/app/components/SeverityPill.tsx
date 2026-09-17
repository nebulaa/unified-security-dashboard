import type { Severity } from "../lib/types";

// Severity tones aren't inverted by the palette swap (red == red in both
// themes — that's the whole point of severity colour-coding). We instead
// pair a pale light-mode tint with the existing dark-mode chip and let the
// `dark:` prefix do the switch.
const STYLE: Record<Severity, string> = {
  critical:
    "bg-red-100 text-red-700 border-red-300 dark:bg-red-900/50 dark:text-red-200 dark:border-red-700",
  high:
    "bg-orange-100 text-orange-700 border-orange-300 dark:bg-orange-900/50 dark:text-orange-200 dark:border-orange-700",
  medium:
    "bg-amber-100 text-amber-700 border-amber-300 dark:bg-amber-900/40 dark:text-amber-200 dark:border-amber-700",
  low:
    "bg-lime-100 text-lime-700 border-lime-300 dark:bg-lime-900/40 dark:text-lime-200 dark:border-lime-700",
  info:
    "bg-blue-100 text-blue-700 border-blue-300 dark:bg-blue-900/40 dark:text-blue-200 dark:border-blue-700",
};

export default function SeverityPill({ severity }: { severity: Severity }) {
  return (
    <span
      className={`inline-flex rounded border px-2 py-0.5 text-xs uppercase tracking-wide ${STYLE[severity]}`}
    >
      {severity}
    </span>
  );
}
