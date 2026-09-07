// Review follow-up on HRP-673: the analysis panel fetches the tenant's
// active scale after the first paint, and the parent passes no `scaleMax`.
// With the placeholder bound lowered to 1 every bar rendered 100% green
// until the answer arrived — and stayed that way when the request failed.
// While the bound is unknown the bar must be empty and neutral; a failed
// request falls back to the pre-HRP-673 5-point default.

import { describe, expect, it } from "vitest";

import {
  FALLBACK_SCALE_MAX,
  scoreBar,
} from "@/components/recruitment/interview-analysis";

describe("scoreBar (HRP-673 follow-up)", () => {
  it("draws nothing while the scale is still unknown", () => {
    expect(scoreBar(0.9, null)).toEqual({ pct: 0, tone: "bg-muted" });
    expect(scoreBar(5, null)).toEqual({ pct: 0, tone: "bg-muted" });
  });

  it("draws nothing for a missing score whatever the scale", () => {
    expect(scoreBar(null, 5)).toEqual({ pct: 0, tone: "bg-muted" });
    expect(scoreBar(undefined, null)).toEqual({ pct: 0, tone: "bg-muted" });
  });

  it("fills and colours against a known scale", () => {
    expect(scoreBar(4, 5)).toEqual({ pct: 80, tone: "bg-emerald-500" });
    expect(scoreBar(2.5, 5)).toEqual({ pct: 50, tone: "bg-amber-500" });
    expect(scoreBar(1, 5)).toEqual({ pct: 20, tone: "bg-rose-500" });
    // The identity scale of a tenant with no active ScaleConfig.
    expect(scoreBar(0.9, 1)).toEqual({ pct: 90, tone: "bg-emerald-500" });
  });

  it("clamps an out-of-range score to the bar", () => {
    expect(scoreBar(7, 5).pct).toBe(100);
    expect(scoreBar(-1, 5).pct).toBe(0);
  });

  it("keeps the pre-HRP-673 bound for a failed scale request", () => {
    expect(FALLBACK_SCALE_MAX).toBe(5);
  });
});
