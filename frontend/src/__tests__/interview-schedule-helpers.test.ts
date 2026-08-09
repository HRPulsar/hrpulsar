import { describe, expect, it } from "vitest";
import {
  joinLocalDateTime,
  labelForAssessmentRound,
  splitLocalDateTime,
} from "@/lib/recruitment-helpers";

// HRP-476 convention: the stub echoes the key back and records the values,
// so the tests pin the i18n contract instead of the English wording.
let lastValues: Record<string, string | number> | undefined;
const t = (key: string, values?: Record<string, string | number>): string => {
  lastValues = values;
  return key;
};

describe("labelForAssessmentRound (HRP-386)", () => {
  it("names the three round kinds with the Manager-assessment keys", () => {
    expect(
      labelForAssessmentRound(t, { type: "pre_interview", round_number: null }),
    ).toBe("managerAssessmentRoundPreInterview");
    expect(
      labelForAssessmentRound(t, { type: "final", round_number: null }),
    ).toBe("managerAssessmentRoundFinal");
    expect(
      labelForAssessmentRound(t, { type: "interview", round_number: 2 }),
    ).toBe("managerAssessmentRoundInterview");
    expect(lastValues).toEqual({ number: 2 });
  });

  it("falls back to a placeholder when the round number is missing", () => {
    labelForAssessmentRound(t, { type: "interview", round_number: null });
    expect(lastValues).toEqual({ number: "?" });
  });
});

describe("splitLocalDateTime / joinLocalDateTime (HRP-386)", () => {
  it("round-trips a local wall-clock slot", () => {
    const iso = new Date(2026, 4, 28, 14, 30).toISOString();
    const split = splitLocalDateTime(iso);
    expect(split).toEqual({ date: "2026-05-28", time: "14:30" });
    expect(joinLocalDateTime(split.date, split.time)).toBe(iso);
  });

  it("treats an empty / invalid timestamp as unset", () => {
    expect(splitLocalDateTime(null)).toEqual({ date: "", time: "" });
    expect(splitLocalDateTime("not-a-date")).toEqual({ date: "", time: "" });
  });

  it("returns null when no date was picked", () => {
    expect(joinLocalDateTime("", "10:00")).toBeNull();
  });

  it("defaults a missing time to local midnight", () => {
    expect(joinLocalDateTime("2026-05-28", "")).toBe(
      new Date(2026, 4, 28, 0, 0).toISOString(),
    );
  });
});
