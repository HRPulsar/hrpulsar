// HRP-823: the exams page is two pages behind one menu entry - the mass
// exams for whoever runs the section, one's own exams for everyone else.
// Which one renders comes from the tenant's matrix now, so a role the
// tenant raised to `manage` gets the manager view without a role change,
// and a role it lowered keeps the exams already assigned to it. QA 26.10:
// admin, hr and manager read the mass exams at `view` too, read-only.

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
    // The mass exams' tab ahead of one's own two: at `manage`, and at
    // `view` for whoever reads the section's list; its writes at `manage`.
    expect(examsPage).toContain('const manage = canManageSection("exams");');
    expect(examsPage).toContain('const lists = readsSectionList("exams");');
    expect(examsPage).toContain('useSectionTab(lists ? ["all", "mine", "todo"] : ["mine", "todo"])');
    expect(examsPage).toContain("return <ManagerExamsView tabs={tabs} manage={manage} />;");
    expect(examsPage).toMatch(/\{manage && \(\s*<Button size="sm" onClick=\{\(\) => setCreateOpen\(true\)\}/);
    expect(examsPage).toContain("{manage && !isTerminalStatus(e.status) && (");
    expect(examsPage).not.toMatch(/\bcanManage\b(?!Section)/);
  });

  it("opens the mass exam's own page to a list reader, read-only below manage", () => {
    // Every call on that page is a /mass-exams one; the layout's gate only
    // knows the section, so the page states the level itself.
    expect(massExamPage).toContain('level={readsSectionList("exams") ? "view" : "manage"}');
    expect(massExamPage).toContain("const canEditMeta = manage && !isTerminal;");
    expect(massExamPage).toContain('const canEditQuestions = manage && exam.status === "draft";');
    expect(massExamPage).toContain("{manage && actionButtons.map((btn) => (");
    expect(massExamPage).toContain('{manage && exam.status === "draft" && (');
  });

  it("falls back to one's own exams rather than to nothing", () => {
    // No gate of its own: the page sits outside the section gate (see
    // lib/sections.ts), so `none` lands here too.
    expect(examsPage).toContain("return <EmployeeExamsView key={tab} tab={tab} tabs={tabs} onChanged={todo.reload} />;");
  });
});
