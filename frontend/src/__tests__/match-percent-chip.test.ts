import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  MatchPercentChip,
  matchPercentColor,
  roundPercent,
} from "@/components/assessment/match-percent-chip";

describe("matchPercentColor (HRP-527)", () => {
  it("paints 75 and above green", () => {
    // HRP-731: the bar itself is a gap, so it can no longer be green.
    expect(matchPercentColor(75)).toBe("yellow");
    expect(matchPercentColor(76)).toBe("green");
    expect(matchPercentColor(90)).toBe("green");
    expect(matchPercentColor(100)).toBe("green");
  });

  it("paints 50..74 yellow", () => {
    expect(matchPercentColor(50)).toBe("yellow");
    expect(matchPercentColor(63)).toBe("yellow");
    expect(matchPercentColor(74)).toBe("yellow");
    expect(matchPercentColor(75)).toBe("yellow");
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
  it("74.6 rounds to 75, which is the bar and therefore still a gap", () => {
    // HRP-731: rounding up to the bar no longer buys a green chip — the
    // bar itself is a growth zone.
    const rounded = roundPercent(74.6);
    expect(rounded).toBe(75);
    expect(matchPercentColor(rounded as number)).toBe("yellow");
  });

  it("75.6 rounds to 76 and clears the bar", () => {
    const rounded = roundPercent(75.6);
    expect(rounded).toBe(76);
    expect(matchPercentColor(rounded as number)).toBe("green");
  });

  it("49.6 rounds to 50 and therefore reads yellow", () => {
    const rounded = roundPercent(49.6);
    expect(rounded).toBe(50);
    expect(matchPercentColor(rounded as number)).toBe("yellow");
  });
});

describe("bar prop (HRP-731 review)", () => {
  // Growth zones / Strengths split on the assessment's own passing_score,
  // so the chip next to each row has to colour against that same bar.
  it("colours 65 against the given bar", () => {
    expect(matchPercentColor(65, 60)).toBe("green");
    expect(matchPercentColor(65, 75)).toBe("yellow");
  });

  it("forwards the bar from the chip to the colour rule", () => {
    const html = (bar: number) =>
      renderToStaticMarkup(createElement(MatchPercentChip, { percent: 65, bar }));
    expect(html(60)).toContain("bg-green-100");
    expect(html(75)).toContain("bg-yellow-100");
  });
});
