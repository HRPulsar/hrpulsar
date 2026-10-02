// HRP-831: the admin block - import, invitations, roles, AI settings -
// follows the tenant's matrix. Each entry and page opens at `view`, the
// writes ask for `manage`, and the role flag the four kept on top of the
// matrix is gone. Invitations narrow by org structure below the admin
// level (the pickers offer `/divisions/scope`), the role of a sent
// invitation stays the admin level's, and `employee` is every inviter's
// floor - mirrors `_allowed_invite_roles` in backend/app/modules/auth/service.py.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const read = (rel: string) => readFileSync(resolve(__dirname, rel), "utf8");
const permissions = read("../hooks/use-permissions.ts");
const sidebar = read("../components/sidebar.tsx");
const importPage = read("../app/(dashboard)/settings/import/page.tsx");
const rolesPage = read("../app/(dashboard)/settings/roles/page.tsx");
const aiPage = read("../app/(dashboard)/settings/ai/page.tsx");
const invitationsPage = read("../app/(dashboard)/settings/invitations/page.tsx");
const employeeCard = read("../app/(dashboard)/employees/[id]/page.tsx");
const companyPage = read("../app/(dashboard)/company/page.tsx");
const addEmployee = read("../components/employees/AddEmployeeDialog.tsx");

describe("the admin block follows the section level (HRP-831)", () => {
  it("reads the matrix in the hook, not the admin role", () => {
    expect(permissions).toContain('canImport: sections.import === "manage",');
    expect(permissions).toContain('canInvite: sections.invitations === "manage",');
    // The two admin pieces on the employee card stay with the rbac seam.
    expect(permissions).toContain("canAssignRoles: isAdmin || isPlatformAdmin,");
  });

  it("drops the admin flag from the four sidebar entries", () => {
    for (const href of ["/settings/import", "/settings/invitations", "/settings/roles", "/settings/ai"]) {
      const item = sidebar.slice(sidebar.indexOf(`href: "${href}"`), sidebar.indexOf("icon:", sidebar.indexOf(`href: "${href}"`)));
      expect(item, href).not.toContain("requireAdmin");
    }
  });

  it("opens each page by its section and writes at manage", () => {
    expect(importPage).toContain('<RequireSection code="import">');
    expect(importPage).toMatch(/\{canImport && \(\s*<Card>/);
    expect(rolesPage).toContain('<RequireSection code="roles">');
    expect(aiPage).toContain('<RequireSection code="ai-settings">');
    expect(aiPage).toContain('const canManage = usePermissions().canManageSection("ai-settings");');
    expect(aiPage.match(/\{canManage && \(/g)).toHaveLength(2);
    expect(invitationsPage).toContain('<RequireSection code="invitations">');
    expect(invitationsPage).toContain('const canManage = canManageSection("invitations");');
    expect(invitationsPage).toMatch(/const editable =\s*inv\.status === "pending" && canManage && allowedRoleCodes\.has\(inv\.role_code\);/);
    // Nowhere to send below the admin level without a subtree (HRP-829's rule).
    expect(invitationsPage).toContain("const canSend = canManage && (isAdminLevel || (scopeIds?.size ?? 0) > 0);");
    expect(invitationsPage).toMatch(/\{canSend && \(\s*<Button data-testid="invitations-btn-invite"/);
    for (const page of [importPage, rolesPage, aiPage, invitationsPage]) {
      expect(page).not.toContain("RequireRole");
    }
  });

  it("keeps the role change of an invitation with the admin level and floors the tiers at employee", () => {
    expect(invitationsPage).toContain("{editable && isAdmin ? (");
    expect(invitationsPage).toContain('const allowed = new Set<string>(["employee"]);');
    expect(invitationsPage).toContain('api.get<{ id: string }[]>("/divisions/scope"),');
  });

  it("gates the links into the block by the section", () => {
    expect(companyPage).toMatch(/\{canImport && \(\s*<Button data-testid="company-btn-import"/);
    expect(addEmployee).toContain("{canInvite ? (");
    expect(employeeCard).toMatch(/const canResendLink =\s*canAssignRoles &&/);
  });
});
