// HRP-329 REDO: while a calibration is running (or after one was saved)
// the questionnaire is closed server-side. The buttons used to be hidden
// outright, which left the user with no explanation. They must now render
// disabled with a tooltip naming the state — two distinct texts for
// "is calibrating" vs "was calibrated". Draft / terminal / no-criteria
// still hide the actions: there is nothing to explain there.
//
// The page can't be mounted under vitest (no jsdom + heavy data deps), so
// the rules are pinned by source-grep, as with the sibling gate tests.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const SOURCE = readFileSync(
  resolve(__dirname, "../app/(dashboard)/assessments/[id]/page.tsx"),
  "utf8",
);

const EN = JSON.parse(
  readFileSync(resolve(__dirname, "../../messages/en.json"), "utf8"),
);
const DE = JSON.parse(
  readFileSync(resolve(__dirname, "../../messages/de.json"), "utf8"),
);

describe("Assessment calibration lock (HRP-329)", () => {
  it("no longer folds the calibration lock into the visibility gate", () => {
    expect(SOURCE.replace(/\s+/g, " ")).toContain(
      "const showEvaluateActions = !isTerminal && !isDraft && assessment.competence_ids.length > 0;",
    );
    // The old gate hid the buttons on a calibration lock — it must be gone.
    expect(SOURCE).not.toMatch(/const canEvaluateAnyone =/);
  });

  it("derives two distinct tooltip texts from the two calibration states", () => {
    expect(SOURCE).toMatch(
      /const calibrationLockHint = assessment\.calibration_in_progress/,
    );
    expect(SOURCE).toMatch(/t\("calibrationLockCalibrating"\)/);
    expect(SOURCE).toMatch(/assessment\.has_calibrated_totals/);
    expect(SOURCE).toMatch(/t\("calibrationLockCalibrated"\)/);
  });

  // Whitespace-insensitive: these assertions must survive a Prettier pass.
  const FLAT = SOURCE.replace(/\s+/g, " ");

  it("renders the Take CTA disabled behind a tooltip when locked", () => {
    expect(FLAT).toContain("showEvaluateActions && myFirstPending &&");
    expect(FLAT).toMatch(
      /data-testid="assessment-take-cta"[^>]*disabled|disabled[^>]*data-testid="assessment-take-cta"/,
    );
  });

  it("renders the per-row Evaluate disabled behind a tooltip when locked", () => {
    expect(FLAT).toContain("showEvaluate && (calibrationLockHint ?");
    expect(FLAT).toMatch(
      /data-testid=\{`assessment-participant-\$\{p\.id\}-evaluate`\}[^>]*disabled/,
    );
  });

  it("wraps the disabled buttons in a span trigger (pointer-events)", () => {
    // A disabled button emits no pointer events, so the tooltip trigger
    // must be the wrapping span, not the button itself.
    expect(FLAT).toContain("<TooltipTrigger");
    expect(FLAT).toMatch(/render=\{ ?<span tabIndex=\{-1\} className="inline-flex" \/>/);
    expect(FLAT).toContain("<TooltipContent>{calibrationLockHint}</TooltipContent>");
  });

  it("keeps the per-row Evaluate gated on the row being the viewer's own", () => {
    expect(FLAT).toContain(
      "const showEvaluate = showEvaluateActions && !p.is_completed && isMine;",
    );
  });

  it("ships both tooltip texts in en and de", () => {
    expect(EN.assessments.calibrationLockCalibrating).toBe(
      "Assessment results are calibrating; the questionnaire is closed",
    );
    expect(EN.assessments.calibrationLockCalibrated).toBe(
      "Assessment results were calibrated; the questionnaire is closed",
    );
    expect(DE.assessments.calibrationLockCalibrating).toBeTruthy();
    expect(DE.assessments.calibrationLockCalibrated).toBeTruthy();
  });
});
