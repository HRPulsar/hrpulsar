// Talent Market card detail — two review findings on the candidates table.
//
// HRP-665: the "Development plan" badge linked to /development/<pdp_id> for
// every viewer. A plain candidate on the card has no read access to a
// colleague's plan, so the badge only advertised that the plan exists and
// then 403'd on click. It has to sit behind the same gate as the Appoint
// button and the Match trigger next to it.
//
// HRP-657: the Match cell trigger wraps the chips that carry the numbers
// ("84%", "2 of 3"). An aria-label on that button *replaces* the name
// computed from its content, so a screen reader announced only "open match
// breakdown" and never the figures the button exists to expose.
//
// The page can't be mounted under vitest (no jsdom), so both rules are
// pinned by source-grep, the way HRP-192 REDO pins its tooltip rule.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { storedCandidateStatusWins } from "@/lib/talent-card-types";

const SOURCE = readFileSync(
  resolve(__dirname, "../app/(dashboard)/talent-market/[id]/page.tsx"),
  "utf8",
);

describe("Development plan badge is gated (HRP-665)", () => {
  it("renders only for a manager or the candidate themselves", () => {
    expect(SOURCE).toMatch(/\{c\.pdp_id && \(canManage \|\| c\.is_me\) && \(/);
  });

  it("never renders the plan link on pdp_id alone", () => {
    expect(SOURCE).not.toMatch(/\{c\.pdp_id && \(\s*<Link/);
  });

  it("keeps the badge testid so the e2e spec still finds it", () => {
    expect(SOURCE).toMatch(/data-testid="talent-market-candidate-plan"/);
  });
});

describe("Match trigger keeps its numbers announceable (HRP-657)", () => {
  it("does not override the computed name with an aria-label", () => {
    expect(SOURCE).not.toMatch(/aria-label=\{t\("openMatchBreakdown"\)\}/);
  });

  it("carries the purpose as a visually hidden prefix inside the button", () => {
    expect(SOURCE).toMatch(
      /<span className="sr-only">\{t\("openMatchBreakdown"\)\}<\/span>/,
    );
  });

  it("leaves the trigger testid untouched", () => {
    expect(SOURCE).toMatch(/data-testid=\{`\$\{testIdPrefix\}-match-trigger`\}/);
  });
});

// HRP-734: the status badge says which requirement is short. The wording is
// derived from the live `blocked_by`, so its colour has to come from the same
// place — sourcing the tone from the stored status let a row read "Matched" in
// grey, or "Competencies short" in green, whenever the pool had not been
// recomputed since the last assessment.
describe("Candidate status badge explains the gap (HRP-734)", () => {
  it("takes wording and colour from one helper", () => {
    expect(SOURCE).toMatch(/const badge = candidateStatusBadge\(/);
    expect(SOURCE).toMatch(/className=\{badge\.tone\}/);
    expect(SOURCE).toMatch(/\{badge\.label\}/);
  });

  it("no longer colours the badge from the stored status", () => {
    expect(SOURCE).not.toMatch(
      /className=\{candidateStatusColors\[c\.status\] \|\| ""\}/,
    );
  });

  it("keeps the badge testid so the e2e spec still finds it", () => {
    expect(SOURCE).toMatch(/data-testid="talent-market-candidate-status"/);
  });

  it("can reach every reason wording", () => {
    for (const key of [
      "candidateReasonCompetences",
      "candidateReasonExperience",
      "candidateReasonCompetencesAndExperience",
      "candidateReasonCompetencesMetNoExperience",
    ]) {
      expect(SOURCE).toContain(`t("${key}")`);
    }
  });
});

// HRP-714 follow-up: the "Request development plan" CTA was gated on
// `!c.comp_qualifies`, which the backend hardcodes to false for a card with
// no required competences — so a fully qualified candidate on such a card
// was offered a plan the backend now refuses (409 `tm_plan_request_no_gap`).
// The gate reads the same live `blocked_by` verdict as the status badge, and
// an appointed row has nothing left to ask for.
describe("Request development plan CTA reads the live gap (HRP-714)", () => {
  const cta = SOURCE.slice(
    SOURCE.indexOf("HRP-714: the CTA the auto-reply points at"),
    SOURCE.indexOf('data-testid="talent-market-candidate-request-plan"'),
  );

  it("is hidden when blocked_by is null or empty", () => {
    expect(cta).toMatch(
      /Array\.isArray\(c\.blocked_by\) &&\s*c\.blocked_by\.length > 0 &&/,
    );
    expect(cta).not.toContain("!c.comp_qualifies");
  });

  it("is hidden once the candidate is appointed", () => {
    expect(cta).toMatch(/c\.status !== "appointed" &&/);
  });
});

// HRP-734 follow-up: only `appointed` deferred to the stored status, so a
// legacy `rejected` / `responded` / `nominated` row with nothing blocking it
// was relabelled "Matched". Those statuses carry a decision the matcher
// never made; the matcher's own words stay live.
describe("Stored status wins over the live verdict (HRP-734)", () => {
  it("for the terminal and the legacy statuses", () => {
    for (const status of ["appointed", "nominated", "rejected", "responded"]) {
      expect(storedCandidateStatusWins(status), status).toBe(true);
    }
  });

  it("never for the matcher's own statuses", () => {
    for (const status of ["matched", "not_matched", "pending"]) {
      expect(storedCandidateStatusWins(status), status).toBe(false);
    }
  });

  it("is what the page's badge helper consults, after the no-verdict case", () => {
    expect(SOURCE).toMatch(
      /if \(blockedBy == null \|\| storedCandidateStatusWins\(status\)\)/,
    );
  });
});
