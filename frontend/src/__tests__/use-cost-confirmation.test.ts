import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Pure unit test of the threshold/cost decision rule. We don't render the hook
// because vitest is configured without jsdom; instead we exercise the same
// branching that the hook applies.

function decidesConfirmation(
  cost: number | null,
  threshold: number,
): { requiresConfirmation: boolean } {
  const requiresConfirmation =
    threshold > 0 && cost !== null && cost >= threshold;
  return { requiresConfirmation };
}

describe("cost confirmation rule", () => {
  it("does not require confirmation when threshold is 0 (disabled)", () => {
    expect(decidesConfirmation(50, 0).requiresConfirmation).toBe(false);
  });

  it("does not require confirmation when cost is unknown", () => {
    expect(decidesConfirmation(null, 10).requiresConfirmation).toBe(false);
  });

  it("does not require confirmation when cost is below threshold", () => {
    expect(decidesConfirmation(5, 10).requiresConfirmation).toBe(false);
  });

  it("requires confirmation when cost equals threshold", () => {
    expect(decidesConfirmation(10, 10).requiresConfirmation).toBe(true);
  });

  it("requires confirmation when cost exceeds threshold", () => {
    expect(decidesConfirmation(75, 10).requiresConfirmation).toBe(true);
  });
});

describe("invalidateCostConfirmationCache import", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("exports a callable cache invalidator", async () => {
    const mod = await import("../hooks/use-cost-confirmation");
    expect(typeof mod.invalidateCostConfirmationCache).toBe("function");
    expect(() => mod.invalidateCostConfirmationCache()).not.toThrow();
  });
});

describe("fetchCosts price source (HRP-509)", () => {
  const categories = (cost: number) => [
    {
      category: "ai_competence_generation",
      actions: [
        {
          action: "ai_competence_generation.start_whole_base",
          name: "start_whole_base",
          cost,
        },
      ],
    },
  ];

  beforeEach(() => {
    vi.resetModules();
    vi.stubGlobal("window", {} as unknown as Window);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("quotes the workspace-effective list when signed in", async () => {
    // The public list carries base prices; a workspace on a heavier model
    // is charged base x multiplier — quoting 200 while deducting 340 is
    // exactly what QA hit.
    vi.stubGlobal("localStorage", { getItem: () => "token" });
    const fetchMock = vi.fn(async (url: string) => ({
      ok: true,
      json: async () =>
        url.includes("/effective") ? categories(340) : categories(200),
    }));
    vi.stubGlobal("fetch", fetchMock);

    const mod = await import("../hooks/use-cost-confirmation");
    const map = await mod.fetchCosts();

    expect(map["ai_competence_generation.start_whole_base"]).toBe(340);
    expect(fetchMock.mock.calls[0][0]).toContain("/billing/costs/effective");
  });

  it("falls back to the public list when the effective one is unavailable", async () => {
    vi.stubGlobal("localStorage", { getItem: () => "token" });
    const fetchMock = vi.fn(async (url: string) =>
      url.includes("/effective")
        ? { ok: false, json: async () => ({}) }
        : { ok: true, json: async () => categories(200) },
    );
    vi.stubGlobal("fetch", fetchMock);

    const mod = await import("../hooks/use-cost-confirmation");
    const map = await mod.fetchCosts();

    expect(map["ai_competence_generation.start_whole_base"]).toBe(200);
  });

  it("uses the public list when there is no token", async () => {
    vi.stubGlobal("localStorage", { getItem: () => null });
    const fetchMock = vi.fn(async (url: string) => ({
      ok: true,
      url,
      json: async () => categories(200),
    }));
    vi.stubGlobal("fetch", fetchMock);

    const mod = await import("../hooks/use-cost-confirmation");
    await mod.fetchCosts();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).not.toContain("/effective");
  });
});

describe("cost cache freshness (HRP-509 review #3)", () => {
  const categories = (cost: number) => [
    {
      category: "ai_competence_generation",
      actions: [
        {
          action: "ai_competence_generation.start_whole_base",
          name: "start_whole_base",
          cost,
        },
      ],
    },
  ];

  beforeEach(() => {
    vi.resetModules();
    vi.stubGlobal("window", {} as unknown as Window);
    vi.stubGlobal("localStorage", { getItem: () => null });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("re-quotes after an explicit invalidation", async () => {
    // Switching the workspace model changes every multiplied price; the
    // module cache used to hold the old ones until a full reload.
    let cost = 200;
    const fetchMock = vi.fn(async (url: string) => ({
      ok: true,
      url,
      json: async () => categories(cost),
    }));
    vi.stubGlobal("fetch", fetchMock);

    const mod = await import("../hooks/use-cost-confirmation");
    expect((await mod.fetchCosts())["ai_competence_generation.start_whole_base"]).toBe(
      200,
    );

    cost = 340;
    expect((await mod.fetchCosts())["ai_competence_generation.start_whole_base"]).toBe(
      200,
    );

    mod.invalidateCostConfirmationCache();
    expect((await mod.fetchCosts())["ai_competence_generation.start_whole_base"]).toBe(
      340,
    );
  });

  it("re-fetches once the cached list goes stale", async () => {
    vi.useFakeTimers();
    let cost = 200;
    const fetchMock = vi.fn(async (url: string) => ({
      ok: true,
      url,
      json: async () => categories(cost),
    }));
    vi.stubGlobal("fetch", fetchMock);

    const mod = await import("../hooks/use-cost-confirmation");
    await mod.fetchCosts();
    expect(fetchMock).toHaveBeenCalledTimes(1);

    cost = 340;
    vi.advanceTimersByTime(6 * 60 * 1000);
    expect((await mod.fetchCosts())["ai_competence_generation.start_whole_base"]).toBe(
      340,
    );
  });
});
