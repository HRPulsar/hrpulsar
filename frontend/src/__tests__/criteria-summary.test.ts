import { describe, expect, it } from "vitest";

import {
  formatCriteriaTypeValue,
  shouldShowCompetencesBlock,
  shouldShowCurrentPositionsHint,
} from "@/components/assessment/criteria-summary";

// HRP-476: the helper composes translated labels — tests pin the i18n keys
// and the composition, the wording itself lives in messages/*.json.
const t = (key: string) => key;

describe("formatCriteriaTypeValue (HRP-98)", () => {
  it("returns the bare label for current_positions", () => {
    expect(formatCriteriaTypeValue(t, "current_positions", null, null, null)).toBe(
      "criteriaTypeCurrentPositions",
    );
  });

  it("returns the bare label for individual competences", () => {
    expect(formatCriteriaTypeValue(t, "competences", null, null, null)).toBe(
      "criteriaTypeCompetences",
    );
  });

  it("inlines Specialization + Grade into the Type line for target_position", () => {
    expect(
      formatCriteriaTypeValue(t, "target_position", "Backend Engineer", "Senior", "grade-id"),
    ).toBe("criteriaTypeTargetPosition: Backend Engineer - Senior");
  });

  it("falls back to the All grades label when no grade is selected", () => {
    expect(
      formatCriteriaTypeValue(t, "target_position", "QA", null, null),
    ).toBe("criteriaTypeTargetPosition: QA - allGrades");
  });

  it("omits the suffix entirely when both Specialization and Grade are missing", () => {
    expect(
      formatCriteriaTypeValue(t, "target_position", null, null, "grade-id"),
    ).toBe("criteriaTypeTargetPosition");
  });
});

describe("shouldShowCurrentPositionsHint (HRP-98)", () => {
  it("hides the helper text on a single assessment (Case 1)", () => {
    expect(shouldShowCurrentPositionsHint("current_positions", false)).toBe(false);
  });

  it("keeps the helper text on the mass-assessment parent (Case 4)", () => {
    expect(shouldShowCurrentPositionsHint("current_positions", true)).toBe(true);
  });

  it("never shows the hint for other criteria types", () => {
    expect(shouldShowCurrentPositionsHint("target_position", true)).toBe(false);
    expect(shouldShowCurrentPositionsHint("competences", true)).toBe(false);
    expect(shouldShowCurrentPositionsHint(null, true)).toBe(false);
  });
});

describe("shouldShowCompetencesBlock (HRP-98)", () => {
  it("shows the block for single + current_positions when competences exist (Case 1)", () => {
    expect(shouldShowCompetencesBlock("current_positions", 3, false)).toBe(true);
  });

  it("hides the block on the mass parent with current_positions (Case 4)", () => {
    expect(shouldShowCompetencesBlock("current_positions", 3, true)).toBe(false);
  });

  it("shows the block on the mass parent with target_position (Case 3)", () => {
    expect(shouldShowCompetencesBlock("target_position", 5, true)).toBe(true);
  });

  it("hides the block when there are no competences to render", () => {
    expect(shouldShowCompetencesBlock("target_position", 0, false)).toBe(false);
  });
});
