// HRP-731 REDO (QA 30.09): growth zones read from the lowest match up,
// strengths from the highest down.

import { describe, expect, it } from "vitest";

import { splitHighlights } from "@/lib/assessment-highlights";

const rows = (...percents: (number | null)[]) =>
  percents.map((percent, i) => ({ competence_id: `c${i}`, percent }));

const percents = (list: { percent: number | null }[]) => list.map((r) => r.percent);

describe("splitHighlights", () => {
  // The order QA saw on the page: results order, not match order.
  const { growthZones, strengths } = splitHighlights(
    rows(54, 83, 50, 92, 71, 100, 75, 58, 96, 88),
    75,
  );

  it("sorts growth zones ascending by match", () => {
    expect(percents(growthZones)).toEqual([50, 54, 58, 71, 75]);
  });

  it("sorts strengths descending by match", () => {
    expect(percents(strengths)).toEqual([100, 96, 92, 88, 83]);
  });

  it("keeps the bar itself in growth zones and drops unmeasured rows", () => {
    const split = splitHighlights(rows(75, null, 76), 75);
    expect(percents(split.growthZones)).toEqual([75]);
    expect(percents(split.strengths)).toEqual([76]);
  });

  it("does not reorder the caller's array", () => {
    const input = rows(90, 10, 60);
    splitHighlights(input, 75);
    expect(percents(input)).toEqual([90, 10, 60]);
  });
});
