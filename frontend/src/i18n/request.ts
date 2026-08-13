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
import { mergeCatalogs, type Messages } from "./merge";

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

// The merged catalog is identical for every request in a locale — the
// inputs are static imports — so it is built once instead of deep-copying
// ~4300 keys on each SSR pass of a non-en locale. Bounded by the number
// of shipped catalogs; nothing invalidates it because nothing can change
// it without a new process.
const mergedCatalogs = new Map<string, Messages>();

async function catalogFor(locale: string): Promise<Messages> {
  const cached = mergedCatalogs.get(locale);
  if (cached) return cached;
  const fallback = (await CATALOGS[FALLBACK_LOCALE]()).default as Messages;
  // HRP-511 (g): lay the locale over English so a key missing from it
  // renders the English string instead of the raw dotted key — the
  // promise in ADDING_A_LANGUAGE.md. Merging here (rather than via
  // getMessageFallback) costs no client bundle and covers the client
  // tree too, since these are the messages the provider serializes.
  const messages =
    locale === FALLBACK_LOCALE
      ? fallback
      : mergeCatalogs(fallback, (await CATALOGS[locale]()).default as Messages);
  mergedCatalogs.set(locale, messages);
  return messages;
}

export default getRequestConfig(async () => {
  const cookieStore = await cookies();
  const requestHeaders = await headers();
  const requested = resolveRequestLocale(
    cookieStore.get(NEXT_LOCALE_COOKIE)?.value,
    requestHeaders.get("accept-language"),
  );
  const locale = CATALOGS[requested] ? requested : FALLBACK_LOCALE;
  return { locale, messages: await catalogFor(locale) };
});
