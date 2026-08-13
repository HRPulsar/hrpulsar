// HRP-550: switching the candidate card to a vacancy that has no
// assessment rounds left the previous vacancy's round selected. The sheet
// stayed on screen under the new vacancy's header, and its autosave kept
// PATCHing into the round the recruiter had already navigated away from.
//
// Structural test: the component owns a full data layer (rounds, sheets,
// aggregates, debounced autosave), so the reset contract is pinned by
// source-grep like its siblings.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const SOURCE = readFileSync(
  resolve(__dirname, "../components/recruitment/manager-assessment-section.tsx"),
  "utf8",
);
const FLAT = SOURCE.replace(/\s+/g, " ");

describe("Manager assessment — vacancy switch resets the sheet (HRP-550)", () => {
  it("drops the round selection when the new vacancy has none", () => {
    expect(FLAT).toContain("} else if (rows.length === 0) {");
    expect(FLAT).toContain("selectRound(null);");
  });

  it("clears the sheet and the aggregate when no round is selected", () => {
    // Match code only — asserting comment prose makes a reword a failure.
    expect(FLAT).toContain("if (!activeRoundId) {");
    const guard = FLAT.indexOf("if (!activeRoundId) {");
    const ensure = FLAT.indexOf("void ensureSheet(activeRoundId);");
    expect(guard).toBeGreaterThan(-1);
    // The reset happens before the early return, not after the fetch.
    expect(FLAT.slice(guard, ensure)).toContain("setSheet(null);");
    expect(FLAT.slice(guard, ensure)).toContain("setAggregate(null);");
  });

  it("resets the selection on the failure path too", () => {
    // A failed round fetch used to clear the list but keep the previous
    // vacancy's round selected — same bug as the empty case, one branch over.
    const failure = FLAT.indexOf("} catch { ");
    const finallyAt = FLAT.indexOf("} finally {", failure);
    expect(failure).toBeGreaterThan(-1);
    expect(finallyAt).toBeGreaterThan(failure);
    const catchBody = FLAT.slice(failure, finallyAt);
    expect(catchBody).toContain("setRounds([]);");
    expect(catchBody).toContain("selectRound(null);");
  });

  it("closes the external-submission drawer on a vacancy switch", () => {
    const effect = FLAT.indexOf("if (!activeCvId) return;");
    const load = FLAT.indexOf("void loadRounds(activeCvId);");
    expect(effect).toBeGreaterThan(-1);
    expect(FLAT.slice(effect, load)).toContain("setViewingInvite(null);");
  });
});
