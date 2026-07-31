// HRP-175: pins the drilldown header counter so it never regresses to
// the cryptic "2/3" form that originally triggered the bug. Three cases
// matter: total-only ("3 employees"), total-vs-plan ("Showing 2 of 3"),
// and empty ("No employees").
//
// i18n F2 (HRP-476): the helper now returns the message key + ICU values
// instead of a rendered string, so the assertions pin keys and values —
// the English wording lives in messages/en.json.

import { describe, expect, it } from "vitest";

import { buildDrilldownCounter } from "@/components/positions/PositionOccupancyDrilldown";
import en from "../../messages/en.json";

describe("buildDrilldownCounter (HRP-175)", () => {
  it("returns null when no position is selected", () => {
    expect(buildDrilldownCounter(null)).toBeNull();
  });

  it("uses the counted employees key when only total is known", () => {
    expect(
      buildDrilldownCounter({
        id: "p1",
        title: "Account Executive",
        headcount: null,
        employee_count: 3,
      }),
    ).toEqual({ key: "drilldownEmployeeCount", values: { count: 3 } });
  });

  it("keeps the singular/plural split inside the message", () => {
    expect(
      buildDrilldownCounter({
        id: "p1",
        title: "Account Executive",
        headcount: null,
        employee_count: 1,
      }),
    ).toEqual({ key: "drilldownEmployeeCount", values: { count: 1 } });
    expect(en.company.drilldownEmployeeCount).toContain("plural");
  });

  it("falls back to the empty-list key on empty list", () => {
    expect(
      buildDrilldownCounter({
        id: "p1",
        title: "Account Executive",
        headcount: null,
        employee_count: 0,
      }),
    ).toEqual({ key: "drilldownNoEmployees", values: {} });
  });

  it("uses the 'showing X of Y' key when total differs from plan headcount", () => {
    expect(
      buildDrilldownCounter({
        id: "p1",
        title: "Account Executive",
        headcount: 3,
        employee_count: 2,
      }),
    ).toEqual({ key: "drilldownShowingOf", values: { total: 2, plan: 3 } });
  });

  it("treats matching plan and total as a clean total", () => {
    expect(
      buildDrilldownCounter({
        id: "p1",
        title: "Account Executive",
        headcount: 3,
        employee_count: 3,
      }),
    ).toEqual({ key: "drilldownEmployeeCount", values: { count: 3 } });
  });

  it("does NOT render the cryptic 'N/M' shorthand", () => {
    const counter = buildDrilldownCounter({
      id: "p1",
      title: "Account Executive",
      headcount: 3,
      employee_count: 2,
    });
    const message = en.company[counter!.key as keyof typeof en.company];
    expect(message).not.toMatch(/^\{\w+\}\/\{\w+\}$/);
    expect(message).toContain("of");
  });
});
