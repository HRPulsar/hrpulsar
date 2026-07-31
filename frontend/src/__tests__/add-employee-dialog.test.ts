// HRP-174: pure helpers behind the "Add employee" dialog. The UI logic
// is exercised by E2E + manual QA; these tests pin the two derivation
// helpers that decide who appears in the picker and who triggers the
// transfer confirm step.

import { describe, expect, it } from "vitest";

import {
  filterAddExistingCandidates,
  pickTransferTargets,
  type AddEmployeeDialogEmployee,
} from "@/components/employees/AddEmployeeDialog";

function emp(
  overrides: Partial<AddEmployeeDialogEmployee>,
): AddEmployeeDialogEmployee {
  return {
    id: "emp",
    user_id: "u",
    user_name: null,
    user_email: null,
    division_id: null,
    division_name: null,
    ...overrides,
  };
}

const TARGET_DIVISION = "div-target";

describe("filterAddExistingCandidates (HRP-174)", () => {
  it("excludes employees already in the target division", () => {
    const employees = [
      emp({ id: "a", division_id: TARGET_DIVISION }),
      emp({ id: "b", division_id: "div-other" }),
      emp({ id: "c", division_id: null }),
    ];
    const result = filterAddExistingCandidates(employees, "", TARGET_DIVISION);
    expect(result.map((e) => e.id)).toEqual(["b", "c"]);
  });

  it("matches name or email substring case-insensitively", () => {
    const employees = [
      emp({ id: "1", user_name: "Alice Doe", user_email: "alice@x.com" }),
      emp({ id: "2", user_name: "Bob", user_email: "bob@y.com" }),
      emp({ id: "3", user_name: "Charlie", user_email: "charlie@z.com" }),
    ];
    expect(
      filterAddExistingCandidates(employees, "ali", TARGET_DIVISION).map(
        (e) => e.id,
      ),
    ).toEqual(["1"]);
    expect(
      filterAddExistingCandidates(employees, "Z.COM", TARGET_DIVISION).map(
        (e) => e.id,
      ),
    ).toEqual(["3"]);
  });

  it("returns all eligible candidates when query is empty", () => {
    const employees = [
      emp({ id: "1", division_id: null }),
      emp({ id: "2", division_id: "div-other" }),
    ];
    const result = filterAddExistingCandidates(employees, "   ", TARGET_DIVISION);
    expect(result).toHaveLength(2);
  });
});

describe("pickTransferTargets (HRP-174)", () => {
  it("returns an empty list when nothing is selected", () => {
    expect(pickTransferTargets([], [], TARGET_DIVISION)).toEqual([]);
  });

  it("flags only employees that belong to a different division", () => {
    const employees = [
      emp({
        id: "stay",
        division_id: TARGET_DIVISION,
        user_name: "Same Division",
      }),
      emp({
        id: "move",
        division_id: "div-other",
        division_name: "Logistics",
        user_name: "Move Me",
      }),
      emp({
        id: "fresh",
        division_id: null,
        user_name: "No Division",
      }),
    ];
    const targets = pickTransferTargets(
      ["stay", "move", "fresh"],
      employees,
      TARGET_DIVISION,
    );
    expect(targets).toEqual([
      {
        employeeId: "move",
        display: "Move Me",
        fromDivision: "Logistics",
      },
    ]);
  });

  it("falls back to email then id when name is missing", () => {
    const employees = [
      emp({
        id: "no-name",
        division_id: "div-other",
        user_name: null,
        user_email: "user@example.com",
      }),
      emp({ id: "anon", division_id: "div-other", user_name: "" }),
    ];
    const targets = pickTransferTargets(
      ["no-name", "anon"],
      employees,
      TARGET_DIVISION,
    );
    expect(targets[0].display).toBe("user@example.com");
    expect(targets[1].display).toBe("anon");
  });

  it("leaves fromDivision null when source division name is missing", () => {
    const employees = [
      emp({
        id: "lost",
        division_id: "div-x",
        division_name: null,
        user_name: "Ghost",
      }),
    ];
    const targets = pickTransferTargets(["lost"], employees, TARGET_DIVISION);
    // The dialog renders a translated "another division" placeholder.
    expect(targets[0].fromDivision).toBeNull();
  });
});
