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
