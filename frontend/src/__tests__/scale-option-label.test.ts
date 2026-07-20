import { describe, expect, it } from "vitest";

import { scaleOptionSuffix } from "@/lib/scale-option-label";

describe("scaleOptionSuffix", () => {
  it("renders the weight in parens for a normal option in admin view", () => {
    expect(scaleOptionSuffix({ is_neutral: false, weight: 3 })).toBe("(3)");
    expect(
      scaleOptionSuffix({ is_neutral: false, weight: 0 }, { showScore: true }),
    ).toBe("(0)");
  });

  it("hides the weight for a normal option in participant view", () => {
    expect(
      scaleOptionSuffix({ is_neutral: false, weight: 3 }, { showScore: false }),
    ).toBeNull();
  });

  it("never leaks empty parens for a neutral option with NULL weight", () => {
    expect(
      scaleOptionSuffix({ is_neutral: true, weight: null }, { showScore: true }),
    ).toBe("(not counted)");
    expect(
      scaleOptionSuffix({ is_neutral: true, weight: null }, { showScore: false }),
    ).toBe("(not counted)");
  });

  it("flags any neutral option as not-counted regardless of stored weight", () => {
    expect(
      scaleOptionSuffix({ is_neutral: true, weight: 5 }, { showScore: true }),
    ).toBe("(not counted)");
  });

  it("returns null when a non-neutral option has no weight", () => {
    expect(
      scaleOptionSuffix({ is_neutral: false, weight: null }, { showScore: true }),
    ).toBeNull();
  });
});
