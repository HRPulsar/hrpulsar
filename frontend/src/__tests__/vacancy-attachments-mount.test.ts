// HRP-846 — the attachments widget (context files for the AI profile
// prompt) fell off the vacancy page in the HRP-180 single-page redesign
// while its API, billing entries and prompt wiring stayed alive. It is
// mounted again above the competences / profile card, read-only once the
// vacancy is archived or closed like every other section.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const PAGE = readFileSync(
  resolve(__dirname, "../app/(dashboard)/recruitment/requisitions/[id]/page.tsx"),
  "utf8",
).replace(/\s+/g, " ");

describe("Vacancy attachments widget (HRP-846)", () => {
  it("is mounted on the vacancy page above the competences section", () => {
    expect(PAGE).toContain(
      'import { VacancyAttachments } from "@/components/recruitment/vacancy-attachments";',
    );
    const widget = PAGE.indexOf("<VacancyAttachments vacancyId={id} canEdit={canEdit} />");
    expect(widget).toBeGreaterThan(-1);
    // Upload/delete ask `manage` on recruitment, like editing the vacancy
    // (HRP-830) - a reader gets the block read-only.
    expect(PAGE).toContain('const canEdit = canManageSection("recruitment") &&');
    expect(widget).toBeLessThan(PAGE.indexOf("<VacancyCompetencesSection"));
  });
});
