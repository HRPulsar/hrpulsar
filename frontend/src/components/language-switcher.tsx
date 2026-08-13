"use client";

import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { Globe } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { setLocaleCookie } from "@/i18n/config";
import { api } from "@/lib/api";
import { isAuthenticated } from "@/lib/auth";
import { getAvailableLocales, localeLabel } from "@/lib/locale";
import { cn } from "@/lib/utils";

/**
 * Write a locale choice: the cookie always (instant switch on this
 * device), the account only where that is the right thing to do — so the
 * choice follows the user across devices and drives email language.
 *
 * ``persistToAccount`` is false on every signed-out surface. Two reasons,
 * and the second is the sharp one:
 *   - there is usually no session at all, so PUT /auth/me would just 401;
 *   - there may be *someone else's* session. A user signed into tenant A
 *     who opens tenant B's invitation or evaluator link is still carrying
 *     A's token, so switching the language of that public page would
 *     silently rewrite account A's interface language and the language of
 *     its emails (review finding 8).
 *
 * If the profile write fails, the locale-sync effect in AuthProvider
 * reconciles the cookie back on the next load.
 */
export function persistLocaleChoice(
  next: string,
  { persistToAccount = true }: { persistToAccount?: boolean } = {},
): void {
  setLocaleCookie(next);
  if (!persistToAccount || !isAuthenticated()) return;
  api.put("/auth/me", { language: next }).catch(() => {
    // Cookie already switched this device; account sync is best-effort.
  });
}

/**
 * Locale switcher (i18n F1). Hidden on single-locale deployments.
 *
 * HRP-516: mounted in the app header, and on the signed-out surfaces —
 * the (auth) pages and the (invite) shell for external evaluators, where
 * the locale would otherwise be decided by Accept-Language alone with
 * nothing to change it (a German company's evaluator on an
 * English-locale browser got a German invitation email and an English
 * form). The testid namespace follows the surface it is mounted on.
 */
export function LanguageSwitcher({
  testIdPrefix = "header",
  triggerClassName,
  persistToAccount = true,
}: {
  /** data-testid namespace, per the docs/guides/TEST_IDS.md convention. */
  testIdPrefix?: string;
  triggerClassName?: string;
  /** Also store the choice on the signed-in account. False on public
   * surfaces — see persistLocaleChoice. */
  persistToAccount?: boolean;
} = {}) {
  const locale = useLocale();
  const router = useRouter();
  const t = useTranslations("common");
  const locales = getAvailableLocales();

  if (locales.length < 2) return null;

  function selectLocale(next: string) {
    if (next === locale) return;
    persistLocaleChoice(next, { persistToAccount });
    router.refresh();
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className={cn(
          "flex h-8 w-8 items-center justify-center rounded-md hover:bg-muted transition-colors outline-none",
          triggerClassName,
        )}
        title={t("changeLanguage")}
        aria-label={t("changeLanguage")}
        data-testid={`${testIdPrefix}-btn-language`}
      >
        <Globe className="h-4 w-4" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {locales.map((code) => (
          <DropdownMenuItem
            key={code}
            data-testid={`${testIdPrefix}-menu-language-${code}`}
            onClick={() => selectLocale(code)}
            className={code === locale ? "font-medium" : undefined}
          >
            {localeLabel(code)}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
