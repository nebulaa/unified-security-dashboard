import type { RatingScoreBreakdown } from "../lib/types";

const RATING_CONFIG = {
  A: {
    bg: "bg-emerald-50 dark:bg-emerald-950/60",
    border: "border-emerald-300 dark:border-emerald-700/50",
    letter: "text-emerald-700 dark:text-emerald-300",
    label: "Strong posture",
    desc: "No critical issues and strong SLA adherence.",
  },
  B: {
    bg: "bg-blue-50 dark:bg-blue-950/60",
    border: "border-blue-300 dark:border-blue-700/50",
    letter: "text-blue-700 dark:text-blue-300",
    label: "Good posture",
    desc: "Minor gaps in SLA or a small number of highs to address.",
  },
  C: {
    bg: "bg-amber-50 dark:bg-amber-950/60",
    border: "border-amber-300 dark:border-amber-700/50",
    letter: "text-amber-700 dark:text-amber-300",
    label: "Needs attention",
    desc: "Open criticals or notable SLA breaches require remediation.",
  },
  D: {
    bg: "bg-red-50 dark:bg-red-950/60",
    border: "border-red-300 dark:border-red-700/50",
    letter: "text-red-700 dark:text-red-400",
    label: "Critical risk",
    desc: "Significant open criticals or severe SLA non-compliance.",
  },
};

function ScoreBar({
  label,
  value,
  max,
}: {
  label: string;
  value: number;
  max: number;
}) {
  const pct = Math.round((value / max) * 100);
  const color =
    pct >= 80
      ? "bg-emerald-500"
      : pct >= 50
        ? "bg-amber-500"
        : "bg-red-500";
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs text-neutral-400">
        <span>{label}</span>
        <span className="font-mono text-neutral-300">
          {value}/{max}
        </span>
      </div>
      <div className="h-1.5 w-full rounded-full bg-neutral-800">
        <div
          className={`h-1.5 rounded-full ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

export default function SecurityRatingBadge({
  rating,
  score,
  breakdown,
}: {
  rating: "A" | "B" | "C" | "D";
  score: number;
  breakdown: RatingScoreBreakdown;
}) {
  const cfg = RATING_CONFIG[rating];
  return (
    <div
      className={`rounded-lg border ${cfg.border} ${cfg.bg} p-5 flex flex-col gap-4`}
    >
      <div className="flex items-start gap-5">
        <div
          className={`text-7xl font-black leading-none ${cfg.letter} tabular-nums`}
        >
          {rating}
        </div>
        <div className="flex flex-col justify-center">
          <div className="text-sm font-medium text-neutral-100">{cfg.label}</div>
          <div className="text-xs text-neutral-400 mt-0.5">{cfg.desc}</div>
          <div className="text-xs text-neutral-500 mt-2">
            Score{" "}
            <span className="font-mono text-neutral-300">{score}/100</span>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-x-6 gap-y-2.5 pt-1 border-t border-neutral-800">
        <ScoreBar label="No criticals" value={breakdown.criticals_score} max={35} />
        <ScoreBar label="SLA compliance" value={breakdown.sla_score} max={35} />
        <ScoreBar label="MTTR (criticals)" value={breakdown.mttr_score} max={15} />
        <ScoreBar label="Low high count" value={breakdown.highs_score} max={15} />
      </div>
    </div>
  );
}
