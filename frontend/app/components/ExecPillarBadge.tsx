/** Non-interactive pillar card — open critical + high counts. */
export default function ExecPillarBadge({
  label,
  description,
  openCriticals,
  openHighs,
}: {
  label: string;
  description: string;
  openCriticals: number | null;
  openHighs: number | null;
}) {
  const hasCriticals = openCriticals != null && openCriticals > 0;

  return (
    <div
      className="flex h-full min-h-[8rem] flex-col items-center justify-center rounded-xl border border-neutral-800/80 bg-gradient-to-br from-neutral-900/70 to-neutral-950/40 p-5 shadow-sm"
      title={description}
    >
      <span className="mb-4 text-center text-lg font-semibold tracking-tight text-neutral-100">
        {label}
      </span>

      <div className="flex items-end justify-center gap-x-10 gap-y-4">
        <div className="text-center">
          <div
            className={`text-4xl font-semibold tabular-nums leading-none ${
              hasCriticals
                ? "text-red-600 dark:text-red-400"
                : "text-emerald-600 dark:text-emerald-400"
            }`}
          >
            {openCriticals ?? "—"}
          </div>
          <div className="mt-1.5 text-xs uppercase tracking-wider text-neutral-500">
            critical
          </div>
        </div>
        <div className="h-12 w-px bg-neutral-700" />
        <div className="text-center">
          <div className="text-4xl font-semibold tabular-nums leading-none text-amber-700 dark:text-amber-400">
            {openHighs ?? "—"}
          </div>
          <div className="mt-1.5 text-xs uppercase tracking-wider text-neutral-500">
            high
          </div>
        </div>
      </div>
    </div>
  );
}
