// HRP-105: pins the success-vs-warning branching the Position card and the
// spec AI Generate page share via `resolveApplyToast`.

import { describe, expect, it } from "vitest";
import { resolveApplyToast } from "@/lib/matrix-apply-toast";
import type { ApplyResult } from "@/lib/api/competence-generation";

function makeResult(overrides: Partial<ApplyResult> = {}): ApplyResult {
  return {
    created_groups: [],
    created_competences: [],
    created_indicators: [],
    created_grade_links: [],
    idempotency_key: "test-key",
    ...overrides,
  };
}

describe("resolveApplyToast", () => {
  it("returns warning when neither competences nor grade links were created", () => {
    const decision = resolveApplyToast(makeResult());
    expect(decision.kind).toBe("warning");
    expect(decision.addedCompetences).toBe(0);
    expect(decision.addedGradeLinks).toBe(0);
  });

  it("returns success when new competences were persisted", () => {
    const decision = resolveApplyToast(
      makeResult({
        created_competences: ["c1", "c2"],
        created_grade_links: ["l1"],
      }),
    );
    expect(decision.kind).toBe("success");
    expect(decision.addedCompetences).toBe(2);
    expect(decision.addedGradeLinks).toBe(1);
  });

  it("returns success when only grade links were created (no new competences)", () => {
    // Existing competences attached to additional grades — apply still
    // changed the matrix, the operator should see a success.
    const decision = resolveApplyToast(
      makeResult({ created_grade_links: ["l1", "l2"] }),
    );
    expect(decision.kind).toBe("success");
    expect(decision.addedCompetences).toBe(0);
    expect(decision.addedGradeLinks).toBe(2);
  });

  it("returns success when only competences were created (no grade links)", () => {
    const decision = resolveApplyToast(
      makeResult({ created_competences: ["c1"] }),
    );
    expect(decision.kind).toBe("success");
    expect(decision.addedCompetences).toBe(1);
    expect(decision.addedGradeLinks).toBe(0);
  });
});
