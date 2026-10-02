import { describe, expect, it } from "vitest";
import { splitDuration } from "@/lib/date-format";

describe("splitDuration", () => {
  it("rounds to seconds and splits minutes", () => {
    expect(splitDuration(48_400)).toEqual({ minutes: 0, seconds: 48 });
    expect(splitDuration(130_000)).toEqual({ minutes: 2, seconds: 10 });
    expect(splitDuration(-5)).toEqual({ minutes: 0, seconds: 0 });
  });
});
