// Enterprise-only locale registrations (locale-ee.ts) must stay internally
// consistent: every registered locale needs a catalog loader, a native-name
// label, and an actual catalog file on disk — a half-registered locale
// would be offered in the switcher and then fall back to English.
//
// In the public repo this file runs against the community stub (empty
// registrations) and passes vacuously; the monorepo/enterprise tree pins
// the full version. Synced to both on purpose.
import { existsSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import {
  EE_CATALOGS,
  EE_CATALOG_LOCALES,
  EE_CONTENT_LANGUAGES,
  EE_LOCALE_LABELS,
} from "@/lib/locale-ee";
import { CATALOG_LOCALES, LOCALE_LABELS, localeLabel } from "@/lib/locale";

describe("enterprise locale registrations", () => {
  it("gives every EE locale a loader, a label and a catalog file", () => {
    for (const locale of EE_CATALOG_LOCALES) {
      expect(EE_CATALOGS[locale], `${locale}: loader`).toBeTypeOf("function");
      expect(EE_LOCALE_LABELS[locale], `${locale}: label`).toBeTruthy();
      expect(
        existsSync(resolve(__dirname, `../../messages/${locale}.json`)),
        `${locale}: messages catalog`,
      ).toBe(true);
    }
  });

  it("merges EE locales into the core registrations", () => {
    for (const locale of EE_CATALOG_LOCALES) {
      expect(CATALOG_LOCALES).toContain(locale);
      expect(localeLabel(locale)).toBe(EE_LOCALE_LABELS[locale]);
    }
    for (const locale of EE_CONTENT_LANGUAGES) {
      // Content-language selects render labels via localeLabel(); an EE
      // content language without a label would show its raw code.
      expect(LOCALE_LABELS[locale], `${locale}: label`).toBeTruthy();
    }
  });
});
