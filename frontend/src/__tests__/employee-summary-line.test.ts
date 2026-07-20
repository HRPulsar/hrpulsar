// HRP-182: pure helpers behind the shared <EmployeeSummaryLine />. The
// component renders these straight into JSX (name + position line + status
// chip), so pinning the derivation here is enough to catch silent regressions
// across Assessment lists, PDP cards and Talent Market matches that all
// re-use the component.

import { describe, expect, it } from "vitest";

import {
  deriveEmployeeSummary,
  statusBadgeClass,
  statusLabel,
} from "@/components/employee/employee-summary-line";

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

describe("statusLabel", () => {
  it("converts snake_case to spaces", () => {
    expect(statusLabel("on_leave")).toBe("on leave");
    expect(statusLabel("inactive")).toBe("inactive");
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
