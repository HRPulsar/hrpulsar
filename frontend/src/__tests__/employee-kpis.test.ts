// HRP-247 / HRP-246: pin the formulas behind the Employee profile
// header KPI tiles so the tooltip wording and the sub-line counts stay
// honest as PDP / assessment statuses evolve.

import { describe, expect, it } from "vitest";
import {
  daysSinceCompleted,
  goalsProgressPercent,
  isOpenAssessment,
  isOpenPdp,
  isRunningAssessment,
  latestDoneAssessment,
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

describe("isRunningAssessment (HRP-736 review)", () => {
  // The backend's running set is sent / in_progress: a Draft was never
  // sent, and On review is waiting on the reviewer, not the participants.
  it.each([{ status_code: "sent" }, { status_code: "in_progress" }])(
    "treats $status_code as running",
    (a) => {
      expect(isRunningAssessment(a)).toBe(true);
    },
  );

  it.each([
    { status_code: "draft" },
    { status_code: "on_review" },
    { status_code: "done" },
    { status_code: "cancelled" },
  ])("does not treat $status_code as running", (a) => {
    expect(isRunningAssessment(a)).toBe(false);
  });
});

describe("latestDoneAssessment", () => {
  const iso = (daysAgo: number) =>
    new Date(Date.now() - daysAgo * 24 * 3600 * 1000).toISOString();

  it("ignores assessments that are not Done", () => {
    // HRP-736: the header used to show this on_review row as "today" while
    // the chip two lines above said "no recent assessment".
    expect(
      latestDoneAssessment([
        { status_code: "on_review", created_at: iso(0) },
        { status_code: "done", finished_at: iso(200), created_at: iso(210) },
      ]),
    ).toMatchObject({ status_code: "done" });
  });

  it("ignores cancelled assessments", () => {
    expect(
      latestDoneAssessment([
        { status_code: "cancelled", finished_at: iso(1), created_at: iso(2) },
      ]),
    ).toBeUndefined();
  });

  it("picks the newest by finished_at, not created_at", () => {
    const newest = {
      status_code: "done",
      finished_at: iso(5),
      created_at: iso(400),
    };
    expect(
      latestDoneAssessment([
        { status_code: "done", finished_at: iso(50), created_at: iso(60) },
        newest,
      ]),
    ).toBe(newest);
  });

  it("skips a done assessment the backend has not dated", () => {
    // HRP-736 review: assessed_recent (employee/issues.py) ignores rows
    // without finished_at, so dating one by created_at could put "3 d"
    // next to an assessment_stale chip.
    const dated = { status_code: "done", finished_at: iso(30), created_at: iso(40) };
    const undated = { status_code: "done", finished_at: null, created_at: iso(3) };
    expect(latestDoneAssessment([undated, dated])).toBe(dated);
    expect(latestDoneAssessment([undated])).toBeUndefined();
  });

  it("returns undefined when nothing is done", () => {
    expect(latestDoneAssessment([])).toBeUndefined();
  });

  it("counts age from the completion date", () => {
    expect(daysSinceCompleted({ finished_at: iso(200) })).toBe(200);
  });
});
