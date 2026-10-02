// HRP-838 — the selects on the vacancy forms (create, edit, Overview
// edit) sat at their content width (`w-fit` is the shared trigger's
// default), so Position / Division / Hiring manager looked like chips
// next to a full-width Title, and a long value grew the trigger out of
// its grid cell. Every field now fills its cell and a long value is cut
// with an ellipsis and carried in full in `title`.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const src = (path: string) =>
  readFileSync(resolve(__dirname, path), "utf8").replace(/\s+/g, " ");

// [surface, source, number of pick lists that carry free-text names
// (position, division, manager) — the employment-type enum stays short]
const SURFACES: [string, string, number][] = [
  ["create/edit form", src("../app/(dashboard)/recruitment/requisitions/_components/VacancyForm.tsx"), 2],
  ["Overview edit", src("../app/(dashboard)/recruitment/requisitions/_components/VacancyOverviewSection.tsx"), 2],
  ["hiring manager", src("../components/recruitment/hiring-manager-select.tsx"), 1],
];

const TRUNCATED_ITEM =
  '[&>span:first-child]:block [&>span:first-child]:truncate';

describe("Vacancy form field widths (HRP-838)", () => {
  for (const [name, source, lists] of SURFACES) {
    it(`${name}: every select trigger fills its cell`, () => {
      const triggers = source.match(/<SelectTrigger\b[^>]*>/g) ?? [];
      expect(triggers.length).toBeGreaterThan(0);
      for (const trigger of triggers) {
        expect(trigger, trigger).toContain('className="w-full"');
      }
    });

    it(`${name}: name lists cut long options with an ellipsis and title them`, () => {
      const items = source.match(/<SelectItem\b[\s\S]*?<\/SelectItem>/g) ?? [];
      const truncated = items.filter((item) => item.includes(TRUNCATED_ITEM));
      expect(truncated.length, name).toBe(lists);
      for (const item of truncated) {
        expect(item, item).toMatch(/title=\{/);
      }
    });
  }

  it("shows the picked position / division / manager truncated with a hover title", () => {
    const [form, overview, manager] = SURFACES.map(([, source]) => source);
    expect(form).toContain('<span className="truncate" title={positionLabel}>');
    expect(form).toContain('<span className="truncate" title={divisionLabel}>');
    expect(overview).toContain('<span className="truncate" title={positionLabel}>');
    expect(overview).toContain('<span className="truncate" title={divisionLabel}>');
    expect(manager).toContain('<span className="truncate" title={selectedLabel}>');
  });

  it("Specializations and Grades fill their cells on both forms", () => {
    for (const [name, source] of SURFACES.slice(0, 2)) {
      const pickers = source.match(/<MultiSelectFilter\b[^>]*>/g) ?? [];
      expect(pickers.length, name).toBe(2);
      for (const picker of pickers) {
        expect(picker, `${name}: ${picker}`).toContain('className="w-full"');
      }
    }
  });
});
