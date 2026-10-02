// HRP-827: the competence catalogue and the dictionaries follow the tenant's
// matrix. Authoring the catalogue is `manage` on competences; deleting from
// it and generating it with AI stay the admin role's on top. The
// dictionaries page opens at `manage` on dictionaries, and every button
// outside the two sections that writes into them reads their row.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const read = (rel: string) => readFileSync(resolve(__dirname, rel), "utf8");
const treePage = read("../app/(dashboard)/competences/page.tsx");
const competencePage = read("../app/(dashboard)/competences/[id]/page.tsx");
const indicatorsEditor = read("../components/competence/indicators-editor.tsx");
const dictionariesPage = read("../app/(dashboard)/dictionaries/page.tsx");
const sidebar = read("../components/sidebar.tsx");
const specList = read("../app/(dashboard)/company/specializations/page.tsx");
const specPage = read("../app/(dashboard)/company/specializations/[id]/page.tsx");
const specAiPage = read("../app/(dashboard)/company/specializations/[id]/ai-generate/page.tsx");
const positionPage = read("../app/(dashboard)/company/positions/[id]/page.tsx");
const positionDialog = read("../components/positions/PositionEditDialog.tsx");
const permissions = read("../hooks/use-permissions.ts");

describe("the competence catalogue follows the section level (HRP-827)", () => {
  it("authors at manage, deletes and generates as admin on top", () => {
    expect(permissions).toContain(
      'canAdministerCompetences: isAdmin && sections.competences === "manage",',
    );
    expect(treePage).toContain('const canManage = canManageSection("competences");');
    // The tree's row menus, drag handles and bulk-add used to render for
    // every viewer.
    expect(treePage.match(/const canEdit = canManageSection\("competences"\);/g)).toHaveLength(2);
    expect(treePage).toContain("{canAdministerCompetences && !group.is_used && (");
    expect(treePage).toMatch(/\{canAdministerCompetences && \(\s*<GenerationStatusButton/);
    expect(competencePage).toContain('const canEditMeta = !isOrigin && canManageSection("competences");');
    expect(competencePage).toMatch(/\{canAdministerCompetences && \(\s*<AiIndicatorsButton/);
    expect(competencePage).not.toContain("canManageCatalogues");
    expect(indicatorsEditor).toMatch(/\{canAdministerCompetences && \(\s*<Button[^>]*?onClick=\{\(\) => openDelete\(ind\)\}/);
  });

  it("opens the dictionaries page and its menu entry at manage", () => {
    expect(dictionariesPage).toContain('<RequireSection code="dictionaries" level="manage">');
    expect(sidebar).toMatch(/href: "\/dictionaries",\s*requireSectionManage: true,/);
  });

  it("reads the written section's row on the company pages", () => {
    expect(specList).toContain('const canDelete = canManageSection("dictionaries");');
    expect(specPage).toContain('const canDelete = canManageSection("dictionaries");');
    expect(specPage).toMatch(/\{canAdministerCompetences && \(\s*<Link\s+href=\{`\/company\/specializations\/\$\{id\}\/ai-generate`\}/);
    expect(specAiPage).toContain('<RequireSection code="competences" level="manage">');
    expect(positionPage).toContain("{showJobProfile && canAdministerCompetences ? (");
    expect(positionDialog).toContain('const canAddSpecialization = canManageSection("dictionaries");');
  });
});
