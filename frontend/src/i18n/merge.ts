/**
 * English fallback for individual missing keys (HRP-511 g).
 *
 * ADDING_A_LANGUAGE.md promises that "a missing translation renders
 * English, never a raw key or a 500". next-intl only delivers that per
 * *catalog*, not per *key*: an incomplete catalog rendered the dotted key
 * itself (or threw in dev), because `getMessageFallback` cannot reach the
 * English catalog on the client without shipping it twice.
 *
 * Merging on the server instead keeps the promise for both the server and
 * the client tree, adds nothing to the bundle, and needs no serialized
 * function: the locale's catalog is laid over English, so every key that
 * exists in English resolves to *something* readable.
 *
 * The parity guards (i18n-catalog-parity.test.ts) still require the key
 * sets to match — this is the runtime safety net for a locale that ships
 * out of step, not a licence to leave keys untranslated.
 */

export type Messages = { [key: string]: string | Messages };

function isBranch(value: unknown): value is Messages {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Deep-merge `override` onto `base`. Leaves in `override` win; keys that
 * only exist in `base` survive. Neither input is mutated.
 *
 * A branch/leaf conflict resolves in favour of `override` — a catalog
 * that changed a key's shape is a parity-guard failure, and guessing
 * would only hide it.
 */
export function mergeCatalogs(base: Messages, override: Messages): Messages {
  const merged: Messages = { ...base };
  for (const [key, value] of Object.entries(override)) {
    const existing = merged[key];
    merged[key] =
      isBranch(existing) && isBranch(value)
        ? mergeCatalogs(existing, value)
        : value;
  }
  return merged;
}
