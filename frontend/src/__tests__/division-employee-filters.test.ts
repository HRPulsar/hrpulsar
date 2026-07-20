// HRP-58: pins the AND-combinator for Specialization + Position + Grade
// filters on the Division detail Employees block. Every existing scenario
// from the task description maps to a single test here.

import { describe, expect, it } from "vitest";

import {
  EMPTY_FILTERS,
  activeFilterCount,
  applyDivisionFilters,
  deriveGradeOptions,
  derivePositionOptions,
  hasActiveDivisionFilters,
  matchesDivisionFilters,
  type DivisionEmployeeForFilter,
} from "@/lib/division-employee-filters";

function makeEmployee(
  overrides: Partial<DivisionEmployeeForFilter> = {},
): DivisionEmployeeForFilter {
  return {
    id: "e1",
    specialization_id: "spec-logistics",
    specialization_title: "Logistics",
    position_id: "pos-senior",
    position_title: "Senior Logistician",
    grade_id: "grade-lead",
    grade_title: "Lead",
    ...overrides,
  };
}

describe("matchesDivisionFilters (HRP-58)", () => {
  it("returns true with no active filters", () => {
    expect(matchesDivisionFilters(makeEmployee(), EMPTY_FILTERS)).toBe(true);
  });

  it("filters by specialization", () => {
    expect(
      matchesDivisionFilters(makeEmployee({ specialization_id: "spec-a" }), {
        ...EMPTY_FILTERS,
        specializationId: "spec-a",
      }),
    ).toBe(true);
    expect(
      matchesDivisionFilters(makeEmployee({ specialization_id: "spec-b" }), {
        ...EMPTY_FILTERS,
        specializationId: "spec-a",
      }),
    ).toBe(false);
  });

  it("filters by position", () => {
    expect(
      matchesDivisionFilters(makeEmployee({ position_id: "pos-1" }), {
        ...EMPTY_FILTERS,
        positionId: "pos-1",
      }),
    ).toBe(true);
    expect(
      matchesDivisionFilters(makeEmployee({ position_id: "pos-2" }), {
        ...EMPTY_FILTERS,
        positionId: "pos-1",
      }),
    ).toBe(false);
  });

  it("filters by grade", () => {
    expect(
      matchesDivisionFilters(makeEmployee({ grade_id: "g-jr" }), {
        ...EMPTY_FILTERS,
        gradeId: "g-jr",
      }),
    ).toBe(true);
    expect(
      matchesDivisionFilters(makeEmployee({ grade_id: "g-sr" }), {
        ...EMPTY_FILTERS,
        gradeId: "g-jr",
      }),
    ).toBe(false);
  });

  it("combines three filters with AND", () => {
    const emp = makeEmployee({
      specialization_id: "spec-a",
      position_id: "pos-1",
      grade_id: "g-jr",
    });
    expect(
      matchesDivisionFilters(emp, {
        specializationId: "spec-a",
        positionId: "pos-1",
        gradeId: "g-jr",
      }),
    ).toBe(true);
    // One mismatch breaks the AND
    expect(
      matchesDivisionFilters(emp, {
        specializationId: "spec-a",
        positionId: "pos-2",
        gradeId: "g-jr",
      }),
    ).toBe(false);
  });
});

describe("applyDivisionFilters", () => {
  it("returns input unchanged when no filters are active", () => {
    const employees = [makeEmployee(), makeEmployee({ id: "e2" })];
    const result = applyDivisionFilters(employees, EMPTY_FILTERS);
    expect(result).toBe(employees);
  });

  it("returns the intersection (specialization + position + grade)", () => {
    const employees = [
      makeEmployee({
        id: "a",
        specialization_id: "spec-1",
        position_id: "pos-1",
        grade_id: "g-1",
      }),
      makeEmployee({
        id: "b",
        specialization_id: "spec-1",
        position_id: "pos-2",
        grade_id: "g-1",
      }),
      makeEmployee({
        id: "c",
        specialization_id: "spec-2",
        position_id: "pos-1",
        grade_id: "g-1",
      }),
    ];
    const result = applyDivisionFilters(employees, {
      specializationId: "spec-1",
      positionId: "pos-1",
      gradeId: "g-1",
    });
    expect(result.map((e) => e.id)).toEqual(["a"]);
  });
});

describe("derive option helpers", () => {
  it("derives position options as unique sorted list", () => {
    const employees = [
      makeEmployee({ position_id: "pos-z", position_title: "Zeta" }),
      makeEmployee({ position_id: "pos-a", position_title: "Alpha" }),
      makeEmployee({ position_id: "pos-a", position_title: "Alpha" }),
    ];
    expect(derivePositionOptions(employees)).toEqual([
      { id: "pos-a", title: "Alpha" },
      { id: "pos-z", title: "Zeta" },
    ]);
  });

  it("derives grade options ignoring employees without a grade", () => {
    const employees = [
      makeEmployee({ grade_id: null, grade_title: null }),
      makeEmployee({ grade_id: "g-sr", grade_title: "Senior" }),
    ];
    expect(deriveGradeOptions(employees)).toEqual([
      { id: "g-sr", title: "Senior" },
    ]);
  });
});

describe("helpers", () => {
  it("hasActiveDivisionFilters detects any active filter", () => {
    expect(hasActiveDivisionFilters(EMPTY_FILTERS)).toBe(false);
    expect(
      hasActiveDivisionFilters({ ...EMPTY_FILTERS, gradeId: "g-1" }),
    ).toBe(true);
  });

  it("activeFilterCount counts each non-null filter", () => {
    expect(activeFilterCount(EMPTY_FILTERS)).toBe(0);
    expect(
      activeFilterCount({
        specializationId: "s",
        positionId: "p",
        gradeId: null,
      }),
    ).toBe(2);
  });
});
