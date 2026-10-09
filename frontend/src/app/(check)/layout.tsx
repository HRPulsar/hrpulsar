import type { ReactNode } from "react";
import { notFound } from "next/navigation";
import { connection } from "next/server";
import { getTranslations } from "next-intl/server";

import { LanguageSwitcher } from "@/components/language-switcher";
import { getBrandName, getLogoUrl } from "@/lib/brand";
import { getLandingHref } from "@/lib/landing-url";
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
        <div className="mx-auto flex h-[60px] max-w-3xl items-center justify-between gap-3 px-4">
          <div className="flex min-w-0 items-center gap-3">
            {/* The marketing site's wordmark, linking home: a visitor from the
                landing sees the same header, not a second brand. */}
            <a
              href={getLandingHref()}
              aria-label={getBrandName()}
              data-testid="check-link-landing"
              className="shrink-0"
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={getLogoUrl("light")} alt={getBrandName()} className="block h-7 dark:hidden" />
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={getLogoUrl("dark")} alt="" className="hidden h-7 dark:block" />
            </a>
            <span aria-hidden="true" className="h-5 w-px bg-border" />
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
