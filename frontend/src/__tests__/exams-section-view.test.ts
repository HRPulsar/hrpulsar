// HRP-823: the exams page is two pages behind one menu entry - the mass
// exams for whoever runs the section, one's own exams for everyone else.
// Which one renders comes from the tenant's matrix now, so a role the
// tenant raised to `manage` gets the manager view without a role change,
// and a role it lowered keeps the exams already assigned to it.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const examsPage = readFileSync(
  resolve(__dirname, "../app/(dashboard)/exams/page.tsx"),
  "utf8",
);
const massExamPage = readFileSync(
  resolve(__dirname, "../app/(dashboard)/exams/[id]/page.tsx"),
  "utf8",
);

describe("the two views of the exams section (HRP-823)", () => {
  it("picks the manager view by the section level, not by a role flag", () => {
    // QA 13.10: `manage` adds the mass exams' tab ahead of one's own two.
    expect(examsPage).toContain('const manage = canManageSection("exams");');
    expect(examsPage).toContain('useSectionTab(manage ? ["all", "mine", "todo"] : ["mine", "todo"])');
    expect(examsPage).toContain("return <ManagerExamsView tabs={tabs} />;");
    expect(examsPage).not.toMatch(/\bcanManage\b(?!Section)/);
  });

  it("opens the mass exam's own page at manage, not at view", () => {
    // Every call on that page is a /mass-exams one; the layout's gate only
    // knows the section, so the page states the level itself.
    expect(massExamPage).toContain('<RequireSection code="exams" level="manage">');
  });

  it("falls back to one's own exams rather than to nothing", () => {
    // No gate of its own: the page sits outside the section gate (see
    // lib/sections.ts), so `none` lands here too.
    expect(examsPage).toContain("return <EmployeeExamsView key={tab} tab={tab} tabs={tabs} onChanged={todo.reload} />;");
  });
});
