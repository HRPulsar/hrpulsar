// @vitest-environment jsdom
/**
 * A request leaving a hidden tab says so in X-Tab-Hidden.
 *
 * Several screens poll on a timer and the timer keeps firing while the
 * visitor is off in another tab. The backend counts an authenticated
 * request as "the visitor is here" (demo activity sampling, idle
 * detection), so without this header a forgotten tab reported hours of
 * engagement and never went idle.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, hiddenTabHeaders } from "@/lib/api";

function okResponse() {
  return {
    ok: true,
    status: 200,
    headers: new Headers({ "content-type": "application/json" }),
    json: async () => ({}),
    text: async () => "{}",
  } as unknown as Response;
}

function setVisibility(state: DocumentVisibilityState) {
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => state,
  });
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.stubGlobal("localStorage", {
    getItem: () => null,
    setItem: () => {},
    removeItem: () => {},
  });
  fetchMock = vi.fn().mockResolvedValue(okResponse());
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  setVisibility("visible");
  vi.unstubAllGlobals();
});

describe("hiddenTabHeaders", () => {
  it("marks a request from a hidden tab", () => {
    setVisibility("hidden");
    expect(hiddenTabHeaders()).toEqual({ "X-Tab-Hidden": "1" });
  });

  it("stays empty while the tab is visible", () => {
    setVisibility("visible");
    expect(hiddenTabHeaders()).toEqual({});
  });
});

describe("api transport", () => {
  it("sends the header on a poll issued from a hidden tab", async () => {
    setVisibility("hidden");
    await api.get("/notifications/unread-count");
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit | undefined;
    expect((init?.headers ?? {}) as Record<string, string>).toMatchObject({
      "X-Tab-Hidden": "1",
    });
  });

  it("omits it while the visitor is looking at the tab", async () => {
    setVisibility("visible");
    await api.get("/notifications/unread-count");
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit | undefined;
    expect((init?.headers ?? {}) as Record<string, string>).not.toHaveProperty(
      "X-Tab-Hidden",
    );
  });
});
