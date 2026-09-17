/**
 * Presentation helpers for the coverage section.
 *
 * The RAG band is decided by the backend (thresholds live in `coverage.yaml`);
 * the frontend only maps a band to colour so a threshold change never needs a
 * UI deploy.
 */
import type { CoverageRag, CoverageRatio } from "./types";

export const RAG_TEXT: Record<CoverageRag, string> = {
  green: "text-emerald-700 dark:text-emerald-400",
  amber: "text-amber-700 dark:text-amber-400",
  red: "text-red-600 dark:text-red-400",
  na: "text-neutral-500",
};

export const RAG_ACCENT: Record<CoverageRag, string> = {
  green: "border-t-emerald-600 dark:border-t-emerald-500",
  amber: "border-t-amber-600 dark:border-t-amber-500",
  red: "border-t-red-600 dark:border-t-red-500",
  na: "border-t-neutral-700",
};

export const RAG_STROKE: Record<CoverageRag, string> = {
  green: "#10b981",
  amber: "#f59e0b",
  red: "#ef4444",
  na: "#71717a",
};

/** `null` means the denominator is empty — say so rather than implying success. */
export function formatPct(pct: number | null): string {
  return pct == null ? "n/a" : `${Math.round(pct)}%`;
}

export function formatCounts(ratio: CoverageRatio, unit: string): string {
  return `${ratio.covered} / ${ratio.in_scope} ${unit}`;
}

export function formatDelta(deltaPts: number | null): string | null {
  if (deltaPts == null) return null;
  const rounded = Math.round(deltaPts);
  if (rounded === 0) return "— vs last month";
  const arrow = rounded > 0 ? "▲" : "▼";
  const pts = Math.abs(rounded) === 1 ? "pt" : "pts";
  return `${arrow} ${Math.abs(rounded)} ${pts} vs last month`;
}

export function deltaTone(deltaPts: number | null): string {
  if (deltaPts == null || Math.round(deltaPts) === 0) return "text-neutral-500";
  return deltaPts > 0
    ? "text-emerald-700 dark:text-emerald-400"
    : "text-red-600 dark:text-red-400";
}

/** "6 excepted · 21 gaps" — both stay visible; an exception is not a pass. */
export function formatExceptions(ratio: CoverageRatio): string {
  const parts = [`${ratio.excepted} excepted`];
  if (ratio.gaps > 0) parts.push(`${ratio.gaps} ${ratio.gaps === 1 ? "gap" : "gaps"}`);
  return parts.join(" · ");
}

export function formatAsOf(asOf: string): string {
  const parsed = new Date(asOf);
  if (Number.isNaN(parsed.getTime())) return asOf;
  return parsed.toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  });
}

/** First few uncovered items, for the tile's hover text. */
export function gapPreview(gapItems: string[]): string | undefined {
  if (gapItems.length === 0) return undefined;
  const shown = gapItems.slice(0, 8).join(", ");
  const rest = gapItems.length - 8;
  return rest > 0 ? `Uncovered: ${shown} (+${rest} more)` : `Uncovered: ${shown}`;
}
