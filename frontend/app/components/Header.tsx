import Link from "next/link";
import { serverFetch } from "../lib/api/server";
import type { Me } from "../lib/types";
import FeedbackButton from "./FeedbackButton";
import ThemeToggle from "./ThemeToggle";

// Authorization is a single per-email flag: `me.is_admin`. The `/admin`
// link only renders for admins; everyone else hits a page-level guard on
// that route. Every other link is unrestricted — any authenticated user can
// browse `/developer`, `/platform`, `/executive`, and `/settings/mcp`.

export default async function Header() {
  const me = await serverFetch<Me>("/me");
  const isAdmin = me.is_admin;

  return (
    <header className="sticky top-0 z-10 border-b border-white/5 bg-neutral-950/95 backdrop-blur">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-3">
        <div className="flex items-center gap-6">
          <Link
            href="/"
            className="text-sm font-semibold tracking-wide text-neutral-100"
          >
            Unified Security Dashboard
          </Link>
          <nav className="flex items-center gap-4 text-sm text-neutral-400">
            <Link href="/executive" className="hover:text-neutral-100">
              Executive
            </Link>
            <Link href="/developer" className="hover:text-neutral-100">
              Developer
            </Link>
            <Link href="/platform" className="hover:text-neutral-100">
              Platform
            </Link>
            {isAdmin ? (
              <Link href="/admin" className="hover:text-neutral-100">
                Admin
              </Link>
            ) : null}
            <Link href="/settings/mcp" className="hover:text-neutral-100">
              MCP
            </Link>
          </nav>
        </div>
        <div className="flex items-center gap-3 text-sm">
          {isAdmin ? (
            <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-[0.06em] text-emerald-700 dark:text-emerald-300">
              admin
            </span>
          ) : null}
          <span className="text-neutral-400">{me.email}</span>
          <FeedbackButton email={me.email} name={me.name} />
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}
