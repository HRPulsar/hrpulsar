// HRP-828: the org chart follows the tenant's matrix. Shaping divisions and
// authoring positions is `manage` on company, inside the caller's subtree;
// a top-level division and a position with no division are admin-level
// only. The specialization ladder and matrices stay admin/hr by role, the
// grade system and deletes stay the admin role's.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { holdsAdminLevel } from "@/lib/user-role-label";

const read = (rel: string) => readFileSync(resolve(__dirname, rel), "utf8");
const companyPage = read("../app/(dashboard)/company/page.tsx");
const divisionPage = read("../app/(dashboard)/company/divisions/[id]/page.tsx");
const positionsPage = read("../app/(dashboard)/company/positions/page.tsx");
const positionPage = read("../app/(dashboard)/company/positions/[id]/page.tsx");
const positionDialog = read("../components/positions/PositionEditDialog.tsx");
const combobox = read("../components/position-combobox.tsx");
const specList = read("../app/(dashboard)/company/specializations/page.tsx");
const gradeForm = read("../components/specialization/grade-attributes-form.tsx");
const permissions = read("../hooks/use-permissions.ts");

describe("the org chart follows the section level (HRP-828)", () => {
  it("edits divisions at manage, inside the subtree", () => {
    expect(permissions).toContain("isAdminLevel: holdsAdminLevel(roles),");
    // HRP-829: one helper mirrors ADMIN_ROLE_CODES for the caller and for
    // the person on a card alike.
    for (const code of ["admin", "hr", "platform_admin"]) {
      expect(holdsAdminLevel(["employee", code])).toBe(true);
    }
    expect(holdsAdminLevel(["manager", "recruiter", "hiring_manager", "employee"])).toBe(false);
    expect(holdsAdminLevel(undefined)).toBe(false);
    expect(companyPage).toContain('const managesChart = canManageSection("company");');
    expect(companyPage).toMatch(/managesChart && \(isAdmin \|\| editableIds\.has\(id\)\)/);
    expect(companyPage).toContain("const canAddRootDivision = managesChart && isAdminLevel;");
    expect(companyPage).toMatch(/\{canAddRootDivision && \(\s*<Button data-testid="company-divisions-btn-add"/);
    // Deleting stays the admin role's.
    expect(companyPage).toContain("canDelete={isAdmin}");
    expect(divisionPage).toMatch(/canManageSection\("company"\) && \(isAdmin \|\| inWriteScope\)/);
  });

  it("authors positions at manage, per row", () => {
    expect(positionsPage).toContain('const canManage = canManageSection("company");');
    expect(positionPage).toMatch(/canManageSection\("company"\) && position\.can_manage !== false/);
    // The inline grade also chains it into the grade system - admin only.
    expect(positionDialog).toContain("const canAddGrade = canAddSpecialization && isAdmin;");
    // The AI drafts card used to render approve/reject to every viewer, and
    // the row menu a Delete the admin role alone may use.
    expect(positionsPage).toContain('.filter((p) => p.source === "ai_draft" && canEdit(p))');
    expect(positionsPage).toContain("{drafts.some(canEdit) && (");
    expect(positionsPage).toMatch(/\{canEdit\(pos\) && \(\s*<div className="flex gap-1">\s*<Button\s+data-testid=\{`positions-row-\$\{pos\.id\}-btn-approve`\}/);
    expect(positionsPage).toContain("{isAdmin && pos.employee_count === 0 && (");
  });

  it("keeps the grade attributes the admin role's - they live on the grade chain", () => {
    expect(gradeForm).toContain("const readOnly = !isAdmin;");
    expect(gradeForm).toMatch(/\{readOnly \? null : \(\s*<Button\s+data-testid=\{`specialization-grade-form-\$\{grade\.id\}-btn-save`\}/);
  });

  it("offers quick-create in the picker only to who may file a position with no division", () => {
    expect(combobox).toContain(
      'const canCreate = allowCreate && canManageSection("company") && isAdminLevel;',
    );
    expect(combobox).toContain("{canCreate && (");
  });

  it("opens the specialization row menu for either of its items", () => {
    expect(specList).toContain("const hasRowMenu = canManage || canDelete;");
    expect(specList).toMatch(/\{canManage && \(\s*<DropdownMenuItem\s+onClick=\{\(\) => openManageGrades\(spec\)\}/);
  });
});
