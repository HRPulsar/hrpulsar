// HRP-665 REDO — once the plan was created, the drawer swapped the
// "Create development plan" button for a bare text link, so the action
// that had just been a button turned into something that reads like body
// copy. The follow-up is the same control in both states: a Button of
// the same size and variant, rendering a Link.
//
// The drawer needs an API round-trip to reach that branch, so this is
// pinned by source-grep like the sibling structural suites.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const SOURCE = readFileSync(
  resolve(__dirname, "../components/talent-market/match-drawer.tsx"),
  "utf8",
);

const FLAT = SOURCE.replace(/\s+/g, " ");

describe("Match drawer development-plan control (HRP-665)", () => {
  it("renders Open development plan as a button, not a text link", () => {
    expect(FLAT).toMatch(
      /<Button size="sm" data-testid="talent-market-match-drawer-plan-link" render=\{<Link href=\{`\/development\/\$\{pdpId\}`\} \/>\}/,
    );
  });

  it("keeps it the same size as the Create button next to it", () => {
    // Both branches are `size="sm"` with the default variant — the
    // complaint was that the two states did not look like one control.
    const create = FLAT.match(
      /<Button size="(\w+)" onClick=\{\(\) => void createPlan\(\)\}/,
    );
    expect(create?.[1]).toBe("sm");
  });

  it("does not dress the plan link up as underlined body text", () => {
    expect(FLAT).not.toContain("text-primary underline-offset-2 hover:underline");
  });
});

describe("Match drawer plan outside the viewer's scope (HRP-856)", () => {
  const PAGE = readFileSync(
    resolve(__dirname, "../app/(dashboard)/talent-market/[id]/page.tsx"),
    "utf8",
  ).replace(/\s+/g, " ");

  it("feeds the drawer the row's own scope flag", () => {
    expect(PAGE).toContain(
      "outOfScope={ card.candidates.find((c) => c.id === drawerCandidateId)?.can_view_profile === false }",
    );
  });

  it("keeps Create inactive and explains why, instead of a 403", () => {
    expect(FLAT).toContain("disabled={creatingPlan || outOfScope}");
    expect(FLAT).toContain('data-testid="talent-market-match-drawer-plan-out-of-scope"');
    expect(FLAT).toContain('t("drawerPlanOutOfScope")');
  });

  it("does not link a plan the viewer cannot open", () => {
    expect(FLAT).toContain("{candidateId && pdpId && !outOfScope && (");
  });
});
