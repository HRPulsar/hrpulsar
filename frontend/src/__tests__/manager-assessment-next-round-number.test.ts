import { describe, expect, it } from "vitest";

// HRP-186 REDO §3: "+ New round" must open a confirm dialog whose body
// reads "This will create Interview {N+1}." — i.e. the number must align
// with the highest existing interview round_number, not with the
// rounds.length (pre_interview / final must NOT count). The pure helper
// is duplicated here so we can pin the contract without spinning up
// jsdom for the whole section.

type RoundType = "pre_interview" | "interview" | "final";
interface RoundFixture {
  type: RoundType;
  round_number: number | null;
}

function nextInterviewNumber(rounds: RoundFixture[]): number {
  const highest = rounds
    .filter((r) => r.type === "interview" && r.round_number !== null)
    .reduce((acc, r) => Math.max(acc, r.round_number ?? 0), 0);
  return highest + 1;
}

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
