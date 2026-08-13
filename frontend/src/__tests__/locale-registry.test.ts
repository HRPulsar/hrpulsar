/**
 * HRP-511 (b, g): the locale registries must agree with each other and
 * with what is actually on disk.
 *
 * Adding a language touches three places that nothing connected before:
 *   frontend/messages/<code>.json   — the catalog file
 *   CATALOG_LOCALES + LOCALE_LABELS — src/lib/locale.ts
 *   CATALOGS                        — src/i18n/request.ts
 * Miss the third and SSR falls back to English with no error anywhere;
 * miss the second and the locale is silently filtered out of the switcher.
 * Enterprise-only catalogs (ru) join through locale-ee.ts, so everything
 * here is discovered rather than hard-coded — the public repo ships fewer
 * catalogs than the monorepo.
 *
 * Also covers the English merge that backs the "a missing key renders
 * English" promise in ADDING_A_LANGUAGE.md.
 */
import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { CATALOG_LOCALES, LOCALE_LABELS } from "@/lib/locale";
import { EE_CATALOGS } from "@/lib/locale-ee";
import { mergeCatalogs, type Messages } from "@/i18n/merge";

const MESSAGES_DIR = resolve(__dirname, "../../messages");
const REQUEST_CONFIG = resolve(__dirname, "../i18n/request.ts");

/** Locales that ship a catalog file. */
const fileLocales = readdirSync(MESSAGES_DIR)
  .filter((name) => name.endsWith(".json"))
  .map((name) => name.replace(/\.json$/, ""))
  .sort();

/**
 * Locales wired into the CATALOGS map of src/i18n/request.ts.
 *
 * Read from source: the map holds dynamic `import()` thunks, and
 * importing the module would pull in next-intl's server runtime.
 */
export function catalogsMapLocales(source: string): string[] {
  const body = source.slice(
    source.indexOf("const CATALOGS"),
    source.indexOf("export default"),
  );
  const keys = [...body.matchAll(/^\s{2}(\w+):\s*\(\)\s*=>/gm)].map((m) => m[1]);
  // The enterprise catalogs are only registered if the map actually
  // spreads them. Appending them unconditionally made this test blind to
  // "...EE_CATALOGS" being dropped — which is precisely the failure it
  // exists to catch (review finding 6): ru would still be listed in
  // CATALOG_LOCALES and offered by the switcher while SSR silently fell
  // back to English.
  const spreadsEnterprise = /\.\.\.EE_CATALOGS\b/.test(body);
  return [
    ...keys,
    ...(spreadsEnterprise ? Object.keys(EE_CATALOGS) : []),
  ].sort();
}

/** Symmetric difference, as (label, missing) pairs — the shape the
 * assertions below report on. */
export function registryGaps(
  expected: readonly string[],
  actual: readonly string[],
): { missing: string[]; extra: string[] } {
  return {
    missing: expected.filter((code) => !actual.includes(code)),
    extra: actual.filter((code) => !expected.includes(code)),
  };
}

describe("locale registries", () => {
  const requestSource = readFileSync(REQUEST_CONFIG, "utf8");

  it("discovers at least the base catalog", () => {
    expect(fileLocales).toContain("en");
  });

  it("keeps CATALOG_LOCALES in step with the catalog files", () => {
    expect(registryGaps(fileLocales, [...CATALOG_LOCALES])).toEqual({
      missing: [],
      extra: [],
    });
  });

  it("keeps the CATALOGS map in step with the catalog files", () => {
    expect(registryGaps(fileLocales, catalogsMapLocales(requestSource))).toEqual(
      { missing: [], extra: [] },
    );
  });

  it("labels every catalog locale", () => {
    for (const code of fileLocales) {
      expect(LOCALE_LABELS[code], `LOCALE_LABELS is missing ${code}`).toBeTruthy();
      // A label falling back to the raw code means the entry was forgotten.
      expect(LOCALE_LABELS[code]).not.toBe(code);
    }
  });

  // The guard must fail on a real regression, not just pass by luck.
  describe("catches a broken registry", () => {
    it("reports a locale that has a file but no CATALOGS entry", () => {
      expect(registryGaps(["en", "de", "fr"], ["en", "de"])).toEqual({
        missing: ["fr"],
        extra: [],
      });
    });

    it("reports a locale registered without a catalog file", () => {
      expect(registryGaps(["en", "de"], ["en", "de", "fr"])).toEqual({
        missing: [],
        extra: ["fr"],
      });
    });

    it("reports enterprise catalogs when the spread is dropped", () => {
      const withSpread = [
        "const CATALOGS = {",
        '  en: () => import("../../messages/en.json"),',
        "  ...EE_CATALOGS,",
        "};",
        "export default getRequestConfig",
      ].join("\n");
      const withoutSpread = withSpread.replace("  ...EE_CATALOGS,\n", "");
      expect(catalogsMapLocales(withSpread)).toEqual(
        ["en", ...Object.keys(EE_CATALOGS)].sort(),
      );
      expect(catalogsMapLocales(withoutSpread)).toEqual(["en"]);
      // With enterprise catalogs shipped, dropping the spread is a real
      // gap the file-vs-map comparison must now surface.
      if (Object.keys(EE_CATALOGS).length > 0) {
        expect(registryGaps(fileLocales, catalogsMapLocales(withoutSpread)))
          .not.toEqual({ missing: [], extra: [] });
      }
    });

    it("does not read CATALOGS entries out of an unrelated map", () => {
      const source = [
        "const OTHER = {",
        "  fr: () => import('../../messages/fr.json'),",
        "};",
        "const CATALOGS = {",
        "  en: () => import('../../messages/en.json'),",
        "};",
        "export default getRequestConfig",
      ].join("\n");
      expect(catalogsMapLocales(source)).toEqual(["en"]);
    });
  });
});

describe("English fallback merge (HRP-511 g)", () => {
  const en = JSON.parse(
    readFileSync(resolve(MESSAGES_DIR, "en.json"), "utf8"),
  ) as Messages;

  it("fills a key missing from the locale with the English string", () => {
    const merged = mergeCatalogs(
      { common: { cancel: "Cancel", back: "Back" } },
      { common: { cancel: "Abbrechen" } },
    );
    expect(merged).toEqual({ common: { cancel: "Abbrechen", back: "Back" } });
  });

  it("merges nested namespaces without dropping siblings", () => {
    const merged = mergeCatalogs(
      { a: { b: { c: "1", d: "2" } }, e: "3" },
      { a: { b: { c: "one" } } },
    );
    expect(merged).toEqual({ a: { b: { c: "one", d: "2" } }, e: "3" });
  });

  it("never mutates its inputs", () => {
    const base = { a: { b: "1" } };
    const override = { a: { b: "2" } };
    mergeCatalogs(base, override);
    expect(base).toEqual({ a: { b: "1" } });
    expect(override).toEqual({ a: { b: "2" } });
  });

  it("gives every shipped locale full English key coverage", () => {
    for (const code of fileLocales) {
      if (code === "en") continue;
      const locale = JSON.parse(
        readFileSync(resolve(MESSAGES_DIR, `${code}.json`), "utf8"),
      ) as Messages;
      const merged = mergeCatalogs(en, locale);
      expect(flatten(merged).size, `${code} loses keys after merge`).toBe(
        flatten(en).size,
      );
    }
  });
});

function flatten(tree: Messages, prefix = ""): Set<string> {
  const out = new Set<string>();
  for (const [key, value] of Object.entries(tree)) {
    const dotted = prefix ? `${prefix}.${key}` : key;
    if (typeof value === "string") out.add(dotted);
    else for (const nested of flatten(value, dotted)) out.add(nested);
  }
  return out;
}
