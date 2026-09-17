import type { ReactNode } from "react";
import DraftBanner from "../components/DraftBanner";

export default function ExecutiveLayout({ children }: { children: ReactNode }) {
  return (
    <div className="space-y-3">
      <DraftBanner />
      {children}
    </div>
  );
}
