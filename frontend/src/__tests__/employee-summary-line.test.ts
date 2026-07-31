// HRP-182: pure helpers behind the shared <EmployeeSummaryLine />. The
// component renders these straight into JSX (name + position line + status
// chip), so pinning the derivation here is enough to catch silent regressions
// across Assessment lists, PDP cards and Talent Market matches that all
// re-use the component.

import { describe, expect, it } from "vitest";

import {
  deriveEmployeeSummary,
  statusBadgeClass,
} from "@/components/employee/employee-summary-line";
import {
  employeeStatusKey,
  employeeStatusLabel,
} from "@/components/employees/employee-status";

describe("deriveEmployeeSummary", () => {
  it("uses user_name when present, trimmed", () => {
    expect(
      deriveEmployeeSummary({ user_name: "  Alice  ", user_email: "a@x" }),
    ).toEqual({ name: "Alice", position: "", status: "active", showStatus: false });
  });

  it("falls back to user_email when user_name is empty / whitespace", () => {
    expect(
      deriveEmployeeSummary({ user_name: "   ", user_email: "  fallback@x  " }).name,
    ).toBe("fallback@x");
  });

  it("returns empty name when neither field is usable", () => {
    expect(deriveEmployeeSummary({ user_name: null, user_email: null }).name).toBe("");
    expect(deriveEmployeeSummary({}).name).toBe("");
  });

  it("trims position and treats whitespace as empty", () => {
    expect(deriveEmployeeSummary({ position_title: "  Senior  " }).position).toBe(
      "Senior",
    );
    expect(deriveEmployeeSummary({ position_title: "   " }).position).toBe("");
  });

  it("defaults status to active and hides chip", () => {
    expect(deriveEmployeeSummary({}).status).toBe("active");
    expect(deriveEmployeeSummary({}).showStatus).toBe(false);
    expect(deriveEmployeeSummary({ status: null }).status).toBe("active");
  });

  it("surfaces non-active statuses with showStatus=true", () => {
    for (const s of ["on_leave", "inactive", "terminated"]) {
      const r = deriveEmployeeSummary({ status: s });
      expect(r.status).toBe(s);
      expect(r.showStatus).toBe(true);
    }
  });
});

describe("employeeStatusKey / employeeStatusLabel (i18n)", () => {
  // The catalogue value itself lives in messages/*.json; the helper only
  // has to pick the right key and fall back for codes it doesn't know.
  const t = (key: string) => `t:${key}`;

  it("maps the known status codes onto namespace keys", () => {
    expect(employeeStatusKey("active")).toBe("statusActive");
    expect(employeeStatusKey("on_leave")).toBe("statusOnLeave");
    expect(employeeStatusKey("inactive")).toBe("statusInactive");
    expect(employeeStatusKey("terminated")).toBe("statusTerminated");
  });

  it("returns no key for unknown or empty codes", () => {
    expect(employeeStatusKey("unknown_status")).toBeNull();
    expect(employeeStatusKey(null)).toBeNull();
    expect(employeeStatusKey(undefined)).toBeNull();
  });

  it("translates known codes and falls back to the raw code otherwise", () => {
    expect(employeeStatusLabel(t, "on_leave")).toBe("t:statusOnLeave");
    expect(employeeStatusLabel(t, "unknown_status")).toBe("unknown status");
    expect(employeeStatusLabel(t, null)).toBe("");
  });
});

describe("statusBadgeClass", () => {
  it("colours on_leave amber", () => {
    expect(statusBadgeClass("on_leave")).toContain("amber");
  });

  it("colours inactive/terminated with the neutral muted token", () => {
    expect(statusBadgeClass("inactive")).toContain("muted-foreground");
    expect(statusBadgeClass("terminated")).toContain("muted-foreground");
  });

  it("falls back to the neutral muted token for unknown statuses", () => {
    expect(statusBadgeClass("unknown_status")).toContain("muted-foreground");
  });
});
