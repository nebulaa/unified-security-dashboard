import type { MetricsSummary, SecurityPosture } from "./types";

export type ExecTone = "neutral" | "ok" | "warn" | "bad";

export function formatMttr(seconds: number | null): string {
  if (seconds == null) return "—";
  const days = seconds / 86_400;
  if (days < 1) return `${Math.round(seconds / 3600)}h`;
  return `${days.toFixed(1)}d`;
}

export function formatOldestAge(seconds: number | null): string {
  if (seconds == null) return "—";
  const days = seconds / 86_400;
  if (days < 1) return `${Math.round(seconds / 3600)}h`;
  return `${Math.round(days)}d`;
}

export function observationDays(observedSinceIso: string | null): number | null {
  if (!observedSinceIso) return null;
  const since = new Date(observedSinceIso).getTime();
  if (Number.isNaN(since)) return null;
  return (Date.now() - since) / 86_400_000;
}

export function slaTone(pct: number | null): ExecTone {
  if (pct == null) return "neutral";
  if (pct >= 95) return "ok";
  if (pct >= 80) return "warn";
  return "bad";
}

export function oldestAgeTone(seconds: number | null): ExecTone {
  if (seconds == null) return "neutral";
  const days = seconds / 86_400;
  if (days > 90) return "bad";
  if (days > 30) return "warn";
  return "ok";
}

export function countTone(count: number | null, warnAbove = 0): ExecTone {
  if (count == null) return "neutral";
  if (count === 0) return "ok";
  if (count > warnAbove) return "bad";
  return "warn";
}

export interface WeekOverWeekDisplay {
  text: string;
  hint?: string;
}

export function buildWeekOverWeekDisplay(
  summary: MetricsSummary | null,
  obsDays: number | null,
): WeekOverWeekDisplay {
  if (summary == null) return { text: "—" };
  if (summary.open_criticals_wow_delta == null) {
    return {
      text: "—",
      hint: obsDays == null ? "no data" : "history < 7d",
    };
  }
  const d = summary.open_criticals_wow_delta;
  if (d === 0) return { text: "unchanged vs last week" };
  return { text: `${d >= 0 ? "+" : ""}${d} criticals vs last week` };
}

export function buildMttrHint(
  summary: MetricsSummary | null,
  obsDays: number | null,
): string | undefined {
  if (summary == null) return undefined;
  if (summary.mttr_critical_30d_seconds != null) return undefined;
  if (obsDays != null && obsDays < 30) return "history < 30d";
  return "no closures in 30d";
}

export interface BurnDown7dDisplay {
  text: string;
  tone: ExecTone;
  hint?: string;
}

/** Compact 7-day critical inflow/outflow for pillar headers. */
export function buildBurnDown7dDisplay(
  summary: MetricsSummary | null,
): BurnDown7dDisplay {
  const incoming = summary?.new_critical_7d ?? null;
  const closed = summary?.closed_critical_7d ?? null;
  if (incoming == null || closed == null) {
    return { text: "7d burn-down —", tone: "neutral", hint: "history < 7d" };
  }
  const net = incoming - closed;
  if (net < 0) {
    return {
      text: `7d: ${incoming} new · ${closed} closed · ↓${Math.abs(net)}`,
      tone: "ok",
    };
  }
  if (net > 0) {
    return {
      text: `7d: ${incoming} new · ${closed} closed · ↑${net}`,
      tone: "bad",
    };
  }
  return {
    text: `7d: ${incoming} new · ${closed} closed · stable`,
    tone: "neutral",
  };
}

export function staleCount(summary: MetricsSummary | null): number {
  return summary?.age_buckets_open_crit_high?.gt_90d ?? 0;
}

export function ratingTone(grade: SecurityPosture["rating"] | undefined): ExecTone {
  if (grade === "A") return "ok";
  if (grade === "B") return "warn";
  if (grade === "C" || grade === "D") return "bad";
  return "neutral";
}
