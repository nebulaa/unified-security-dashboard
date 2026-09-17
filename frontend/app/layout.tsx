import type { Metadata } from "next";
import type { ReactNode } from "react";
import Header from "./components/Header";
import "./globals.css";
import { themeInitScript } from "./lib/theme-init";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "Unified Security Dashboard",
  description: "Internal security posture for executives, developers, and platform engineers.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  // `dark` on <html> is the product default. The inline script below may swap
  // to light before first paint when the user has explicitly chosen light in
  // localStorage. `suppressHydrationWarning` silences the mismatch warning
  // when that script adjusts the class.
  return (
    <html lang="en" className="dark" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body>
        <Providers>
          <Header />
          {/* py-5 (was py-8) — pulls the developer Overview/Services pages
              up so the trend chart / per-service table sits closer to the
              fold on a standard MacBook viewport. The 24px lost here is the
              largest single compression win across the entire page chrome. */}
          <main className="mx-auto max-w-7xl px-6 py-5">{children}</main>
        </Providers>
      </body>
    </html>
  );
}
