import { describe, expect, it } from "vitest";

import {
  matchPercentColor,
  roundPercent,
} from "@/components/assessment/match-percent-chip";

describe("matchPercentColor (HRP-527)", () => {
  it("paints 75 and above green", () => {
    expect(matchPercentColor(75)).toBe("green");
    expect(matchPercentColor(90)).toBe("green");
    expect(matchPercentColor(100)).toBe("green");
  });

  it("paints 50..74 yellow", () => {
    expect(matchPercentColor(50)).toBe("yellow");
    expect(matchPercentColor(63)).toBe("yellow");
    expect(matchPercentColor(74)).toBe("yellow");
  });

  it("paints below 50 red", () => {
    expect(matchPercentColor(49)).toBe("red");
    expect(matchPercentColor(0)).toBe("red");
  });
});

describe("roundPercent", () => {
  it("rounds half away from zero", () => {
    expect(roundPercent(74.5)).toBe(75);
    expect(roundPercent(74.4)).toBe(74);
    expect(roundPercent(49.5)).toBe(50);
  });

  it("returns null for missing values so the chip renders an em dash", () => {
    expect(roundPercent(null)).toBeNull();
    expect(roundPercent(undefined)).toBeNull();
    expect(roundPercent(Number.NaN)).toBeNull();
  });

  it("keeps integers untouched", () => {
    expect(roundPercent(0)).toBe(0);
    expect(roundPercent(100)).toBe(100);
  });
});

describe("rounding feeds the colour bucket (boundary safety)", () => {
  it("74.6 rounds to 75 and therefore reads green", () => {
    const rounded = roundPercent(74.6);
    expect(rounded).toBe(75);
    expect(matchPercentColor(rounded as number)).toBe("green");
  });

  it("49.6 rounds to 50 and therefore reads yellow", () => {
    const rounded = roundPercent(49.6);
    expect(rounded).toBe(50);
    expect(matchPercentColor(rounded as number)).toBe("yellow");
  });
});
