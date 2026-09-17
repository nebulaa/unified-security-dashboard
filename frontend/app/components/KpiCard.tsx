type Tone = "neutral" | "ok" | "warn" | "bad";

// Border tones — semantic palettes carry a pale-light + dark pair via the
// `dark:` prefix; the neutral border auto-inverts through the palette swap.
const TONE_BORDER: Record<Tone, string> = {
  neutral: "border-neutral-800",
  ok: "border-emerald-300 dark:border-emerald-700/50",
  warn: "border-amber-300 dark:border-amber-700/50",
  bad: "border-red-300 dark:border-red-700/50",
};

const TONE_VALUE: Record<Tone, string> = {
  neutral: "text-neutral-100",
  ok: "text-emerald-700 dark:text-emerald-300",
  warn: "text-amber-700 dark:text-amber-300",
  bad: "text-red-700 dark:text-red-400",
};

export default function KpiCard({
  label,
  value,
  delta,
  tone = "neutral",
  hint,
}: {
  label: string;
  value: string | number;
  delta?: string;
  tone?: Tone;
  hint?: string;
}) {
  return (
    <div
      className={`flex h-full min-h-[6.5rem] flex-col rounded-lg border ${TONE_BORDER[tone]} bg-neutral-900/40 p-4`}
    >
      <div className="text-xs uppercase tracking-wide text-neutral-500">{label}</div>
      <div className={`mt-2 text-3xl font-semibold ${TONE_VALUE[tone]}`}>{value}</div>
      <div className="mt-1 flex items-center gap-2 text-xs text-neutral-400">
        {delta && <span>{delta}</span>}
        {hint && <span>{hint}</span>}
      </div>
    </div>
  );
}
