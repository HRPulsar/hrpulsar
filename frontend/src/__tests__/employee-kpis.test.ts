// HRP-247 / HRP-246: pin the formulas behind the Employee profile
// header KPI tiles so the tooltip wording and the sub-line counts stay
// honest as PDP / assessment statuses evolve.

import { describe, expect, it } from "vitest";
import {
  goalsProgressPercent,
  isOpenAssessment,
  isOpenPdp,
  openAssessmentCount,
  openPdpCount,
} from "@/lib/employee-kpis";

describe("isOpenPdp (HRP-246)", () => {
  it.each([
    { status: "draft" },
    { status: "sent" },
    { status: "in_progress" },
    { status: "review" },
    { status: "returned" },
  ])("treats $status as open", (p) => {
    expect(isOpenPdp({ ...p, total_progress: 10 })).toBe(true);
  });

  it.each([{ status: "done" }, { status: "cancelled" }])(
    "treats $status as closed",
    (p) => {
      expect(isOpenPdp({ ...p, total_progress: 100 })).toBe(false);
    },
  );

  it("does not match the legacy 'completed' literal — PDPs use 'done'", () => {
    // Guard against re-introducing the original HRP-246 bug.
    expect(isOpenPdp({ status: "completed", total_progress: 0 })).toBe(true);
  });
});

describe("goalsProgressPercent (HRP-247)", () => {
  it("averages total_progress across open plans only", () => {
    expect(
      goalsProgressPercent([
        { status: "in_progress", total_progress: 50 },
        { status: "review", total_progress: 60 },
        { status: "done", total_progress: 100 },
        { status: "cancelled", total_progress: 0 },
      ]),
    ).toBe(55);
  });

  it("rounds to the nearest integer", () => {
    expect(
      goalsProgressPercent([
        { status: "in_progress", total_progress: 33 },
        { status: "in_progress", total_progress: 34 },
        { status: "in_progress", total_progress: 34 },
      ]),
    ).toBe(34);
  });

  it("returns null when no open plans remain so the tile renders a dash", () => {
    expect(
      goalsProgressPercent([
        { status: "done", total_progress: 100 },
        { status: "cancelled", total_progress: 0 },
      ]),
    ).toBeNull();
    expect(goalsProgressPercent([])).toBeNull();
  });

  it("handles missing total_progress as zero", () => {
    expect(
      goalsProgressPercent([
        { status: "in_progress" } as unknown as {
          status: string;
          total_progress: number;
        },
        { status: "in_progress", total_progress: 100 },
      ]),
    ).toBe(50);
  });
});

describe("openPdpCount (HRP-246)", () => {
  it("excludes Done and Cancelled plans", () => {
    expect(
      openPdpCount([
        { status: "draft", total_progress: 0 },
        { status: "in_progress", total_progress: 10 },
        { status: "done", total_progress: 100 },
        { status: "cancelled", total_progress: 0 },
      ]),
    ).toBe(2);
  });
});

describe("isOpenAssessment / openAssessmentCount (HRP-246)", () => {
  it.each([
    { status_code: "draft" },
    { status_code: "sent" },
    { status_code: "in_progress" },
    { status_code: "on_review" },
  ])("treats $status_code as open", (a) => {
    expect(isOpenAssessment(a)).toBe(true);
  });

  it.each([{ status_code: "done" }, { status_code: "cancelled" }])(
    "treats $status_code as closed",
    (a) => {
      expect(isOpenAssessment(a)).toBe(false);
    },
  );

  it("counts only non-terminal rows", () => {
    expect(
      openAssessmentCount([
        { status_code: "draft" },
        { status_code: "on_review" },
        { status_code: "done" },
        { status_code: "cancelled" },
      ]),
    ).toBe(2);
  });
});
