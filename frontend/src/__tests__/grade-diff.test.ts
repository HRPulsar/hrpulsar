// HRP-158: pins the additive vs. destructive split inside the Manage
// grades dialog. The dialog itself isn't rendered (vitest runs without
// jsdom) — these tests cover the pure logic the modal feeds the save
// handler before it pipes the diff through addGrades / deleteGrade.

import { describe, expect, it } from "vitest";

import { computeGradeDiff } from "@/lib/grade-diff";

describe("computeGradeDiff", () => {
  it("treats selected-but-not-yet-attached ids as additions, preserving tick order", () => {
    const diff = computeGradeDiff(["g3", "g1"], new Set());
    expect(diff.toAdd).toEqual(["g3", "g1"]);
    expect(diff.toRemove).toEqual([]);
  });

  it("treats pre-attached but newly unchecked ids as removals", () => {
    const diff = computeGradeDiff([], new Set(["g1", "g2"]));
    expect(diff.toAdd).toEqual([]);
    expect(diff.toRemove.sort()).toEqual(["g1", "g2"]);
  });

  it("produces both directions when the user mixes ticks and unticks", () => {
    // The dialog opened with {g1, g2} pre-checked; the operator unticked g2
    // and ticked g3. Expect g3→add, g2→remove, g1 untouched.
    const diff = computeGradeDiff(["g1", "g3"], new Set(["g1", "g2"]));
    expect(diff.toAdd).toEqual(["g3"]);
    expect(diff.toRemove).toEqual(["g2"]);
  });

  it("is a no-op when the selection mirrors the pre-attached set", () => {
    const diff = computeGradeDiff(["g1", "g2"], new Set(["g1", "g2"]));
    expect(diff.toAdd).toEqual([]);
    expect(diff.toRemove).toEqual([]);
  });
});
