// HRP-96: pin the auto-expand rule for the AI generation Refine panel.
// The rendering layer is exercised manually; vitest runs without jsdom, so
// the test asserts the pure rule the component relies on.

import { describe, expect, it } from "vitest";
import { shouldStartExpanded } from "@/components/competence-generation/RefinementPanel";

describe("shouldStartExpanded (Refine detailed form)", () => {
  it("returns false when no initial values are passed", () => {
    expect(shouldStartExpanded(undefined)).toBe(false);
    expect(shouldStartExpanded(null)).toBe(false);
    expect(shouldStartExpanded({})).toBe(false);
  });

  it("ignores the general field — it does not expand the detailed form on its own", () => {
    expect(shouldStartExpanded({ general: "tighten the wording" })).toBe(false);
  });

  it("expands when any granular field carries previously saved input", () => {
    expect(shouldStartExpanded({ add: "missing competence" })).toBe(true);
    expect(shouldStartExpanded({ change: "rewrite leadership" })).toBe(true);
    expect(shouldStartExpanded({ exclude: "drop intern items" })).toBe(true);
    expect(
      shouldStartExpanded({ general: "x", add: "y" }),
    ).toBe(true);
  });

  it("treats null/empty granular values as empty", () => {
    expect(
      shouldStartExpanded({ add: null, change: "", exclude: null }),
    ).toBe(false);
  });
});
