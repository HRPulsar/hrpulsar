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
