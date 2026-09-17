"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { ThemeProvider } from "./lib/theme";

// React Query: 5-minute stale time across the app (D26).
//
// ThemeProvider wraps QueryClientProvider so that components inside any data-
// fetching boundary can still read / toggle the theme via `useTheme()`.

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 5 * 60 * 1000,
            refetchOnWindowFocus: false,
          },
        },
      }),
  );
  return (
    <ThemeProvider>
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    </ThemeProvider>
  );
}
