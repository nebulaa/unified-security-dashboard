"use client";

import { useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useTheme } from "../lib/theme";
import type { MetricsTrend, Severity } from "../lib/types";

// ---------------------------------------------------------------------------
// "Open by severity" trend chart.
//
// Visual brief (2026-05-18 refresh): bolder fills + gradients + brighter
// strokes so the critical/high story pops at a glance; date axis formatted as
// "May 18" (no year clutter); larger plot area; tooltip shows the same colour
// dot the chart uses so the legend reads consistently. Default mode = critical
// + high only; "All severities" toggle keeps every series
// available for ad-hoc investigation without re-fetching.
//
// Recharts noise: `ResponsiveContainer`'s `initialDimension` defaults to
// `{ width: -1, height: -1 }`, so the very first internal render Surface
// emits a "width(-1) and height(-1)" warning every time the chart mounts —
// the ResizeObserver fires a moment later with real numbers, but the console
// stays littered. We seed `initialDimension` with the parent box (`h-80` =>
// 320px tall; the width matches the typical card width and is overwritten by
// the observer on the next tick anyway) so the first render is dimensionally
// sane and the warning never fires.
// ---------------------------------------------------------------------------

const ALL_SEVERITIES: Severity[] = ["critical", "high", "medium", "low", "info"];
const DEFAULT_SEVERITIES: Severity[] = ["critical", "high"];

// Brighter, higher-contrast palette than the muted defaults — these are the
// colours users will glance at from across a meeting room, so we lift them up
// from the table palette (which has to coexist with surrounding row text).
// Greens/blues for lower severities stay quiet on purpose so they don't crowd
// the critical+high story when "All severities" is toggled on.
const SEVERITY_COLOR: Record<Severity, string> = {
  critical: "#ef4444",
  high: "#fb923c",
  medium: "#facc15",
  low: "#84cc16",
  info: "#38bdf8",
};

const SEVERITY_LABEL: Record<Severity, string> = {
  critical: "Critical",
  high: "High",
  medium: "Medium",
  low: "Low",
  info: "Info",
};

type Mode = "default" | "all";

// Recharts can't read the `dark` class on `<html>` for us — it expects hard
// colour values for axes / grid / tooltip. We pick the right palette here at
// render time so the chart restyles in lockstep with the theme toggle.
//
// During the brief SSR / pre-hydration window the provider returns `null` for
// theme; we fall back to the dark palette in that case (matches the inline
// script's default-to-dark behaviour).
type ChartPalette = {
  grid: string;
  axisStroke: string;
  axisTick: string;
  legendText: string;
  tooltipBg: string;
  tooltipBorder: string;
  tooltipText: string;
  tooltipLabel: string;
  cursor: string;
  activeDotStroke: string;
};

const DARK_PALETTE: ChartPalette = {
  grid: "#27272a",
  axisStroke: "#3f3f46",
  axisTick: "#d4d4d8",
  legendText: "#d4d4d8",
  tooltipBg: "#0a0a0a",
  tooltipBorder: "#3f3f46",
  tooltipText: "#fafafa",
  tooltipLabel: "#a1a1aa",
  cursor: "#71717a",
  activeDotStroke: "#0a0a0a",
};

const LIGHT_PALETTE: ChartPalette = {
  grid: "#e4e4e7",
  axisStroke: "#a1a1aa",
  axisTick: "#52525b",
  legendText: "#3f3f46",
  tooltipBg: "#ffffff",
  tooltipBorder: "#d4d4d8",
  tooltipText: "#0a0a0a",
  tooltipLabel: "#52525b",
  cursor: "#a1a1aa",
  activeDotStroke: "#ffffff",
};

export default function TrendChart({ trend }: { trend: MetricsTrend }) {
  const [mode, setMode] = useState<Mode>("default");
  const { theme } = useTheme();
  const palette = theme === "light" ? LIGHT_PALETTE : DARK_PALETTE;
  const visible = mode === "default" ? DEFAULT_SEVERITIES : ALL_SEVERITIES;

  // Build a complete per-day matrix once, regardless of `mode`; toggling the
  // mode just controls which `<Area />` instances render. Keeping the same
  // `data` array stable across modes also keeps the y-axis steady when the
  // user switches views (a flicker-free toggle reads as more trustworthy).
  const byDate = new Map<string, Record<Severity, number>>();
  for (const point of trend.points) {
    const row = byDate.get(point.date) ?? {
      critical: 0,
      high: 0,
      medium: 0,
      low: 0,
      info: 0,
    };
    row[point.severity] = point.open_count;
    byDate.set(point.date, row);
  }
  const data = Array.from(byDate.entries())
    .map(([date, row]) => ({ date, ...row }))
    .sort((a, b) => a.date.localeCompare(b.date));

  if (data.length === 0) {
    return (
      <div className="flex h-72 items-center justify-center rounded-lg border border-neutral-800 bg-neutral-900/40 text-sm text-neutral-500">
        no data in window — ingest a snapshot to populate
      </div>
    );
  }

  return (
    // Density pass (2026-05-18): outer container p-3 (was p-4), toggle row
    // mb-2 (was mb-3), and the chart frame itself h-60 = 240px (was h-80 =
    // 320px). The 80px saved here is the second-biggest single compression
    // win on the page after the `main py-5` trim — it puts the bottom of
    // the legend within a standard 800px viewport on /developer when the
    // user lands without scrolling.
    <div className="rounded-lg border border-neutral-800 bg-gradient-to-b from-neutral-900/60 to-neutral-950/40 p-3 shadow-inner">
      <div className="mb-2 flex items-center justify-end gap-1 text-xs">
        <ModePill label="Critical + High" active={mode === "default"} onClick={() => setMode("default")} />
        <ModePill label="All severities" active={mode === "all"} onClick={() => setMode("all")} />
      </div>
      <div className="h-60">
        <ResponsiveContainer
          width="100%"
          height="100%"
          initialDimension={{ width: 600, height: 240 }}
        >
          <AreaChart data={data} margin={{ top: 12, right: 16, left: 0, bottom: 4 }}>
            <defs>
              {ALL_SEVERITIES.map((sev) => (
                // Top-heavy gradient so the band reads as a coloured swatch
                // at its strongest near the line, fading into the background
                // at the baseline — gives every severity its own "weight"
                // without crowding the ones underneath when stacked.
                <linearGradient
                  key={sev}
                  id={`trend-grad-${sev}`}
                  x1="0"
                  y1="0"
                  x2="0"
                  y2="1"
                >
                  <stop offset="0%" stopColor={SEVERITY_COLOR[sev]} stopOpacity={0.85} />
                  <stop offset="100%" stopColor={SEVERITY_COLOR[sev]} stopOpacity={0.15} />
                </linearGradient>
              ))}
            </defs>
            <CartesianGrid stroke={palette.grid} strokeDasharray="2 4" vertical={false} />
            <XAxis
              dataKey="date"
              tick={{ fill: palette.axisTick, fontSize: 11 }}
              tickFormatter={formatDateTick}
              tickMargin={8}
              minTickGap={24}
              stroke={palette.axisStroke}
            />
            <YAxis
              tick={{ fill: palette.axisTick, fontSize: 11 }}
              tickMargin={6}
              allowDecimals={false}
              stroke={palette.axisStroke}
              width={36}
            />
            <Tooltip
              cursor={{ stroke: palette.cursor, strokeDasharray: "3 3" }}
              contentStyle={{
                backgroundColor: palette.tooltipBg,
                border: `1px solid ${palette.tooltipBorder}`,
                borderRadius: 6,
                fontSize: 12,
                color: palette.tooltipText,
                boxShadow: "0 8px 24px rgba(0,0,0,0.25)",
              }}
              labelStyle={{ color: palette.tooltipLabel, marginBottom: 4 }}
              labelFormatter={(label) => formatTooltipLabel(String(label))}
              formatter={(value, name) => [
                value as number,
                SEVERITY_LABEL[name as Severity] ?? String(name),
              ]}
            />
            <Legend
              wrapperStyle={{ fontSize: 12, paddingTop: 8 }}
              iconType="circle"
              formatter={(value: string) => (
                <span style={{ color: palette.legendText }}>
                  {SEVERITY_LABEL[value as Severity] ?? value}
                </span>
              )}
            />
            {visible.map((sev) => (
              <Area
                key={sev}
                type="monotone"
                dataKey={sev}
                stackId="1"
                stroke={SEVERITY_COLOR[sev]}
                strokeWidth={2.5}
                fill={`url(#trend-grad-${sev})`}
                activeDot={{
                  r: 5,
                  stroke: palette.activeDotStroke,
                  strokeWidth: 2,
                  fill: SEVERITY_COLOR[sev],
                }}
              />
            ))}
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function formatDateTick(value: string): string {
  // Inputs are ISO `YYYY-MM-DD` from the backend. Render as "May 18" — the
  // year is implicit on a 30-day window and just adds visual noise to the
  // x-axis. Falls back to the raw string if parsing fails (defensive — the
  // chart should never crash because of a malformed tick).
  const d = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
}

function formatTooltipLabel(value: string): string {
  // The header line of the tooltip — give it the full "Mon, May 18" form so
  // the user can place each hovered point in their week without doing the
  // day-of-week math themselves.
  const d = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

function ModePill({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`rounded border px-2 py-0.5 transition-colors ${
        active
          ? "border-neutral-500 bg-neutral-800 text-neutral-100"
          : "border-neutral-800 bg-neutral-950 text-neutral-400 hover:border-neutral-600 hover:text-neutral-200"
      }`}
    >
      {label}
    </button>
  );
}
