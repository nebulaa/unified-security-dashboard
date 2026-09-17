import type { ReactNode } from "react";
import DraftBanner from "../components/DraftBanner";
import PlatformSectionNav from "./PlatformSectionNav";

export default function PlatformLayout({ children }: { children: ReactNode }) {
  return (
    <div className="space-y-4">
      <DraftBanner />
      <PlatformSectionNav />
      {children}
    </div>
  );
}
