import type { ReactNode } from "react";
import { notFound } from "next/navigation";
import { connection } from "next/server";
import { getTranslations } from "next-intl/server";

import { LanguageSwitcher } from "@/components/language-switcher";
import { getBrandName } from "@/lib/brand";
import { publicCheckHost } from "@/lib/public-check-host";

/**
 * Shell of the public process check (HRP-924/925): anonymous visitors, no
 * product header or navigation. The service exists only where the site
 * turns it on (PUBLIC_CHECK_ENABLED + PUBLIC_CHECK_HOST, read per request -
 * see lib/public-check-host.ts); everywhere else every page here is a 404.
 */
export default async function PublicCheckLayout({
  children,
}: {
  children: ReactNode;
}) {
  await connection();
  if (!publicCheckHost()) notFound();
  const t = await getTranslations("publicCheck");
  return (
    <div className="min-h-screen bg-background">
      <header className="border-b">
        <div className="mx-auto flex max-w-3xl items-center justify-between gap-3 px-4 py-3">
          <div className="flex min-w-0 items-baseline gap-2">
            <span className="text-sm font-semibold tracking-tight">
              {getBrandName()}
            </span>
            <span className="truncate text-sm text-muted-foreground">
              {t("serviceName")}
            </span>
          </div>
          <LanguageSwitcher testIdPrefix="check" persistToAccount={false} />
        </div>
      </header>
      <main className="mx-auto max-w-3xl px-4 py-6 sm:py-10">{children}</main>
    </div>
  );
}
