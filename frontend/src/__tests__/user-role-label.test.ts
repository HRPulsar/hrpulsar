// HRP-196: the sidebar footer showed the wrong role (or none at all).
// Case 1 — a user promoted Employee -> Manager holds both codes, and
// `roles[0]` on an unordered list kept rendering "Employee".
// Case 2 — a downgraded manager-only user was left with no roles, and the
// footer rendered a blank line instead of "Employee".

import { describe, expect, it } from "vitest";

import {
  FALLBACK_ROLE_CODE,
  resolveDisplayRoleCode,
  resolveRoleLabel,
} from "@/lib/user-role-label";

// Stand-in for next-intl's `t` — echoes the key so assertions stay readable.
const translate = (key: string) => `t:${key}`;

describe("resolveDisplayRoleCode (HRP-196)", () => {
  it("picks manager over employee regardless of order", () => {
    expect(resolveDisplayRoleCode(["employee", "manager"])).toBe("manager");
    expect(resolveDisplayRoleCode(["manager", "employee"])).toBe("manager");
  });

  it("applies the full precedence ladder", () => {
    expect(resolveDisplayRoleCode(["employee", "admin", "manager"])).toBe(
      "admin",
    );
    expect(resolveDisplayRoleCode(["employee", "hr", "manager"])).toBe("hr");
    expect(resolveDisplayRoleCode(["admin", "platform_admin"])).toBe(
      "platform_admin",
    );
  });

  it("falls back to employee for an empty or missing list", () => {
    expect(resolveDisplayRoleCode([])).toBe(FALLBACK_ROLE_CODE);
    expect(resolveDisplayRoleCode(undefined)).toBe(FALLBACK_ROLE_CODE);
    expect(resolveDisplayRoleCode(null)).toBe(FALLBACK_ROLE_CODE);
  });

  it("keeps a tenant-custom role when no system role is present", () => {
    expect(resolveDisplayRoleCode(["mentor"])).toBe("mentor");
  });

  it("prefers a system role over a tenant-custom one", () => {
    expect(resolveDisplayRoleCode(["mentor", "manager"])).toBe("manager");
  });

  // The `employee` baseline is the weakest role and every account carries
  // it, so it must lose to anything else — including roles the precedence
  // ladder does not list. Downgrading a recruiter who managed a division
  // leaves exactly {recruiter, employee}, and showing "Employee" there
  // would be the same wrong-label bug all over again.
  it("ranks a seeded role outside the ladder above the employee baseline", () => {
    expect(resolveDisplayRoleCode(["employee", "recruiter"])).toBe("recruiter");
    expect(resolveDisplayRoleCode(["recruiter", "employee"])).toBe("recruiter");
    expect(resolveDisplayRoleCode(["employee", "hiring_manager"])).toBe(
      "hiring_manager",
    );
  });

  it("ranks a tenant-custom role above the employee baseline", () => {
    expect(resolveDisplayRoleCode(["employee", "mentor"])).toBe("mentor");
  });

  it("still lets a ladder role win over an unknown one", () => {
    expect(resolveDisplayRoleCode(["recruiter", "admin", "employee"])).toBe(
      "admin",
    );
  });
});

describe("resolveRoleLabel (HRP-196)", () => {
  it("translates system roles through the catalog", () => {
    expect(resolveRoleLabel(["employee", "manager"], translate)).toBe(
      "t:roleManager",
    );
    expect(resolveRoleLabel(["employee"], translate)).toBe("t:roleEmployee");
    expect(resolveRoleLabel(["admin"], translate)).toBe("t:roleAdmin");
    expect(resolveRoleLabel(["hr"], translate)).toBe("t:roleHr");
  });

  it("never returns an empty label for a downgraded user", () => {
    expect(resolveRoleLabel([], translate)).toBe("t:roleEmployee");
  });

  it("translates platform_admin through the catalog too", () => {
    expect(resolveRoleLabel(["platform_admin"], translate)).toBe(
      "t:rolePlatformAdmin",
    );
  });

  it("prettifies codes that have no catalog key", () => {
    expect(resolveRoleLabel(["hiring_manager"], translate)).toBe(
      "hiring manager",
    );
    expect(resolveRoleLabel(["mentor"], translate)).toBe("mentor");
  });
});
