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

// HRP-579 (b): the autosave state was left behind by the same switch —
// the previous vacancy's "Saving… / Saved" finished playing under the new
// one, and its armed PATCHes fired minutes into the new sheet's session.
describe("Manager assessment — vacancy switch resets autosave (HRP-579)", () => {
  const effect = FLAT.indexOf("if (!activeCvId) return;");
  const load = FLAT.indexOf("void loadRounds(activeCvId);");
  const body = FLAT.slice(effect, load);

  it("disarms the debounced saves before loading the new vacancy", () => {
    expect(effect).toBeGreaterThan(-1);
    expect(body).toContain("clearTimeout(pending.timer);");
    expect(body).toContain("debounceTimers.current.clear();");
    expect(body).toContain("pendingSaves.current = 0;");
  });

  it("flushes them instead of dropping the evaluator's last edit", () => {
    // The armed closure carries the old sheet's id, so firing it now still
    // writes where the edit was made — dropping it would lose whatever
    // happened inside the 1.5 s debounce window.
    expect(body).toContain("void pending.run()");
  });

  it("resets the indicator so it cannot play under the new vacancy", () => {
    expect(body).toContain('setSavingState("idle");');
    expect(body).toContain("clearTimeout(savedResetTimer.current);");
    expect(body).toContain("savedResetTimer.current = null;");
  });
});
