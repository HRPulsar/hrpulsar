// HRP-840 — Back on a candidate card opened from the Candidates list went
// to the vacancies list. The card has two ways in: from a vacancy (the
// link carries `vacancyId`, Back returns to that vacancy — HRP-181, kept)
// and from anywhere else (Candidates list, search), where Back returns to
// the Candidates list. The origin travels in the URL, never via
// history.back(), so a reload or a shared link behaves the same.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const src = (path: string) =>
  readFileSync(resolve(__dirname, path), "utf8").replace(/\s+/g, " ");

const CARD = src("../app/(dashboard)/recruitment/candidates/[id]/page.tsx");

describe("Candidate card Back target (HRP-840)", () => {
  it("returns to the vacancy when opened from one, else to the Candidates list", () => {
    expect(CARD).toContain(
      'const backHref = vacancyContextId ? `/recruitment/requisitions/${vacancyContextId}` : "/recruitment/candidates";',
    );
    expect(CARD).not.toContain("router.back()");
  });

  it("every way in from a vacancy carries the vacancy context", () => {
    // Links that live on the vacancy page and open a candidate card.
    const fromVacancy = [
      src("../app/(dashboard)/recruitment/requisitions/_components/VacancyCandidatesSection.tsx"),
      src("../components/recruitment/internal-candidates-block.tsx"),
      src("../components/recruitment/vacancy-candidates-table.tsx"),
      src("../app/(dashboard)/recruitment/requisitions/[id]/compare/page.tsx"),
    ];
    for (const source of fromVacancy) {
      const links = source.match(/\/recruitment\/candidates\/\$\{[^`]*`/g) ?? [];
      expect(links.length).toBeGreaterThan(0);
      for (const link of links) {
        expect(link).toContain("?vacancyId=");
      }
    }
  });
});
