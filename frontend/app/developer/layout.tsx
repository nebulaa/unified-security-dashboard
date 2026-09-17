import type { ReactNode } from "react";
import DraftBanner from "../components/DraftBanner";

export default function DeveloperLayout({ children }: { children: ReactNode }) {
  return (
    <div className="space-y-4">
      <DraftBanner />
      {children}
    </div>
  );
}
