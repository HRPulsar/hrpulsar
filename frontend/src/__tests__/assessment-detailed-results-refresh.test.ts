// HRP-185 REDO #3: when calibration is cancelled from the "post-Save"
// state (admin sees a Cancel calibration button outside of edit mode),
// `calibrationInProgress` was already false, so the dep array on the
// fetch effect didn't refire — Detailed results kept rendering the
// calibrated numbers until F5. The fix bumps a refreshKey on every
// save / cancel and adds it to the effect deps so the data always
// refetches.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const SOURCE = readFileSync(
  resolve(
    __dirname,
    "../components/assessment/assessment-detailed-results.tsx",
  ),
  "utf8",
);

describe("Detailed results — calibration refresh (HRP-185 REDO #3)", () => {
  it("declares a refreshKey counter", () => {
    expect(SOURCE).toMatch(
      /const \[refreshKey, setRefreshKey\] = useState\(0\);/,
    );
  });

  it("includes refreshKey in the fetch effect deps", () => {
    expect(SOURCE).toMatch(
      /\[assessmentId, visible, calibrationInProgress, refreshKey\]/,
    );
  });

  it("bumps the counter inside both saveCalibration and cancelCalibration", () => {
    // Two occurrences — one in save, one in cancel.
    const matches = SOURCE.match(/setRefreshKey\(\(k\) => k \+ 1\);/g) ?? [];
    expect(matches.length).toBe(2);
  });
});
