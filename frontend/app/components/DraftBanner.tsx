/** Shared work-in-progress indicator for views still being refined. */
export default function DraftBanner() {
  return (
    <div
      className="flex w-full items-center justify-center gap-3 rounded-lg border border-amber-300/50 bg-gradient-to-r from-amber-50/90 via-amber-50/70 to-amber-50/90 px-4 py-2 dark:border-amber-700/40 dark:from-amber-950/30 dark:via-amber-950/20 dark:to-amber-950/30"
      role="note"
      aria-label="Draft — work in progress"
    >
      <span className="rounded-md border border-amber-400/60 bg-amber-100/80 px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.2em] text-amber-900 dark:border-amber-600/50 dark:bg-amber-900/50 dark:text-amber-100">
        Draft
      </span>
      <span className="hidden h-3 w-px bg-amber-300/70 dark:bg-amber-600/50 sm:block" />
      <span className="text-xs font-medium tracking-wide text-amber-900/90 dark:text-amber-100/90">
        Work in progress
      </span>
    </div>
  );
}
