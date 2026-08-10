/**
 * next-intl per-request config (i18n F1) — cookie-based, no URL prefix.
 *
 * Loaded by createNextIntlPlugin (next.config.ts). Runs on every SSR
 * pass; reading cookies()/headers() keeps the tree request-dynamic
 * (which the layout already is via RuntimeEnvScript's headers() call).
 *
 * SSR cannot see User.language / Tenant.default_locale (Bearer auth,
 * no session cookie) — the client-side locale-sync effect reconciles
 * those into the NEXT_LOCALE cookie; see src/i18n/config.ts.
 */

import { getRequestConfig } from "next-intl/server";
import { cookies, headers } from "next/headers";

import { FALLBACK_LOCALE } from "@/lib/locale";
import { EE_CATALOGS } from "@/lib/locale-ee";
import { NEXT_LOCALE_COOKIE, resolveRequestLocale } from "./config";

// Static catalog map: an unknown locale is a plain map miss (falls back
// to English) instead of a module-resolution crash that would 500 every
// request. Keep in sync with CATALOG_LOCALES in src/lib/locale.ts.
// Enterprise-only catalogs merge in from locale-ee.ts (empty stub in
// community builds, where their catalog files do not exist).
const CATALOGS: Record<string, () => Promise<{ default: unknown }>> = {
  en: () => import("../../messages/en.json"),
  de: () => import("../../messages/de.json"),
  ...EE_CATALOGS,
};

export default getRequestConfig(async () => {
  const cookieStore = await cookies();
  const requestHeaders = await headers();
  const locale = resolveRequestLocale(
    cookieStore.get(NEXT_LOCALE_COOKIE)?.value,
    requestHeaders.get("accept-language"),
  );
  const loadCatalog = CATALOGS[locale] ?? CATALOGS[FALLBACK_LOCALE];
  return {
    locale: CATALOGS[locale] ? locale : FALLBACK_LOCALE,
    messages: (await loadCatalog()).default as Record<string, unknown>,
  };
});
