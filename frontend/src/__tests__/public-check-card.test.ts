// HRP-928: the link-preview card of a result. A ready check gets its own
// card, cached for minutes (it names a process its owner may delete); a check still running,
// expired or unknown gets the card of the service under the same URL - and
// that one must never be cached, or the figure would never replace it.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/server", () => ({ connection: async () => undefined }));
vi.mock("next-intl/server", () => ({ getLocale: async () => "en" }));

const { default: resultCardRoute } = await import("@/app/(check)/check/r/[token]/opengraph-image");

const fetchMock = vi.fn();
const params = Promise.resolve({ token: "tok-1" });

beforeEach(() => {
  vi.stubEnv("PUBLIC_CHECK_ENABLED", "true");
  vi.stubEnv("PUBLIC_CHECK_HOST", "check.hrpulsar.com");
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

function answer(body: object | null, status = 200) {
  fetchMock.mockResolvedValue({ ok: status === 200, status, json: async () => body });
}

const step = (position: number) => ({ position, title: `Step ${position}` });
const ready = {
  status: "ready",
  locale: "en",
  title: "Month-end close",
  result: { buckets: { moves: [step(1)], to_review: [step(2)], stays: [] }, out_of_scope: [] },
};

describe("the card of a result", () => {
  it("is a PNG cached briefly once the check is ready - never next/og's immutable year", async () => {
    vi.stubEnv("NODE_ENV", "production"); // next/og's default is per environment
    answer(ready);
    const res = await resultCardRoute({ params });
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toBe("image/png");
    // It names a process the visitor may delete: the CDN lets go soon.
    expect(res.headers.get("cache-control")).toBe("public, max-age=300");
  });

  it.each([
    ["still running", () => answer({ ...ready, status: "running", result: null })],
    ["unknown or expired", () => answer({ detail: "not found" }, 404)],
  ])("is the service's card, never cached, while the check is %s", async (_label, arrange) => {
    arrange();
    const res = await resultCardRoute({ params });
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toBe("image/png");
    expect(res.headers.get("cache-control")).toBe("no-store");
  });

  it("does not exist while the service is off", async () => {
    vi.stubEnv("PUBLIC_CHECK_ENABLED", "");
    const res = await resultCardRoute({ params });
    expect(res.status).toBe(404);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
