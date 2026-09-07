import { describe, expect, it } from "vitest";

import { formatAiScore } from "@/components/recruitment/vacancy-candidates-table";

// HRP-274 / HRP-662: the candidates table renders the AI score on the
// tenant's active assessment scale — the raw 0..1 LLM mean lost its
// column when the units toggle went. The helper has to stay resilient to
// a missing value (older candidate rows do not carry
// ``ai_score_normalized`` yet) and emit a stable em-dash so downstream
// sort comparators do not have to invent NaN fall-backs.

describe("formatAiScore", () => {
  it("formats the tenant-scale normalized score with one decimal", () => {
    expect(formatAiScore({ ai_score_normalized: 4.0 })).toBe("4.0");
  });

  it("returns em-dash when the normalized score is missing", () => {
    expect(formatAiScore({ ai_score_normalized: null })).toBe("—");
  });

  it("treats undefined normalized as missing (legacy rows)", () => {
    expect(formatAiScore({ ai_score_normalized: undefined })).toBe("—");
  });
});
