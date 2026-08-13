// HRP-58 (REDO): the Specializations block on the Division detail page.
//
// QA reported "Specializations (0)" on the THIRD nesting level of an org
// (Engineering -> QA -> QA-2) while the Employees filters on the same page
// listed those specializations correctly. Two causes, both covered here:
//
//  1. the tiles rendered the division's mapped catalogue only, so a
//     division whose specializations are mapped further up the tree — or
//     not mapped at all, since a specialization follows the employee's
//     position — had nothing to render;
//  2. counts came from employees whose division matched exactly, so any
//     parent whose staff sit in child departments counted zero.
//
// Depth is deliberately >= 3 levels: two levels behaved correctly before
// the fix, which is why the bug reached production.

import { describe, expect, it } from "vitest";

import {
  collectDivisionSubtreeIds,
  deriveSpecializationTiles,
  reconcileDivisionFilters,
  type DivisionEmployeeForFilter,
  type DivisionSpecializationForFilter,
  type DivisionTreeNode,
} from "@/lib/division-employee-filters";

// Engineering -> QA -> QA-2 -> QA-2 Automation, plus a sibling branch.
const TREE: DivisionTreeNode[] = [
  {
    id: "d-engineering",
    children: [
      {
        id: "d-qa",
        children: [
          {
            id: "d-qa-2",
            children: [{ id: "d-qa-2-automation", children: [] }],
          },
        ],
      },
      { id: "d-backend", children: [] },
    ],
  },
  { id: "d-sales", children: [] },
];

function employee(
  id: string,
  divisionId: string,
  specializationId: string | null,
  specializationTitle: string | null = null,
): DivisionEmployeeForFilter & { division_id: string } {
  return {
    id,
    division_id: divisionId,
    specialization_id: specializationId,
    specialization_title: specializationTitle,
  };
}

describe("collectDivisionSubtreeIds (HRP-58)", () => {
  it("collects four levels from the root", () => {
    expect(collectDivisionSubtreeIds(TREE, "d-engineering")).toEqual([
      "d-engineering",
      "d-qa",
      "d-backend",
      "d-qa-2",
      "d-qa-2-automation",
    ]);
  });

  it("collects the third level and everything under it", () => {
    expect(collectDivisionSubtreeIds(TREE, "d-qa-2")).toEqual([
      "d-qa-2",
      "d-qa-2-automation",
    ]);
  });

  it("never walks up or sideways", () => {
    const ids = collectDivisionSubtreeIds(TREE, "d-qa");
    expect(ids).toContain("d-qa-2");
    expect(ids).not.toContain("d-engineering");
    expect(ids).not.toContain("d-backend");
  });

  it("returns the leaf itself", () => {
    expect(collectDivisionSubtreeIds(TREE, "d-sales")).toEqual(["d-sales"]);
  });

  it("returns nothing for an unknown division", () => {
    expect(collectDivisionSubtreeIds(TREE, "d-missing")).toEqual([]);
    expect(collectDivisionSubtreeIds([], "d-engineering")).toEqual([]);
  });

  it("tolerates missing children arrays", () => {
    expect(collectDivisionSubtreeIds([{ id: "d-flat" }], "d-flat")).toEqual([
      "d-flat",
    ]);
  });
});

describe("deriveSpecializationTiles (HRP-58 REDO)", () => {
  it("renders tiles for specializations only the employees carry", () => {
    // The exact QA case: a third-level division with no mapping rows of
    // its own. Before the fix this produced "Specializations (0)".
    const tiles = deriveSpecializationTiles(
      [],
      [
        employee("e1", "d-qa-2", "spec-qa", "QA Engineer"),
        employee("e2", "d-qa-2", "spec-qa", "QA Engineer"),
      ],
    );
    expect(tiles).toEqual([
      { specializationId: "spec-qa", title: "QA Engineer", count: 2 },
    ]);
  });

  it("counts employees from every nesting level of the subtree", () => {
    const mapped: DivisionSpecializationForFilter[] = [
      { specialization_id: "spec-qa", specialization_title: "QA Engineer" },
    ];
    // One person per level, three levels deep.
    const tiles = deriveSpecializationTiles(mapped, [
      employee("e1", "d-engineering", "spec-qa", "QA Engineer"),
      employee("e2", "d-qa", "spec-qa", "QA Engineer"),
      employee("e3", "d-qa-2", "spec-qa", "QA Engineer"),
      employee("e4", "d-qa-2-automation", "spec-qa", "QA Engineer"),
    ]);
    expect(tiles).toHaveLength(1);
    expect(tiles[0].count).toBe(4);
  });

  it("keeps a mapped specialization with nobody in it at zero", () => {
    const tiles = deriveSpecializationTiles(
      [
        { specialization_id: "spec-qa", specialization_title: "QA Engineer" },
        { specialization_id: "spec-devops", specialization_title: "DevOps" },
      ],
      [employee("e1", "d-qa-2", "spec-qa", "QA Engineer")],
    );
    expect(tiles).toEqual([
      { specializationId: "spec-devops", title: "DevOps", count: 0 },
      { specializationId: "spec-qa", title: "QA Engineer", count: 1 },
    ]);
  });

  it("unions the catalogue with employee-held specializations", () => {
    const tiles = deriveSpecializationTiles(
      [{ specialization_id: "spec-devops", specialization_title: "DevOps" }],
      [employee("e1", "d-qa-2", "spec-qa", "QA Engineer")],
    );
    expect(tiles.map((t) => t.specializationId).sort()).toEqual([
      "spec-devops",
      "spec-qa",
    ]);
  });

  it("prefers the curated catalogue title over the employee's copy", () => {
    const tiles = deriveSpecializationTiles(
      [{ specialization_id: "spec-qa", specialization_title: "QA Engineer" }],
      [employee("e1", "d-qa-2", "spec-qa", "qa engineer (stale)")],
    );
    expect(tiles[0].title).toBe("QA Engineer");
  });

  it("ignores employees without a specialization", () => {
    const tiles = deriveSpecializationTiles(
      [],
      [
        employee("e1", "d-qa-2", null),
        employee("e2", "d-qa-2", "spec-qa", "QA Engineer"),
      ],
    );
    expect(tiles).toEqual([
      { specializationId: "spec-qa", title: "QA Engineer", count: 1 },
    ]);
  });

  it("sorts tiles by title", () => {
    const tiles = deriveSpecializationTiles(
      [],
      [
        employee("e1", "d-qa-2", "spec-z", "Zebra"),
        employee("e2", "d-qa-2", "spec-a", "Alpha"),
      ],
    );
    expect(tiles.map((t) => t.title)).toEqual(["Alpha", "Zebra"]);
  });

  it("returns nothing when the division has neither mappings nor staff", () => {
    expect(deriveSpecializationTiles([], [])).toEqual([]);
  });
});

describe("reconcileDivisionFilters (HRP-58 review fix)", () => {
  const options = {
    specializations: [{ id: "spec-qa", title: "QA Engineer" }],
    positions: [{ id: "pos-1", title: "QA Engineer (Senior)" }],
    grades: [{ id: "grade-1", title: "Senior" }],
  };

  it("keeps values that are still offered", () => {
    const filters = {
      specializationId: "spec-qa",
      positionId: "pos-1",
      gradeId: "grade-1",
    };
    expect(reconcileDivisionFilters(filters, options)).toBe(filters);
  });

  it("returns the same object when nothing is selected", () => {
    const filters = {
      specializationId: null,
      positionId: null,
      gradeId: null,
    };
    expect(reconcileDivisionFilters(filters, options)).toBe(filters);
  });

  it("clears values the narrowed scope no longer offers", () => {
    // Turning off "Include sub-divisions" drops the nested employees, and
    // with them the position they held: the chip would say "Unknown" over
    // an empty table.
    const filters = {
      specializationId: "spec-qa",
      positionId: "pos-gone",
      gradeId: "grade-gone",
    };
    expect(reconcileDivisionFilters(filters, options)).toEqual({
      specializationId: "spec-qa",
      positionId: null,
      gradeId: null,
    });
  });

  it("clears everything when the scope has no options at all", () => {
    const filters = {
      specializationId: "spec-qa",
      positionId: "pos-1",
      gradeId: "grade-1",
    };
    expect(
      reconcileDivisionFilters(filters, {
        specializations: [],
        positions: [],
        grades: [],
      }),
    ).toEqual({ specializationId: null, positionId: null, gradeId: null });
  });
});
