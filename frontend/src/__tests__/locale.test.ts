// @vitest-environment jsdom
// i18n F0 (HRP-474): deployment-locale getters — defaults, parsing,
// runtime overrides.
import { afterEach, describe, expect, it } from "vitest";

import {
  FALLBACK_LOCALE,
  getAvailableLocales,
  getDefaultLocale,
  localeLabel,
} from "@/lib/locale";

type Env = NonNullable<Window["__ENV__"]>;

function setEnv(env: Env) {
  window.__ENV__ = env;
}

afterEach(() => {
  delete window.__ENV__;
  delete process.env.NEXT_PUBLIC_AVAILABLE_LOCALES;
  delete process.env.NEXT_PUBLIC_DEFAULT_LOCALE;
});

describe("stock defaults", () => {
  it("is English-only with no overrides", () => {
    expect(getAvailableLocales()).toEqual([FALLBACK_LOCALE]);
    expect(getDefaultLocale()).toBe(FALLBACK_LOCALE);
  });
});

describe("runtime overrides via window.__ENV__", () => {
  it("parses a comma-separated list, normalizing case and whitespace", () => {
    setEnv({ NEXT_PUBLIC_AVAILABLE_LOCALES: " De , EN " });
    expect(getAvailableLocales()).toEqual(["de", "en"]);
  });

  it("drops locales without a shipped catalog", () => {
    setEnv({ NEXT_PUBLIC_AVAILABLE_LOCALES: "fr,en" });
    expect(getAvailableLocales()).toEqual(["en"]);
  });

  it("falls back to English when no listed locale has a catalog", () => {
    setEnv({ NEXT_PUBLIC_AVAILABLE_LOCALES: "fr" });
    expect(getAvailableLocales()).toEqual([FALLBACK_LOCALE]);
  });

  it("uses the configured default locale when it is listed", () => {
    setEnv({
      NEXT_PUBLIC_AVAILABLE_LOCALES: "de,en",
      NEXT_PUBLIC_DEFAULT_LOCALE: "de",
    });
    expect(getDefaultLocale()).toBe("de");
  });

  it("falls back to the first available locale when the default is not listed", () => {
    setEnv({
      NEXT_PUBLIC_AVAILABLE_LOCALES: "de,en",
      NEXT_PUBLIC_DEFAULT_LOCALE: "fr",
    });
    expect(getDefaultLocale()).toBe("de");
  });

  it("falls back to the first available locale when no default is set", () => {
    setEnv({ NEXT_PUBLIC_AVAILABLE_LOCALES: "de" });
    expect(getDefaultLocale()).toBe("de");
  });
});

describe("process.env fallback", () => {
  it("reads process.env when window.__ENV__ is absent", () => {
    process.env.NEXT_PUBLIC_AVAILABLE_LOCALES = "de,en";
    process.env.NEXT_PUBLIC_DEFAULT_LOCALE = "en";
    expect(getAvailableLocales()).toEqual(["de", "en"]);
    expect(getDefaultLocale()).toBe("en");
  });
});

describe("localeLabel", () => {
  it("returns native names for known locales and the raw code otherwise", () => {
    expect(localeLabel("en")).toBe("English");
    expect(localeLabel("de")).toBe("Deutsch");
    expect(localeLabel("xx")).toBe("xx");
  });
});
