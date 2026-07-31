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
import { getAvailableLocales, localeLabel } from "@/lib/locale";

/**
 * Header locale switcher (i18n F1). Hidden on single-locale deployments.
 *
 * Selecting a locale writes the NEXT_LOCALE cookie (instant switch on
 * this device via router.refresh()) and best-effort persists it as
 * User.language so the choice follows the user across devices and
 * drives email language. If the profile write fails, the locale-sync
 * effect in AuthProvider reconciles the cookie back on the next load.
 */
export function LanguageSwitcher() {
  const locale = useLocale();
  const router = useRouter();
  const t = useTranslations("common");
  const locales = getAvailableLocales();

  if (locales.length < 2) return null;

  function selectLocale(next: string) {
    if (next === locale) return;
    setLocaleCookie(next);
    api.put("/auth/me", { language: next }).catch(() => {
      // Cookie already switched this device; account sync is best-effort.
    });
    router.refresh();
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className="flex h-8 w-8 items-center justify-center rounded-md hover:bg-muted transition-colors outline-none"
        title={t("changeLanguage")}
        aria-label={t("changeLanguage")}
        data-testid="header-btn-language"
      >
        <Globe className="h-4 w-4" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {locales.map((code) => (
          <DropdownMenuItem
            key={code}
            data-testid={`header-menu-language-${code}`}
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
