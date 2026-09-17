import type { Config } from "tailwindcss";

// Theming model
// -------------
// The dashboard supports both light and dark colour schemes via a class-based
// theme toggle (see `ThemeProvider` + `ThemeToggle`). Rather than duplicating
// every component with `dark:` variants, we redefine the `neutral` and `white`
// palettes as CSS variables and *invert* their values between the two themes
// in `globals.css`. The practical effect:
//
//   - `bg-neutral-950` resolves to a near-black surface in dark mode and a
//     near-white surface in light mode.
//   - `text-neutral-100` resolves to near-white text in dark mode and near-
//     black text in light mode.
//   - `border-white/5` is a faint white-over-dark divider in dark mode and a
//     faint black-over-light divider in light mode.
//
// Severity-tone palettes (red / amber / emerald / blue / orange / lime / sky /
// purple) are *not* inverted — those colours convey semantic meaning (critical
// = red, high = orange, etc.) and must read the same way in both modes. The
// components that use severity-tinted backgrounds add explicit `dark:` over-
// rides for the contrast-sensitive cases.

const config: Config = {
  content: ["./app/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        white: "rgb(var(--c-fg) / <alpha-value>)",
        neutral: {
          50: "rgb(var(--c-neutral-50) / <alpha-value>)",
          100: "rgb(var(--c-neutral-100) / <alpha-value>)",
          200: "rgb(var(--c-neutral-200) / <alpha-value>)",
          300: "rgb(var(--c-neutral-300) / <alpha-value>)",
          400: "rgb(var(--c-neutral-400) / <alpha-value>)",
          500: "rgb(var(--c-neutral-500) / <alpha-value>)",
          600: "rgb(var(--c-neutral-600) / <alpha-value>)",
          700: "rgb(var(--c-neutral-700) / <alpha-value>)",
          800: "rgb(var(--c-neutral-800) / <alpha-value>)",
          900: "rgb(var(--c-neutral-900) / <alpha-value>)",
          950: "rgb(var(--c-neutral-950) / <alpha-value>)",
        },
        sev: {
          critical: "#DC2626",
          high: "#EA580C",
          medium: "#D97706",
          low: "#65A30D",
          info: "#2563EB",
        },
      },
    },
  },
  plugins: [],
  darkMode: "class",
};
export default config;
