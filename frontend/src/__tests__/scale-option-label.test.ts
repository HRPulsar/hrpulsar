import { describe, expect, it } from "vitest";

import { scaleOptionSuffix } from "@/lib/scale-option-label";

// HRP-476: the neutral suffix is translated — the helper takes the
// `assessments` translator. Tests pin the key (the wording itself lives in
// messages/*.json), weights stay numeric and locale-independent.
const t = (key: string) => key;

describe("scaleOptionSuffix", () => {
  it("renders the weight in parens for a normal option in admin view", () => {
    expect(scaleOptionSuffix(t, { is_neutral: false, weight: 3 })).toBe("(3)");
    expect(
      scaleOptionSuffix(t, { is_neutral: false, weight: 0 }, { showScore: true }),
    ).toBe("(0)");
  });

  it("hides the weight for a normal option in participant view", () => {
    expect(
      scaleOptionSuffix(t, { is_neutral: false, weight: 3 }, { showScore: false }),
    ).toBeNull();
  });

  it("never leaks empty parens for a neutral option with NULL weight", () => {
    expect(
      scaleOptionSuffix(t, { is_neutral: true, weight: null }, { showScore: true }),
    ).toBe("scaleOptionNotCounted");
    expect(
      scaleOptionSuffix(t, { is_neutral: true, weight: null }, { showScore: false }),
    ).toBe("scaleOptionNotCounted");
  });

  it("flags any neutral option as not-counted regardless of stored weight", () => {
    expect(
      scaleOptionSuffix(t, { is_neutral: true, weight: 5 }, { showScore: true }),
    ).toBe("scaleOptionNotCounted");
  });

  it("returns null when a non-neutral option has no weight", () => {
    expect(
      scaleOptionSuffix(t, { is_neutral: false, weight: null }, { showScore: true }),
    ).toBeNull();
  });
});
