// @vitest-environment jsdom
// i18n F1 (HRP-475): request-locale resolution helpers and the
// NEXT_LOCALE cookie writers. Mirrors backend/app/core/i18n.py tests.
import { afterEach, describe, expect, it } from "vitest";

import {
  clearLocaleCookie,
  normalizeLocale,
  parseAcceptLanguage,
  readLocaleCookie,
  resolveRequestLocale,
  setLocaleCookie,
} from "@/i18n/config";
import { CATALOG_LOCALES } from "@/lib/locale";

type Env = NonNullable<Window["__ENV__"]>;

function setEnv(env: Env) {
  window.__ENV__ = env;
}

afterEach(() => {
  delete window.__ENV__;
  clearLocaleCookie();
});

describe("parseAcceptLanguage", () => {
  it("orders by quality", () => {
    expect(parseAcceptLanguage("en;q=0.5, de, fr;q=0.8")).toEqual([
      "de",
      "fr",
      "en",
    ]);
  });

  it("skips wildcard and zero quality", () => {
    expect(parseAcceptLanguage("*, de;q=0, en;q=0.1")).toEqual(["en"]);
  });

  it("drops tags with malformed q-values", () => {
    expect(parseAcceptLanguage("de;q=broken, en;q=0.9")).toEqual(["en"]);
    expect(parseAcceptLanguage("de;q=0.0000, en")).toEqual(["en"]);
  });

  it("matches the q parameter case-insensitively", () => {
    expect(parseAcceptLanguage("en;Q=0.1, de;q=0.9")).toEqual(["de", "en"]);
  });

  it("handles empty input", () => {
    expect(parseAcceptLanguage(null)).toEqual([]);
    expect(parseAcceptLanguage("")).toEqual([]);
  });

  it("keeps header order on equal q-values (stable sort)", () => {
    expect(parseAcceptLanguage("de, fr, en")).toEqual(["de", "fr", "en"]);
    expect(parseAcceptLanguage("de;q=0.5, fr;q=0.5")).toEqual(["de", "fr"]);
  });
});

describe("normalizeLocale", () => {
  it("matches the primary subtag against available locales", () => {
    setEnv({ NEXT_PUBLIC_AVAILABLE_LOCALES: "de,en" });
    expect(normalizeLocale("de-DE")).toBe("de");
    expect(normalizeLocale("de_AT")).toBe("de");
    expect(normalizeLocale("EN")).toBe("en");
  });

  it("returns undefined for unsupported values", () => {
    setEnv({ NEXT_PUBLIC_AVAILABLE_LOCALES: "de,en" });
    expect(normalizeLocale("fr")).toBeUndefined();
    expect(normalizeLocale("")).toBeUndefined();
    expect(normalizeLocale(undefined)).toBeUndefined();
  });
});

describe("resolveRequestLocale", () => {
  it("prefers a valid cookie", () => {
    setEnv({ NEXT_PUBLIC_AVAILABLE_LOCALES: "de,en" });
    expect(resolveRequestLocale("de", "en")).toBe("de");
  });

  it("falls back to Accept-Language for an invalid cookie", () => {
    setEnv({ NEXT_PUBLIC_AVAILABLE_LOCALES: "de,en" });
    expect(resolveRequestLocale("fr", "de-DE,de;q=0.9")).toBe("de");
  });

  it("falls back to the deployment default", () => {
    setEnv({
      NEXT_PUBLIC_AVAILABLE_LOCALES: "de,en",
      NEXT_PUBLIC_DEFAULT_LOCALE: "de",
    });
    expect(resolveRequestLocale(undefined, "fr")).toBe("de");
    expect(resolveRequestLocale(undefined, undefined)).toBe("de");
  });

  it("never selects a shipped catalog the site does not offer", () => {
    // The bundle carries more catalogs than a given site enables (an
    // enterprise build ships ru while an English-default site offers
    // en only) — neither a cookie nor the browser language may pull the
    // interface, demo popup included, into a locale outside
    // AVAILABLE_LOCALES.
    setEnv({
      NEXT_PUBLIC_AVAILABLE_LOCALES: "en",
      NEXT_PUBLIC_DEFAULT_LOCALE: "en",
    });
    expect(resolveRequestLocale("de", "de-DE,de;q=0.9")).toBe("en");
    if (CATALOG_LOCALES.includes("ru")) {
      // Enterprise bundle only — the community stub ships no ru catalog.
      expect(resolveRequestLocale("ru", "ru-RU,ru;q=0.9")).toBe("en");
    }
  });
});

describe("locale cookie", () => {
  it("writes, reads and clears NEXT_LOCALE", () => {
    expect(readLocaleCookie()).toBeUndefined();
    setLocaleCookie("de");
    expect(readLocaleCookie()).toBe("de");
    clearLocaleCookie();
    expect(readLocaleCookie()).toBeUndefined();
  });
});
