import { describe, expect, it } from "vitest";

// HRP-186 REDO §3: "+ New round" must open a confirm dialog whose body
// reads "This will create Interview {N+1}." — i.e. the number must align
// with the highest existing interview round_number, not with the
// rounds.length (pre_interview / final must NOT count).
//
// HRP-372: the tab strip order is part of the same contract — the helpers
// now live in `@/lib/manager-assessment-rounds` so both are pinned against
// the real implementation instead of a copy.

import {
  nextInterviewNumber,
  sortRounds,
  type SortableRound,
} from "@/lib/manager-assessment-rounds";

describe("nextInterviewNumber", () => {
  it("returns 1 when no rounds exist", () => {
    expect(nextInterviewNumber([])).toBe(1);
  });

  it("returns 1 when only pre_interview exists", () => {
    expect(
      nextInterviewNumber([{ type: "pre_interview", round_number: null }]),
    ).toBe(1);
  });

  it("returns 2 after the first interview", () => {
    expect(
      nextInterviewNumber([
        { type: "pre_interview", round_number: null },
        { type: "interview", round_number: 1 },
      ]),
    ).toBe(2);
  });

  it("skips final rounds when computing the next interview number", () => {
    // The spec lets `final` close the loop; new interviews still pick
    // the next integer above the highest interview round_number.
    expect(
      nextInterviewNumber([
        { type: "interview", round_number: 1 },
        { type: "interview", round_number: 2 },
        { type: "final", round_number: null },
      ]),
    ).toBe(3);
  });

  it("returns the highest interview number + 1 even with gaps", () => {
    expect(
      nextInterviewNumber([
        { type: "interview", round_number: 1 },
        { type: "interview", round_number: 3 },
      ]),
    ).toBe(4);
  });
});

describe("sortRounds (HRP-372)", () => {
  const label = (r: SortableRound) =>
    r.type === "interview" ? `interview-${r.round_number}` : r.type;

  it("orders pre-interview, then interviews by number, then final", () => {
    const rounds: SortableRound[] = [
      { type: "final", round_number: null },
      { type: "interview", round_number: 2 },
      { type: "pre_interview", round_number: null },
      { type: "interview", round_number: 1 },
    ];
    expect(sortRounds(rounds).map(label)).toEqual([
      "pre_interview",
      "interview-1",
      "interview-2",
      "final",
    ]);
  });

  it("keeps the order stable when the rows arrive already sorted", () => {
    const rounds: SortableRound[] = [
      { type: "pre_interview", round_number: null },
      { type: "interview", round_number: 1 },
      { type: "interview", round_number: 2 },
      { type: "final", round_number: null },
    ];
    expect(sortRounds(rounds).map(label)).toEqual([
      "pre_interview",
      "interview-1",
      "interview-2",
      "final",
    ]);
  });

  it("places a late-created pre-interview first, not last", () => {
    // The bug report: a Pre-interview added after Interview 1/2 used to
    // land at the end of the strip because the API sorted by created_at.
    const rounds: SortableRound[] = [
      { type: "interview", round_number: 1 },
      { type: "interview", round_number: 2 },
      { type: "pre_interview", round_number: null },
    ];
    expect(sortRounds(rounds)[0]!.type).toBe("pre_interview");
  });

  it("orders interviews numerically, not lexicographically", () => {
    const rounds: SortableRound[] = [
      { type: "interview", round_number: 10 },
      { type: "interview", round_number: 2 },
    ];
    expect(sortRounds(rounds).map((r) => r.round_number)).toEqual([2, 10]);
  });

  it("does not mutate the input array", () => {
    const rounds: SortableRound[] = [
      { type: "final", round_number: null },
      { type: "pre_interview", round_number: null },
    ];
    sortRounds(rounds);
    expect(rounds[0]!.type).toBe("final");
  });

  it("breaks ties on id so repeated renders agree", () => {
    const rounds = [
      { id: "b", type: "interview" as const, round_number: 1 },
      { id: "a", type: "interview" as const, round_number: 1 },
    ];
    expect(sortRounds(rounds).map((r) => r.id)).toEqual(["a", "b"]);
  });
});
