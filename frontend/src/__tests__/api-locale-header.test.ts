// @vitest-environment jsdom
/**
 * HRP-513: every API call states the interface locale in X-Locale.
 *
 * The NEXT_LOCALE cookie is not sent when NEXT_PUBLIC_API_URL points at
 * another origin (fetch defaults to `same-origin` credentials), so the
 * cookie alone left cross-origin deployments with English error bodies.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import {
  LOCALE_HEADER,
  clearLocaleCookie,
  localeRequestHeaders,
  setLocaleCookie,
} from "@/i18n/config";

function okResponse() {
  return {
    ok: true,
    status: 200,
    headers: new Headers({ "content-type": "application/json" }),
    json: async () => ({}),
    text: async () => "{}",
  } as unknown as Response;
}

function sentHeaders(fetchMock: ReturnType<typeof vi.fn>): Record<string, string> {
  const init = fetchMock.mock.calls[0]?.[1] as RequestInit | undefined;
  return (init?.headers ?? {}) as Record<string, string>;
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  window.__ENV__ = { NEXT_PUBLIC_AVAILABLE_LOCALES: "de,en" };
  vi.stubGlobal("localStorage", {
    getItem: () => null,
    setItem: () => {},
    removeItem: () => {},
  });
  fetchMock = vi.fn().mockResolvedValue(okResponse());
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  delete window.__ENV__;
  clearLocaleCookie();
  vi.unstubAllGlobals();
});

describe("localeRequestHeaders", () => {
  it("states the locale chosen in the cookie", () => {
    setLocaleCookie("de");
    expect(localeRequestHeaders()).toEqual({ [LOCALE_HEADER]: "de" });
  });

  it("stays empty without a cookie, so Accept-Language decides", () => {
    expect(localeRequestHeaders()).toEqual({});
  });

  it("drops a locale this deployment does not ship", () => {
    setLocaleCookie("fr");
    expect(localeRequestHeaders()).toEqual({});
  });
});

describe("api transport", () => {
  it("sends X-Locale on requests", async () => {
    setLocaleCookie("de");
    await api.get("/employees");
    expect(sentHeaders(fetchMock)[LOCALE_HEADER]).toBe("de");
  });

  it("omits the header when no locale is chosen", async () => {
    await api.get("/employees");
    expect(sentHeaders(fetchMock)[LOCALE_HEADER]).toBeUndefined();
  });

  it("lets an explicit caller header win", async () => {
    setLocaleCookie("de");
    await api.post("/employees", {}, { headers: { [LOCALE_HEADER]: "en" } });
    expect(sentHeaders(fetchMock)[LOCALE_HEADER]).toBe("en");
  });
});
