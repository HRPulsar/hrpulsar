// @vitest-environment jsdom
/**
 * A failed file download carries the backend's localized detail and code,
 * as every JSON call does - not a bare "Request failed (HTTP 409)".
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, ApiError } from "@/lib/api";

beforeEach(() => {
  vi.stubGlobal("localStorage", { getItem: () => null, setItem: () => {} });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function failing(status: number, json: () => Promise<unknown>) {
  return vi.fn(async () => ({ ok: false, status, json }) as unknown as Response);
}

describe("api.fetchBlob errors", () => {
  it("keeps the JSON detail and code", async () => {
    vi.stubGlobal(
      "fetch",
      failing(409, async () => ({
        detail: "Vorschau nicht verfügbar",
        code: "invoice_preview_unavailable",
      })),
    );
    const err = await api.fetchBlob("/x").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).message).toBe("Vorschau nicht verfügbar");
    expect((err as ApiError).code).toBe("invoice_preview_unavailable");
  });

  it("falls back to the status line on a non-JSON body", async () => {
    vi.stubGlobal(
      "fetch",
      failing(502, async () => {
        throw new SyntaxError("not json");
      }),
    );
    const err = await api.fetchBlob("/x").catch((e: unknown) => e);
    expect((err as ApiError).message).toBe("Request failed (HTTP 502)");
  });
});
