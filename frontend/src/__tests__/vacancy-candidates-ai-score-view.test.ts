import { describe, expect, it } from "vitest";

import { formatAiScoreForView } from "@/components/recruitment/vacancy-candidates-table";

// HRP-274: the candidates-table AI column flips between the raw LLM mean
// (canonical 0..1 scale) and the normalized score rebased onto the
// tenant's active assessment scale. The helper has to stay resilient to
// missing values on either side (older candidates rows do not carry
// ``ai_score_normalized`` yet) and emit a stable em-dash so downstream
// sort comparators do not have to invent NaN fall-backs.

describe("formatAiScoreForView", () => {
  it("formats the raw 0..1 LLM mean with two decimals", () => {
    expect(
      formatAiScoreForView({ ai_score: 0.8, ai_score_normalized: 4.0 }, "raw"),
    ).toBe("0.80");
  });

  it("formats the tenant-scale normalized score with one decimal", () => {
    expect(
      formatAiScoreForView({ ai_score: 0.8, ai_score_normalized: 4.0 }, "normalized"),
    ).toBe("4.0");
  });

  it("returns em-dash when raw score is missing", () => {
    expect(
      formatAiScoreForView({ ai_score: null, ai_score_normalized: 4.0 }, "raw"),
    ).toBe("—");
  });

  it("returns em-dash when normalized score is missing", () => {
    expect(
      formatAiScoreForView({ ai_score: 0.8, ai_score_normalized: null }, "normalized"),
    ).toBe("—");
  });

  it("treats undefined normalized as missing (legacy rows)", () => {
    expect(
      formatAiScoreForView(
        { ai_score: 0.8, ai_score_normalized: undefined },
        "normalized",
      ),
    ).toBe("—");
  });
});
