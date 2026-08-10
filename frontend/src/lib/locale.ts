/**
 * Deployment-level interface locales (i18n F0), mirroring lib/brand.ts.
 *
 *   NEXT_PUBLIC_AVAILABLE_LOCALES — comma-separated UI locales offered by
 *                                   this deployment (e.g. "de,en"); drives
 *                                   which options language selects show
 *   NEXT_PUBLIC_DEFAULT_LOCALE    — fallback locale for users/tenants
 *                                   without an explicit choice
 *
 * Backend counterparts: AVAILABLE_LOCALES / DEFAULT_LOCALE (config.py) —
 * a deployment must set both sides consistently. The backend refuses to
 * start when DEFAULT_LOCALE is not listed in AVAILABLE_LOCALES, so this
 * module only guards against the envs being absent (stock en-only build).
 */

import { EE_CATALOG_LOCALES, EE_LOCALE_LABELS } from "./locale-ee";

export const FALLBACK_LOCALE = "en";

/** Locales with a shipped messages catalog (frontend/messages/<code>.json).
 * The runtime env can only narrow this set, never extend it — offering a
 * locale without a catalog would crash SSR message loading (see
 * src/i18n/request.ts). Adding a language: create the catalog file, list
 * the code here (+ LOCALE_LABELS) and register it in the CATALOGS map of
 * src/i18n/request.ts. Enterprise-only locales register through
 * locale-ee.ts instead (community stub is empty, so they are dropped by
 * the getAvailableLocales() filter in community builds). */
export const CATALOG_LOCALES: readonly string[] = [
  "en",
  "de",
  ...EE_CATALOG_LOCALES,
];

/** Native-name labels for language selects and the switcher.
 * Unknown codes fall through to the raw code via localeLabel(). */
export const LOCALE_LABELS: Record<string, string> = {
  en: "English",
  de: "Deutsch",
  ...EE_LOCALE_LABELS,
};

type LocaleEnvKey =
  | "NEXT_PUBLIC_AVAILABLE_LOCALES"
  | "NEXT_PUBLIC_DEFAULT_LOCALE";

/** Build-time inlined values, for client contexts without runtime
 * injection (local dev, build-args). Static member access per key is
 * required for the bundler to substitute them. */
function buildTimeEnv(key: LocaleEnvKey): string | undefined {
  switch (key) {
    case "NEXT_PUBLIC_AVAILABLE_LOCALES":
      return process.env.NEXT_PUBLIC_AVAILABLE_LOCALES;
    case "NEXT_PUBLIC_DEFAULT_LOCALE":
      return process.env.NEXT_PUBLIC_DEFAULT_LOCALE;
  }
}

function readEnv(key: LocaleEnvKey): string | undefined {
  if (typeof window === "undefined") {
    // Server: dynamic access on purpose — a static process.env.NEXT_PUBLIC_*
    // member read is inlined at build time and would freeze prebuilt (GHCR)
    // images to the CI env (see runtime-env-script.tsx).
    return process.env[key] || undefined;
  }
  return window.__ENV__?.[key] || buildTimeEnv(key) || undefined;
}

export function getAvailableLocales(): string[] {
  const raw = readEnv("NEXT_PUBLIC_AVAILABLE_LOCALES") ?? "";
  const locales = raw
    .split(",")
    .map((locale) => locale.trim().toLowerCase())
    // Locales without a shipped catalog are dropped, not offered — an
    // env typo must degrade to English, not brick SSR message loading.
    .filter((locale) => locale && CATALOG_LOCALES.includes(locale));
  return locales.length > 0 ? locales : [FALLBACK_LOCALE];
}

export function getDefaultLocale(): string {
  const available = getAvailableLocales();
  const raw = readEnv("NEXT_PUBLIC_DEFAULT_LOCALE")?.trim().toLowerCase();
  if (raw && available.includes(raw)) return raw;
  return available[0] ?? FALLBACK_LOCALE;
}

export function localeLabel(code: string): string {
  return LOCALE_LABELS[code] ?? code;
}
