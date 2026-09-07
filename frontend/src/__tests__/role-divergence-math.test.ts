// HRP-715: the divergence block picks its reference side itself, so pin
// which side that is and how the columns get ordered.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import {
  comparedToManager,
  orderRoles,
  overallDelta,
  selfDelta,
} from "@/components/assessment/role-divergence-math";

describe("selfDelta", () => {
  it("compares self against the manager on a 180°", () => {
    expect(selfDelta({ self: 80, manager: 62 })).toBe(18);
    expect(selfDelta({ self: 55, manager: 71 })).toBe(-16);
    expect(selfDelta({ self: 70, manager: 70 })).toBe(0);
  });

  it("still uses the manager when peers and subordinates answered too", () => {
    // Peers at 100 must not soften a 20 pp gap to the manager.
    expect(selfDelta({ self: 80, manager: 60, peer: 100, subordinate: 100 })).toBe(
      20,
    );
  });

  it("falls back to the average of the other raters without a manager", () => {
    expect(selfDelta({ self: 80, peer: 60, subordinate: 50 })).toBe(25);
  });

  it("has nothing to compare for a lone self", () => {
    expect(selfDelta({ self: 80 })).toBeNull();
    expect(selfDelta({ manager: 80 })).toBeNull();
    expect(selfDelta({})).toBeNull();
  });
});

describe("orderRoles", () => {
  it("puts the spec roles first and anything custom last, alphabetically", () => {
    expect(orderRoles(["subordinate", "manager", "external", "self", "peer"])).toEqual(
      ["self", "manager", "peer", "subordinate", "external"],
    );
    expect(orderRoles(["zeta", "external", "self"])).toEqual([
      "self",
      "external",
      "zeta",
    ]);
  });
});

describe("overallDelta", () => {
  it("averages the per-competence deltas, not the per-role averages", () => {
    // Review case: the manager answered "Don't know" on B, so the backend's
    // role_percents_overall is self (90+30)/2 = 60 against manager 90 — a
    // 30 pp headline gap on competences that actually agree.
    const rows: Record<string, number>[] = [
      { self: 90, manager: 90 },
      { self: 30 },
    ];
    expect(overallDelta(rows)).toBe(0);
  });

  it("averages the rows that do have both sides", () => {
    expect(overallDelta([{ self: 80, manager: 60 }, { self: 50, manager: 60 }])).toBe(
      5,
    );
  });

  it("has no headline when no competence has both sides", () => {
    expect(overallDelta([{ self: 80 }, { manager: 60 }])).toBeNull();
    expect(overallDelta([])).toBeNull();
  });
});

describe("comparedToManager", () => {
  it("is true when every row with a delta had a manager value", () => {
    expect(
      comparedToManager([
        { self: 80, manager: 60 },
        { self: 50, manager: 60, peer: 90 },
      ]),
    ).toBe(true);
  });

  it("is false when any row's delta came from the peer fallback", () => {
    // The headline is then partly built from peers, so "vs manager" would
    // describe a number the manager never fully produced.
    expect(
      comparedToManager([
        { self: 80, manager: 60 },
        { self: 50, peer: 60 },
      ]),
    ).toBe(false);
  });

  it("ignores rows that contributed no delta", () => {
    expect(
      comparedToManager([{ self: 80, manager: 60 }, { self: 50 }, { peer: 70 }]),
    ).toBe(true);
  });
});

// The block needs live data plus next-intl to mount, so the two render rules
// that carry meaning are pinned by source-grep — same approach as
// assessment-detail-results-gate.test.ts.
const SOURCE = readFileSync(
  resolve(__dirname, "../components/assessment/assessment-role-divergence.tsx"),
  "utf8",
);

describe("AssessmentRoleDivergence render rules", () => {
  it("renders nothing for a self-assessment (fewer than two roles)", () => {
    expect(SOURCE).toMatch(
      /if \(!visible \|\| roles\.length < 2 \|\| overallDelta === null\) return null;/,
    );
  });

  it("picks the manager wording from the rows, not from the overall averages", () => {
    expect(SOURCE).not.toMatch(/"manager" in overall/);
    expect(SOURCE).toMatch(/comparedToManager\(/);
  });

  it("switches to the amber tone at 15 pp, on both the row and the headline", () => {
    expect(SOURCE).toMatch(/const AMBER_THRESHOLD = 15;/);
    expect(SOURCE).toMatch(/Math\.abs\(rowDelta\) >= AMBER_THRESHOLD/);
    expect(SOURCE).toMatch(/points >= AMBER_THRESHOLD/);
  });
});
