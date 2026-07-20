// HRP-175: pins the drilldown header counter so it never regresses to
// the cryptic "2/3" form that originally triggered the bug. Three cases
// matter: total-only ("3 employees"), total-vs-plan ("Showing 2 of 3"),
// and empty ("No employees").

import { describe, expect, it } from "vitest";

import { buildDrilldownCounter } from "@/components/positions/PositionOccupancyDrilldown";

describe("buildDrilldownCounter (HRP-175)", () => {
  it("returns empty string when no position is selected", () => {
    expect(buildDrilldownCounter(null)).toBe("");
  });

  it("shows plural employees when only total is known", () => {
    expect(
      buildDrilldownCounter({
        id: "p1",
        title: "Account Executive",
        headcount: null,
        employee_count: 3,
      }),
    ).toBe("3 employees");
  });

  it("uses singular for one employee", () => {
    expect(
      buildDrilldownCounter({
        id: "p1",
        title: "Account Executive",
        headcount: null,
        employee_count: 1,
      }),
    ).toBe("1 employee");
  });

  it("falls back to 'No employees' on empty list", () => {
    expect(
      buildDrilldownCounter({
        id: "p1",
        title: "Account Executive",
        headcount: null,
        employee_count: 0,
      }),
    ).toBe("No employees");
  });

  it("shows 'Showing X of Y' when total differs from plan headcount", () => {
    expect(
      buildDrilldownCounter({
        id: "p1",
        title: "Account Executive",
        headcount: 3,
        employee_count: 2,
      }),
    ).toBe("Showing 2 of 3 employees");
  });

  it("treats matching plan and total as a clean total", () => {
    expect(
      buildDrilldownCounter({
        id: "p1",
        title: "Account Executive",
        headcount: 3,
        employee_count: 3,
      }),
    ).toBe("3 employees");
  });

  it("does NOT render the cryptic 'N/M' shorthand", () => {
    const label = buildDrilldownCounter({
      id: "p1",
      title: "Account Executive",
      headcount: 3,
      employee_count: 2,
    });
    expect(label).not.toMatch(/^\d+\/\d+$/);
    expect(label).toContain("of");
  });
});
