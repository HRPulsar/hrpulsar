/**
 * Enterprise locale registrations.
 *
 * Community edition stub — no extra locales beyond the core set.
 * Monorepo locale-ee.ts contains the full enterprise version;
 * sync script swaps this file in for the public repo.
 */

export const EE_CATALOG_LOCALES: readonly string[] = [];

/** Native-name labels, merged into LOCALE_LABELS in src/lib/locale.ts. */
export const EE_LOCALE_LABELS: Record<string, string> = {};

/** Lazy catalog loaders, merged into the CATALOGS map in
 * src/i18n/request.ts (same shape). */
export const EE_CATALOGS: Record<string, () => Promise<{ default: unknown }>> =
  {};

/** AI content languages enterprise deployments offer on top of the core
 * set, merged into CONTENT_LANGUAGES in src/lib/api/ai-settings.ts. */
export const EE_CONTENT_LANGUAGES: readonly string[] = [];
