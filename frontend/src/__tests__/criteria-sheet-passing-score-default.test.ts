// HRP-183 REDO #2: re-opening the Evaluation criteria sheet must show the
// previously saved passing_score, not the hard-coded default. The sheet still
// falls back to 75 when nothing was saved yet, and the grade-default useEffect
// is gated behind passingScoreTouched so an explicit saved value survives.
//
// vitest runs without jsdom, so we can't mount the React component to observe
// the input value directly. Instead we pin the rule by reading the source.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const SOURCE = readFileSync(
  resolve(__dirname, "../components/assessment/criteria-sheet.tsx"),
  "utf8",
);

describe("criteria-sheet passing_score (HRP-183 REDO)", () => {
  it("declares the default constant at 75", () => {
    expect(SOURCE).toMatch(/const DEFAULT_PASSING_SCORE = 75;/);
  });

  it("seeds useState from initial.passing_score when present", () => {
    expect(SOURCE).toMatch(
      /useState<string>\(\s*initial\.passing_score != null\s*\?\s*String\(initial\.passing_score\)\s*:\s*String\(DEFAULT_PASSING_SCORE\),?\s*\)/,
    );
  });

  it("marks passingScoreTouched as true when initial.passing_score was persisted", () => {
    expect(SOURCE).toMatch(
      /useState\(\s*initial\.passing_score != null,?\s*\)/,
    );
  });
});
