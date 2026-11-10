// @vitest-environment jsdom
/**
 * HRP-1158: every successful non-GET request announces itself on
 * `window` as `hrpulsar:mutation` — the contract the demo card, the demo
 * banner and the sandbox guide listen to. Both transports do: `request()`
 * and the ETag-aware `requestWithMeta()` behind `sendWithMeta`.
 */
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { api, MUTATION_EVENT, type MutationEventDetail } from "@/lib/api";

function response(status: number, body: unknown = {}) {
  return {
    ok: status < 400,
    status,
    statusText: "",
    headers: new Headers({ "content-type": "application/json" }),
    json: async () => body,
  } as unknown as Response;
}

let seen: MutationEventDetail[];
const listen = (e: Event) => seen.push((e as CustomEvent<MutationEventDetail>).detail);

beforeEach(() => {
  seen = [];
  vi.stubGlobal("localStorage", {
    getItem: () => null,
    setItem: () => {},
    removeItem: () => {},
  });
  window.addEventListener(MUTATION_EVENT, listen);
});

afterEach(() => {
  window.removeEventListener(MUTATION_EVENT, listen);
  vi.unstubAllGlobals();
});

it("reports a successful POST with its path and parsed body", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(201, { id: "p-1" })));
  await api.post("/work/decomposition/sessions/s-1/apply?force=true", {});
  expect(seen).toEqual([
    {
      method: "POST",
      path: "/work/decomposition/sessions/s-1/apply",
      status: 201,
      data: { id: "p-1" },
    },
  ]);
});

it("reports a 204 without a body", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(204)));
  await api.delete("/pdp/p-1");
  expect(seen).toEqual([
    { method: "DELETE", path: "/pdp/p-1", status: 204, data: undefined },
  ]);
});

it("stays quiet for reads and failures", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(response(200, []))
      .mockResolvedValueOnce(response(409, { detail: "nope" })),
  );
  await api.get("/pdp");
  await expect(api.post("/pdp", {})).rejects.toThrow("nope");
  expect(seen).toEqual([]);
});

it("reports an ETag-aware edit the same way", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(200, { id: "v-1" })));
  await api.sendWithMeta("/recruitment/vacancies/v-1?x=1", "PATCH", { title: "T" });
  expect(seen).toEqual([
    {
      method: "PATCH",
      path: "/recruitment/vacancies/v-1",
      status: 200,
      data: { id: "v-1" },
    },
  ]);
});

it("stays quiet for an ETag-aware read", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(200, {})));
  await api.getWithMeta("/recruitment/vacancies/v-1");
  expect(seen).toEqual([]);
});
