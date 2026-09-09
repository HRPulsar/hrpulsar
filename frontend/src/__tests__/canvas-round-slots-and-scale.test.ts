// HRP-510 REDO — three things the tester rejected on the fullscreen
// canvas, all of them visible in the page source rather than in a mounted
// tree: the Round selector must list the vacancy's Manager-assessment
// slots instead of a count of interview recordings, the Scale selector
// must name the vacancy's own Assessment scale, and the Candidate column
// must stay on screen while the competences scroll.
//
// Same source-grep idiom as candidate-deep-link-anchor: the page is not
// mounted, the rule is which data each control is built from.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const SOURCE = readFileSync(
  resolve(
    __dirname,
    "../app/(fullscreen)/recruitment/requisitions/[id]/assessments/canvas/page.tsx",
  ),
  "utf8",
);

describe("Canvas Round selector (HRP-510 REDO task 1)", () => {
  it("builds its options from the backend's round slots", () => {
    expect(SOURCE).toMatch(/roundSlots\.map\(\(slot\) => \(/);
    expect(SOURCE).toMatch(/value=\{slot\.key\}/);
  });

  it("no longer counts interview recordings", () => {
    expect(SOURCE).not.toMatch(/round_count/);
  });

  it("labels every slot type through t()", () => {
    for (const key of [
      "canvasRoundPreInterview",
      "canvasRoundInterviewNumber",
      "canvasRoundFinal",
    ]) {
      expect(SOURCE).toContain(key);
    }
  });
});

describe("Canvas Scale selector (HRP-510 REDO task 2)", () => {
  it("names the vacancy scale and its maximum", () => {
    expect(SOURCE).toMatch(/canvasScaleNamed/);
    expect(SOURCE).toMatch(/name: data\.scale_name/);
  });

  it("keeps Points and Percent as the only display modes", () => {
    const options = SOURCE.match(/<option value="(points|percent)">/g) ?? [];
    expect(options).toHaveLength(2);
  });
});

describe("Canvas Candidate column (HRP-510 REDO task 3)", () => {
  it("pins the candidate header and body cells to the left edge", () => {
    const pinned = SOURCE.match(/className="sticky left-0[^"]*"/g) ?? [];
    // One on the header cell, one on every row's candidate cell.
    expect(pinned.length).toBeGreaterThanOrEqual(2);
  });

  it("keeps the competence header row on screen too", () => {
    expect(SOURCE).toMatch(/className="sticky top-0 z-10 min-w-/);
  });
});

describe("Canvas export (HRP-744)", () => {
  it("sends the whole toolbar to the server", () => {
    for (const param of [
      "round,",
      "view,",
      "scale,",
      "only_divergences:",
      "hide_unscored:",
      '"candidates"',
    ]) {
      expect(SOURCE).toContain(param);
    }
  });

  it("asks the API for both formats instead of building CSV in the browser", () => {
    expect(SOURCE).toMatch(/assessment-matrix\/export\.\$\{format\}/);
    // The second copy of the rendering rules is what shipped a CSV with
    // no Total column; it must not come back.
    expect(SOURCE).not.toMatch(/csvSafe|Blob\(/);
  });
});
