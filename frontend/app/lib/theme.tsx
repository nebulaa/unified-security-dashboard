"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

// ---------------------------------------------------------------------------
// Theme provider — light / dark with localStorage persistence.
//
// Rendering model
// ---------------
//   1. An inline `<script>` injected in `<head>` (see `layout.tsx`) reads
//      `localStorage.secdb.theme` ("light" | "dark") OR defaults to "dark",
//      then sets the matching class on `<html>` BEFORE React hydrates. This
//      avoids a light→dark FOUC flash on first paint.
//   2. On the client, this provider re-reads the same source on mount, so
//      `useTheme()` always returns the value that's actually painted.
//   3. `toggleTheme()` persists the new value to `localStorage` (so subsequent
//      visits remember the explicit choice) and updates the DOM class.
//
// The provider intentionally returns `null` for theme on the very first server
// render to avoid hydration mismatches; consumers should treat that as the
// "default" state and rely on the inline script for the painted appearance.
// ---------------------------------------------------------------------------

export type Theme = "light" | "dark";

interface ThemeContextValue {
  /** Resolved theme — `null` only during the brief SSR / pre-hydration window. */
  theme: Theme | null;
  /** Flip the current theme and persist the choice to localStorage. */
  toggleTheme: () => void;
  /** Set a specific theme (used by tests and programmatic switches). */
  setTheme: (next: Theme) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

const STORAGE_KEY = "secdb.theme";

/** Read the theme from `<html>`'s class list. Mirrors the inline pre-hydration
 *  script so the provider sees the same value that was painted. */
function readCurrentTheme(): Theme {
  if (typeof document === "undefined") return "dark";
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

function applyTheme(next: Theme): void {
  const root = document.documentElement;
  root.classList.toggle("dark", next === "dark");
  root.style.colorScheme = next;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  // `null` during the first server render — see file header. After the first
  // useEffect tick this swaps to the painted theme.
  const [theme, setThemeState] = useState<Theme | null>(null);

  useEffect(() => {
    // Hydration must read the class applied by the pre-paint initialization script.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setThemeState(readCurrentTheme());
  }, []);

  const setTheme = useCallback((next: Theme) => {
    applyTheme(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // localStorage can be unavailable in private-mode Safari and a few
      // corp-locked browsers; persistence is best-effort and the class on
      // <html> is the source of truth for the in-tab session anyway.
    }
    setThemeState(next);
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme(readCurrentTheme() === "dark" ? "light" : "dark");
  }, [setTheme]);

  const value = useMemo<ThemeContextValue>(
    () => ({ theme, toggleTheme, setTheme }),
    [theme, toggleTheme, setTheme],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) {
    throw new Error("useTheme must be used inside a ThemeProvider");
  }
  return ctx;
}
