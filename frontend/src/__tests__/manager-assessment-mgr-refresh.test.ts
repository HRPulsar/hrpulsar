// HRP-812: the Mgr value in the candidate page's Vacancy applications block
// comes from the candidate card, while the scores that move it are written
// by the Manager assessments block. The block now reports every such write
// upward and the page re-reads the card — the value follows without F5.
//
// Mounting the block needs the whole card's data layer, so the contract is
// pinned by source-grep, as the sibling structural tests do.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const SECTION = readFileSync(
  resolve(__dirname, "../components/recruitment/manager-assessment-section.tsx"),
  "utf8",
).replace(/\s+/g, " ");

const PAGE = readFileSync(
  resolve(__dirname, "../app/(dashboard)/recruitment/candidates/[id]/page.tsx"),
  "utf8",
).replace(/\s+/g, " ");

const FIRE = "onScoresChangedRef.current?.();";

describe("Manager score refresh on the candidate page (HRP-812)", () => {
  it("exposes onScoresChanged and reads it through a ref, so memoised autosaves never go stale", () => {
    expect(SECTION).toContain("onScoresChanged?: () => void;");
    expect(SECTION).toContain("const onScoresChangedRef = useRef(onScoresChanged);");
  });

  it("fires after a competence or indicator score is saved, once the aggregate is re-read", () => {
    expect(SECTION).toContain(`await loadAggregate(roundId); ${FIRE}`);
    expect(SECTION).toContain(`await loadAggregate(sheet.round_id); ${FIRE}`);
  });

  it("fires for every round action, before the active-tab guard", () => {
    const action = SECTION.indexOf("toast.success(t(ROUND_ACTION_TOASTS[action]));");
    const fire = SECTION.indexOf(FIRE, action);
    const guard = SECTION.indexOf(
      "if (activeRoundIdRef.current !== roundId) return;",
      action,
    );
    expect(action).toBeGreaterThan(-1);
    expect(fire).toBeGreaterThan(action);
    expect(fire).toBeLessThan(guard);
  });

  it("fires when an invitation changes, together with the header average", () => {
    expect(SECTION).toContain(
      `if (activeRoundId) void loadAggregate(activeRoundId); ${FIRE} }}`,
    );
  });

  it("is answered by the page re-reading the candidate card", () => {
    expect(PAGE).toContain("onScoresChanged={() => void load()}");
  });

  it("does not turn that re-read into a vacancy/scales/profile refetch", () => {
    // The card re-read rebuilds the vacancy options with new identities;
    // the loader must key on the vacancy id, never on the option object.
    expect(SECTION).toContain("const activeVacancyId = activeVacancy?.vacancy_id;");
    expect(SECTION).toContain("}, [activeVacancyId]);");
    expect(SECTION).not.toContain("}, [activeVacancy]);");
  });
});

describe("Manager assessments deep link from the submitted-assessment email (HRP-379)", () => {
  it("carries the anchor the email points at", () => {
    expect(SECTION).toContain('id="manager-assessments"');
  });

  it("scrolls itself into view once the linked round tab is selected", () => {
    expect(SECTION).toContain(
      'if (window.location.hash !== "#manager-assessments") return;',
    );
    const hashCheck = SECTION.indexOf(
      'if (window.location.hash !== "#manager-assessments") return;',
    );
    const scroll = SECTION.indexOf("sectionRef.current?.scrollIntoView({", hashCheck);
    const deps = SECTION.indexOf("}, [activeRoundId]);", scroll);
    expect(scroll).toBeGreaterThan(hashCheck);
    expect(deps).toBeGreaterThan(scroll);
  });

  it("is left alone by the page-level anchor jump, which would fire too early", () => {
    expect(PAGE).toContain('if (anchorId === "manager-assessments") return;');
  });
});
