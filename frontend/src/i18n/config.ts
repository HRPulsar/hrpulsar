/**
 * Interface-locale resolution for the frontend (i18n F1).
 *
 * Cookie-based next-intl setup without URL prefixes (see
 * docs/plans/I18N_PLAN.md): the effective locale of a request is
 *
 *   ?lang= > NEXT_LOCALE cookie > Accept-Language > deployment default
 *
 * (`?lang=` is the locale an invitation email put in its link. The proxy
 * consumes it once — writes the cookie, then redirects to the same URL
 * without it — so it cannot outrank a switch the user makes afterwards.
 * Full table, both sides of the wire: docs/guides/ADDING_A_LANGUAGE.md,
 * "Locale sources and their priority".)
 *
 * Auth is a Bearer token (no session cookie), so SSR cannot see
 * User.language / Tenant.default_locale — those levels of the chain are
 * reconciled client-side into the cookie: the LanguageSwitcher writes it
 * directly, while the profile Language select PUTs the account field and
 * lets the locale-sync effect in AuthProvider write the cookie on the
 * refreshed user. When an account-level preference exists it overrides
 * the cookie, so the choice follows the account across devices.
 *
 * Mirrors backend/app/core/i18n.py (parse_accept_language /
 * resolve_locale) — keep the two in sync.
 */

import { getAvailableLocales, getDefaultLocale } from "@/lib/locale";

export const NEXT_LOCALE_COOKIE = "NEXT_LOCALE";

/** One year, in seconds — the cookie stores a deliberate user choice. */
export const LOCALE_COOKIE_MAX_AGE = 60 * 60 * 24 * 365;

const QVALUE_RE = /^q=(0(\.\d{0,3})?|1(\.0{0,3})?)$/;

/** Map a locale tag onto a supported locale, or undefined. Accepts full
 * BCP 47 tags ("de-DE", "de_AT") and matches on the primary subtag. */
export function normalizeLocale(
  value: string | null | undefined,
): string | undefined {
  if (!value) return undefined;
  const primary = value.trim().toLowerCase().split(/[-_]/)[0];
  return getAvailableLocales().includes(primary) ? primary : undefined;
}

/** Accept-Language → language tags ordered by descending q-value.
 * Wildcards are dropped; a malformed q-value drops its tag; parameter
 * names are case-insensitive; ties keep header order. */
export function parseAcceptLanguage(header: string | null | undefined): string[] {
  if (!header) return [];
  const weighted: Array<{ quality: number; tag: string }> = [];
  for (const part of header.split(",")) {
    const segments = part.trim().split(";").map((s) => s.trim());
    const tag = segments[0];
    if (!tag || tag === "*") continue;
    let quality = 1;
    for (const param of segments.slice(1)) {
      const lowered = param.toLowerCase();
      if (lowered.startsWith("q=")) {
        quality = QVALUE_RE.test(lowered) ? parseFloat(lowered.slice(2)) : 0;
        break;
      }
    }
    if (quality > 0) weighted.push({ quality, tag });
  }
  weighted.sort((a, b) => b.quality - a.quality);
  return weighted.map((w) => w.tag);
}

/** Resolve the request locale from the NEXT_LOCALE cookie and the
 * Accept-Language header, falling back to the deployment default. */
export function resolveRequestLocale(
  cookieValue: string | null | undefined,
  acceptLanguage: string | null | undefined,
): string {
  const fromCookie = normalizeLocale(cookieValue);
  if (fromCookie) return fromCookie;
  for (const tag of parseAcceptLanguage(acceptLanguage)) {
    const normalized = normalizeLocale(tag);
    if (normalized) return normalized;
  }
  return getDefaultLocale();
}

/** Client-side cookie writers (no-ops outside the browser). */
export function setLocaleCookie(locale: string): void {
  if (typeof document === "undefined") return;
  document.cookie = `${NEXT_LOCALE_COOKIE}=${locale}; path=/; max-age=${LOCALE_COOKIE_MAX_AGE}; SameSite=Lax`;
}

export function clearLocaleCookie(): void {
  if (typeof document === "undefined") return;
  document.cookie = `${NEXT_LOCALE_COOKIE}=; path=/; max-age=0; SameSite=Lax`;
}

/** Header name the backend reads for the caller's effective locale. */
export const LOCALE_HEADER = "X-Locale";

/**
 * Locale header for API calls (HRP-513), or `{}` when there is nothing
 * to state.
 *
 * The NEXT_LOCALE cookie never reaches the backend when
 * NEXT_PUBLIC_API_URL points at another origin (fetch defaults to
 * `same-origin` credentials), so a de user got English error bodies on
 * self-hosted and dev setups. Stating the locale explicitly is
 * origin-independent, and unlike Accept-Language it describes the
 * account's choice rather than the browser's.
 *
 * Mirrors resolve_locale_from_request in backend/app/core/i18n.py.
 */
export function localeRequestHeaders(): Record<string, string> {
  const locale = normalizeLocale(readLocaleCookie());
  return locale ? { [LOCALE_HEADER]: locale } : {};
}

export function readLocaleCookie(): string | undefined {
  if (typeof document === "undefined") return undefined;
  const match = document.cookie
    .split("; ")
    .find((row) => row.startsWith(`${NEXT_LOCALE_COOKIE}=`));
  return match ? match.slice(NEXT_LOCALE_COOKIE.length + 1) : undefined;
}
