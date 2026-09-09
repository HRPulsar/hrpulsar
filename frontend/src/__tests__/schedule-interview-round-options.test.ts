// @vitest-environment jsdom
//
// HRP-741 — the Round select of Schedule interview offered every
// assessment round of the candidate-vacancy, Pre-interview included.
// A pre-interview round is not a slot an interview is scheduled into,
// so it must not be offered — while an interview already bound to one
// keeps showing its own value, or opening Edit would blank the field.

import { describe, expect, it } from "vitest";

import { schedulableRounds } from "@/components/recruitment/schedule-interview-dialog";
import type { InterviewRoundOption } from "@/lib/types";

const PRE: InterviewRoundOption = {
  id: "round-pre",
  type: "pre_interview",
  round_number: null,
  status: "open",
};
const FIRST: InterviewRoundOption = {
  id: "round-1",
  type: "interview",
  round_number: 1,
  status: "open",
};
const FINAL: InterviewRoundOption = {
  id: "round-final",
  type: "final",
  round_number: null,
  status: "open",
};

const ALL = [PRE, FIRST, FINAL];

describe("Schedule interview round options (HRP-741)", () => {
  it("drops pre-interview rounds when nothing is selected yet", () => {
    expect(schedulableRounds(ALL, "__none__")).toEqual([FIRST, FINAL]);
  });

  it("keeps the interview and final rounds in their original order", () => {
    expect(schedulableRounds(ALL, "round-1").map((r) => r.id)).toEqual([
      "round-1",
      "round-final",
    ]);
  });

  it("keeps a pre-interview round that the edited interview sits on", () => {
    expect(schedulableRounds(ALL, "round-pre")).toEqual([PRE, FIRST, FINAL]);
  });

  it("still hides other pre-interview rounds while one is selected", () => {
    const otherPre: InterviewRoundOption = { ...PRE, id: "round-pre-2" };
    expect(
      schedulableRounds([...ALL, otherPre], "round-pre").map((r) => r.id),
    ).toEqual(["round-pre", "round-1", "round-final"]);
  });
});
