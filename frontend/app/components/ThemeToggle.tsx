"use client";

import { useTheme } from "../lib/theme";

// ---------------------------------------------------------------------------
// Light / dark theme toggle — single icon button rendered in the Header.
//
// The button is intentionally tiny and lives in the top-right cluster next to
// the active role pill. We don't render the icon until the provider has
// resolved which theme is painted (theme === null during the first SSR pass)
// to avoid hydration flicker — the button takes its final shape on mount.
// ---------------------------------------------------------------------------

export default function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === "dark";

  return (
    <button
      type="button"
      onClick={toggleTheme}
      aria-label={
        theme == null
          ? "Toggle theme"
          : isDark
            ? "Switch to light theme"
            : "Switch to dark theme"
      }
      title={
        theme == null
          ? "Toggle theme"
          : isDark
            ? "Switch to light theme"
            : "Switch to dark theme"
      }
      className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-neutral-700 bg-neutral-900 text-neutral-300 transition-colors hover:border-neutral-500 hover:text-neutral-100"
    >
      <span aria-hidden="true" className="text-base leading-none">
        {theme == null ? "◐" : isDark ? "☀" : "☾"}
      </span>
    </button>
  );
}
