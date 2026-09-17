"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const SECTIONS = [
  { href: "/platform", label: "Platform security", match: "product" as const },
  {
    href: "/platform/threat-intel",
    label: "Threat intel",
    match: "threat-intel" as const,
  },
] as const;

/** Top-level /platform sections — product-line pillars vs org-wide threat intel. */
export default function PlatformSectionNav() {
  const pathname = usePathname();
  const active = pathname?.startsWith("/platform/threat-intel")
    ? "threat-intel"
    : "product";

  return (
    <nav
      className="flex gap-1 rounded-lg border border-neutral-800 bg-neutral-900/50 p-1 w-fit"
      aria-label="Platform sections"
    >
      {SECTIONS.map((section) => {
        const isActive = section.match === active;
        return (
          <Link
            key={section.href}
            href={section.href}
            className={`rounded-md px-4 py-1.5 text-sm font-medium transition-colors ${
              isActive
                ? "bg-neutral-700 text-neutral-100"
                : "text-neutral-400 hover:text-neutral-200 hover:bg-neutral-800/80"
            }`}
            aria-current={isActive ? "page" : undefined}
          >
            {section.label}
          </Link>
        );
      })}
    </nav>
  );
}
