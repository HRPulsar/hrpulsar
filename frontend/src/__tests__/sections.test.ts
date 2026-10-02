// @vitest-environment jsdom
// HRP-820: the route → section map must agree with the sidebar ids, which
// are the codes the backend registry (app/core/sections.py) speaks.
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ usePathname: () => "/dashboard" }));

const { SECTION_CODES, sectionForPath } = await import("@/lib/sections");
const { navigation } = await import("@/components/sidebar");

describe("sectionForPath", () => {
  it("maps every sidebar entry to its own code", () => {
    for (const item of navigation) {
      // HRP-823: the exams entry points at one's own exams, which the
      // matrix never closes - the section behind it starts one segment
      // deeper and is checked below.
      if (item.id === "dashboard" || item.id === "exams") continue;
      expect(sectionForPath(item.href), item.href).toBe(item.id);
      expect(SECTION_CODES, item.id).toContain(item.id);
    }
  });

  it("gates the mass exams but not one's own (HRP-823)", () => {
    // The assignment e-mail links to /exams, so the page behind it must
    // survive a section the tenant closed for the taker's role - exactly
    // what `/api/exams*` does on the backend (PERSONAL_PATHS).
    expect(sectionForPath("/exams")).toBeNull();
    expect(sectionForPath("/exams/8f1c")).toBe("exams");
    expect(SECTION_CODES).toContain("exams");
  });

  it("covers nested routes and the odd directories", () => {
    expect(sectionForPath("/employees")).toBe("employees");
    expect(sectionForPath("/employees/123")).toBe("employees");
    expect(sectionForPath("/admin/employees/unassigned")).toBe("employees");
    expect(sectionForPath("/company/profile/section-access")).toBe("company");
    expect(sectionForPath("/assessment-groups/1")).toBe("assessments");
    expect(sectionForPath("/settings/import")).toBe("import");
    expect(sectionForPath("/settings/ai")).toBe("ai-settings");
  });

  it("leaves the surfaces outside the matrix alone", () => {
    // /employees/me mirrors the backend's PERSONAL_PATHS list: the route
    // itself is not gated. The /employees/{id} it redirects to still is.
    for (const path of ["/dashboard", "/onboarding", "/employees/me", "/settings/profile", "/settings/notifications", "/settings/billing"]) {
      expect(sectionForPath(path), path).toBeNull();
    }
  });
});
