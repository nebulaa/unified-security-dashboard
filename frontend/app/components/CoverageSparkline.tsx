/** 90-day coverage trend. Plain SVG — one polyline, no axes, no interaction. */
import { RAG_STROKE } from "../lib/coverage";
import type { CoverageRag } from "../lib/types";

const WIDTH = 180;
const HEIGHT = 30;
const PADDING = 3;

export default function CoverageSparkline({
  points,
  rag,
  label,
}: {
  points: number[];
  rag: CoverageRag;
  label: string;
}) {
  if (points.length < 2) return null;

  // Scale to the observed band, not 0–100: at 90%+ coverage a full-range axis
  // renders every series as the same flat line near the top.
  const min = Math.min(...points);
  const max = Math.max(...points);
  const span = max - min || 1;
  const stepX = (WIDTH - PADDING * 2) / (points.length - 1);

  const path = points
    .map((value, index) => {
      const x = PADDING + index * stepX;
      const y = PADDING + (1 - (value - min) / span) * (HEIGHT - PADDING * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  return (
    <svg
      width={WIDTH}
      height={HEIGHT}
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      role="img"
      aria-label={`${label}: 90-day trend, ${Math.round(min)}% to ${Math.round(max)}%`}
      className="my-2"
    >
      <polyline
        fill="none"
        stroke={RAG_STROKE[rag]}
        strokeWidth={2}
        strokeLinejoin="round"
        strokeLinecap="round"
        points={path}
      />
    </svg>
  );
}
