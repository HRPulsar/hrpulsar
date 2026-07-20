import type { ReactNode } from "react";

import { getBrandName } from "@/lib/brand";

export default function InvitedEvaluatorLayout({
  children,
}: {
  children: ReactNode;
}) {
  // HRP-359: this shell is the contact surface for external evaluators —
  // no navigation into the tenant app, not even a logo link home.
  return (
    <div className="min-h-screen bg-background">
      <header className="border-b">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
          <span className="text-sm font-semibold tracking-tight">
            {getBrandName()}
          </span>
          <span className="text-xs text-muted-foreground">
            Evaluation form
          </span>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
    </div>
  );
}
