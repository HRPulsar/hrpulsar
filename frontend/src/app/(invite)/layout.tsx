import type { ReactNode } from "react";
import { getTranslations } from "next-intl/server";

import { LanguageSwitcher } from "@/components/language-switcher";
import { getBrandName } from "@/lib/brand";

export default async function InvitedEvaluatorLayout({
  children,
}: {
  children: ReactNode;
}) {
  const t = await getTranslations("auth");
  // HRP-359: this shell is the contact surface for external evaluators —
  // no navigation into the tenant app, not even a logo link home.
  return (
    <div className="min-h-screen bg-background">
      <header className="border-b">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
          <span className="text-sm font-semibold tracking-tight">
            {getBrandName()}
          </span>
          <div className="flex items-center gap-3">
            <span className="text-xs text-muted-foreground">
              {t("evaluationForm")}
            </span>
            {/* HRP-516: external evaluators never sign in, so this is the
                only place they can correct a locale that Accept-Language
                got wrong (German employer, English browser). */}
            <LanguageSwitcher testIdPrefix="invite" persistToAccount={false} />
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
    </div>
  );
}
