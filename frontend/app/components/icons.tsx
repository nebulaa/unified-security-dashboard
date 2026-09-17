/**
 * Tiny inline-SVG icon set. We deliberately don't pull in a full icon library
 * (lucide-react, react-icons, …) for two pictograms — a 40-line file is less
 * code than the bundle hit. Both icons are 16×16 by default to match the
 * code-coverage tool UI we're mirroring (see `image.png` reference).
 *
 * Both icons inherit `currentColor` so callers can theme them with Tailwind
 * text-color utilities (`text-neutral-400 hover:text-neutral-100`).
 *
 * Where the marks come from:
 *   - GitHub: the official mark, transcribed from github.com/logos.
 *   - SonarCloud: cloud silhouette with three sonar pulses emanating inside,
 *     matching the SonarSource brand shape (see `image copy.png` reference).
 *     The cloud outline is the standard Heroicons "cloud" path; the trio of
 *     concentric arcs is the SonarSource radar metaphor. We don't transcribe
 *     the corporate mark verbatim — it's trademarked and the link lands on
 *     sonarcloud.io regardless — but the silhouette is distinct enough to
 *     read as "SonarCloud" at a glance.
 */

import type { SVGProps } from "react";

type IconProps = Omit<SVGProps<SVGSVGElement>, "viewBox" | "fill" | "xmlns"> & {
  size?: number;
};

export function GitHubIcon({ size = 16, ...rest }: IconProps) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 16 16"
      width={size}
      height={size}
      fill="currentColor"
      aria-hidden="true"
      {...rest}
    >
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
    </svg>
  );
}

export function SonarCloudIcon({ size = 16, ...rest }: IconProps) {
  // Cloud silhouette + three sonar pulses inside it (per `image copy.png`).
  // 24×24 viewBox gives the cloud curves enough headroom to read at the
  // 16px render size we use in the per-service table — at 16×16 the cloud
  // path becomes mush. Stroke-width 1.8 in viewBox space ≈ 1.2px on screen
  // at 16×16, comparable to the GitHub mark beside it.
  //
  // Anatomy:
  //   - Cloud: Heroicons v2 cloud path (outline form).
  //   - Sonar: three concentric arcs centred at (8, 17) — a point inside the
  //     lower-left of the cloud body — sweeping up-and-right at increasing
  //     radii (3 → 5 → 7). Reads as "radar pulses from inside the cloud".
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...rest}
    >
      {/* Cloud outline */}
      <path d="M2.25 15a4.5 4.5 0 0 0 4.5 4.5H18a3.75 3.75 0 0 0 1.332-7.257 3 3 0 0 0-3.758-3.848 5.25 5.25 0 0 0-10.233 2.33A4.502 4.502 0 0 0 2.25 15Z" />
      {/* Sonar pulses — three concentric quarter arcs from origin (8, 17) */}
      <path d="M8 14 A 3 3 0 0 1 11 17" />
      <path d="M8 12 A 5 5 0 0 1 13 17" />
      <path d="M8 10 A 7 7 0 0 1 15 17" />
    </svg>
  );
}
