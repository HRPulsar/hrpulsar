// HRP-370 (REDO): the autosave indicator used to be a block-level div of
// its own directly above the scoring sheet. Its text appears and clears on
// every save, so the whole sheet nudged down and back — QA's "the layout
// jumps". It now sits inline in the empty left slot of the evaluators
// row, whose height is already settled by the avatars next to it.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const SOURCE = readFileSync(
  resolve(__dirname, "../components/recruitment/manager-assessment-section.tsx"),
  "utf8",
);
const FLAT = SOURCE.replace(/\s+/g, " ");

describe("Manager assessment autosave placement (HRP-370)", () => {
  it("keeps the indicator's testid so the public sheet and this one agree", () => {
    expect(FLAT).toContain('data-testid="assessment-autosave-status"');
    expect(FLAT).toContain('aria-live="polite"');
  });

  it("renders it inline, not as a standalone block above the sheet", () => {
    expect(FLAT).toContain(
      '<span aria-live="polite" className="text-xs text-muted-foreground" data-testid="assessment-autosave-status"',
    );
    expect(FLAT).not.toContain(
      '{/* Autosave indicator */} <div aria-live="polite"',
    );
  });

  it("puts it inside the evaluators row, after the row opens", () => {
    const evaluatorsRow = FLAT.indexOf('data-testid="assessment-round-evaluators"');
    const indicator = FLAT.indexOf('data-testid="assessment-autosave-status"');
    expect(evaluatorsRow).toBeGreaterThan(-1);
    expect(indicator).toBeGreaterThan(evaluatorsRow);
  });

  it("reserves the row height so an empty state does not collapse it", () => {
    expect(FLAT).toContain('<div className="flex min-h-6 items-center gap-2">');
  });

  it("still shows both saving and saved states", () => {
    expect(FLAT).toContain('t("managerAssessmentSaving")');
    expect(FLAT).toContain('t("managerAssessmentSaved")');
  });
});
