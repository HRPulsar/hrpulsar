import { describe, expect, it } from "vitest";

import {
  averageMatchLevel,
  bestGradeIds,
  competenceAverages,
  competenceMatrixRows,
  EMPTY_FILTERS,
  employeesAtRisk,
  filterEmployees,
  gradeAverages,
  gradeMatrixRows,
  meanPercent,
  sortEmployeesByPercent,
  topPerformers,
} from "@/lib/assessment/group-analytics";
import type {
  GroupAnalyticsCompetenceRef,
  GroupAnalyticsEmployee,
  GroupAnalyticsGradeRef,
} from "@/lib/types";

function employee(
  overrides: Partial<GroupAnalyticsEmployee> & { employee_id: string },
): GroupAnalyticsEmployee {
  return {
    assessment_id: `a-${overrides.employee_id}`,
    full_name: overrides.employee_id,
    avatar_url: null,
    division_id: null,
    division_name: null,
    specialization_id: null,
    specialization_title: null,
    specialization_i18n_key: null,
    grade_id: null,
    grade_title: null,
    grade_i18n_key: null,
    position_title: null,
    percent: null,
    all_dont_know: false,
    competences: [],
    grades: [],
    ...overrides,
  };
}

const gradeTitle = (g: GroupAnalyticsGradeRef) => g.grade_title ?? "—";

describe("meanPercent", () => {
  it("ignores missing values instead of counting them as zero", () => {
    expect(meanPercent([100, null, undefined])).toBe(100);
  });

  it("returns null when nothing is present", () => {
    expect(meanPercent([null, undefined])).toBeNull();
    expect(meanPercent([])).toBeNull();
  });

  it("math-rounds the mean", () => {
    expect(meanPercent([74, 75])).toBe(75);
    expect(meanPercent([74, 74])).toBe(74);
  });
});

describe("filterEmployees", () => {
  const alice = employee({
    employee_id: "alice",
    division_id: "d1",
    specialization_id: "s1",
  });
  const bob = employee({
    employee_id: "bob",
    division_id: "d2",
    specialization_id: "s2",
  });

  it("keeps everyone when no facet is selected", () => {
    expect(filterEmployees([alice, bob], EMPTY_FILTERS)).toHaveLength(2);
  });

  it("filters by division", () => {
    const out = filterEmployees([alice, bob], {
      ...EMPTY_FILTERS,
      divisions: ["d1"],
    });
    expect(out.map((e) => e.employee_id)).toEqual(["alice"]);
  });

  it("filters by specialization and employee together", () => {
    const out = filterEmployees([alice, bob], {
      ...EMPTY_FILTERS,
      specializations: ["s1", "s2"],
      employees: ["bob"],
    });
    expect(out.map((e) => e.employee_id)).toEqual(["bob"]);
  });

  it("drops employees with no division when a division filter is on", () => {
    const nobody = employee({ employee_id: "ghost" });
    const out = filterEmployees([nobody], {
      ...EMPTY_FILTERS,
      divisions: ["d1"],
    });
    expect(out).toEqual([]);
  });
});

describe("employee highlight buckets", () => {
  const low = employee({ employee_id: "low", percent: 49 });
  const mid = employee({ employee_id: "mid", percent: 60 });
  const high = employee({ employee_id: "high", percent: 76 });
  const boundaryLow = employee({ employee_id: "b50", percent: 50 });
  const boundaryHigh = employee({ employee_id: "b75", percent: 75 });
  const unknown = employee({ employee_id: "dk", percent: null });

  it("at risk is strictly below 50", () => {
    const out = employeesAtRisk([low, boundaryLow, mid, unknown]);
    expect(out.map((e) => e.employee_id)).toEqual(["low"]);
  });

  it("top performers are strictly above 75", () => {
    const out = topPerformers([high, boundaryHigh, mid, unknown]);
    expect(out.map((e) => e.employee_id)).toEqual(["high"]);
  });

  it("sorts highest first", () => {
    const a = employee({ employee_id: "a", percent: 10 });
    const b = employee({ employee_id: "b", percent: 40 });
    expect(employeesAtRisk([a, b]).map((e) => e.employee_id)).toEqual([
      "b",
      "a",
    ]);
  });

  it("never buckets an all-Don't-know employee", () => {
    expect(employeesAtRisk([unknown])).toEqual([]);
    expect(topPerformers([unknown])).toEqual([]);
  });
});

describe("averageMatchLevel", () => {
  it("skips employees without a result", () => {
    const out = averageMatchLevel([
      employee({ employee_id: "a", percent: 60 }),
      employee({ employee_id: "b", percent: null }),
    ]);
    expect(out).toBe(60);
  });

  it("is null when nobody has a result", () => {
    expect(
      averageMatchLevel([employee({ employee_id: "a", percent: null })]),
    ).toBeNull();
  });

  it("re-derives the average from the selected competences only", () => {
    const employees = [
      employee({
        employee_id: "a",
        percent: 50,
        competences: [
          { competence_id: "c1", percent: 90 },
          { competence_id: "c2", percent: 10 },
        ],
      }),
      employee({
        employee_id: "b",
        percent: 50,
        competences: [
          { competence_id: "c1", percent: 70 },
          { competence_id: "c2", percent: 30 },
        ],
      }),
    ];

    // Unfiltered the gauge is the overall mean …
    expect(averageMatchLevel(employees)).toBe(50);
    // … filtered to one competence it follows that competence instead.
    expect(averageMatchLevel(employees, ["c1"])).toBe(80);
    expect(averageMatchLevel(employees, ["c2"])).toBe(20);
  });

  it("ignores a Don't-know employee when the competence filter is on", () => {
    const employees = [
      employee({
        employee_id: "a",
        percent: 60,
        competences: [{ competence_id: "c1", percent: 60 }],
      }),
      employee({
        employee_id: "b",
        percent: null,
        competences: [{ competence_id: "c1", percent: null }],
      }),
    ];

    expect(averageMatchLevel(employees, ["c1"])).toBe(60);
  });
});

describe("sortEmployeesByPercent", () => {
  const a = employee({ employee_id: "a", percent: 80 });
  const b = employee({ employee_id: "b", percent: 20 });
  const none = employee({ employee_id: "none", percent: null });

  it("ascending by default puts the weakest first", () => {
    expect(
      sortEmployeesByPercent([a, b, none], "asc").map((e) => e.employee_id),
    ).toEqual(["b", "a", "none"]);
  });

  it("descending flips the order but keeps blanks last", () => {
    expect(
      sortEmployeesByPercent([a, b, none], "desc").map((e) => e.employee_id),
    ).toEqual(["a", "b", "none"]);
  });
});

describe("competenceMatrixRows", () => {
  const compA: GroupAnalyticsCompetenceRef = {
    competence_id: "c1",
    competence_title: "Alpha",
  };
  const compB: GroupAnalyticsCompetenceRef = {
    competence_id: "c2",
    competence_title: "Beta",
  };

  const alice = employee({
    employee_id: "alice",
    competences: [
      { competence_id: "c1", percent: 100 },
      { competence_id: "c2", percent: 20 },
    ],
  });
  const bob = employee({
    employee_id: "bob",
    competences: [
      { competence_id: "c1", percent: 50 },
      { competence_id: "c2", percent: 40 },
    ],
  });

  it("averages each competence across the employees in scope", () => {
    const rows = competenceMatrixRows([alice, bob], [compA, compB], [], "asc");
    const byId = Object.fromEntries(rows.map((r) => [r.id, r.average]));
    expect(byId.c1).toBe(75);
    expect(byId.c2).toBe(30);
  });

  it("sorts by average ascending, then flips on demand", () => {
    const asc = competenceMatrixRows([alice, bob], [compA, compB], [], "asc");
    expect(asc.map((r) => r.id)).toEqual(["c2", "c1"]);
    const desc = competenceMatrixRows([alice, bob], [compA, compB], [], "desc");
    expect(desc.map((r) => r.id)).toEqual(["c1", "c2"]);
  });

  it("breaks average ties by title", () => {
    const tieA = employee({
      employee_id: "x",
      competences: [
        { competence_id: "c1", percent: 50 },
        { competence_id: "c2", percent: 50 },
      ],
    });
    const rows = competenceMatrixRows([tieA], [compB, compA], [], "asc");
    expect(rows.map((r) => r.title)).toEqual(["Alpha", "Beta"]);
  });

  it("honours the competence filter", () => {
    const rows = competenceMatrixRows(
      [alice, bob],
      [compA, compB],
      ["c2"],
      "asc",
    );
    expect(rows.map((r) => r.id)).toEqual(["c2"]);
  });

  it("keeps a competence answered entirely with Don't know, as a blank row", () => {
    const dk = employee({
      employee_id: "dk",
      competences: [{ competence_id: "c1", percent: null }],
    });
    const rows = competenceMatrixRows([dk], [compA], [], "asc");
    expect(rows).toHaveLength(1);
    expect(rows[0].average).toBeNull();
    expect(rows[0].cells.dk).toBeNull();
  });

  it("drops competences nobody in scope was assessed on", () => {
    const rows = competenceMatrixRows([alice], [compA, compB], [], "asc");
    const onlyA = competenceMatrixRows(
      [employee({ employee_id: "solo", competences: [] })],
      [compA],
      [],
      "asc",
    );
    expect(rows).toHaveLength(2);
    expect(onlyA).toEqual([]);
  });

  it("returns no rows when the filter selects nobody", () => {
    expect(competenceMatrixRows([], [compA, compB], [], "asc")).toEqual([]);
  });
});

describe("grade layout", () => {
  const junior: GroupAnalyticsGradeRef = {
    grade_id: "g1",
    grade_title: "Junior",
    grade_i18n_key: null,
    sort_index: 0,
  };
  const middle: GroupAnalyticsGradeRef = {
    grade_id: "g2",
    grade_title: "Middle",
    grade_i18n_key: null,
    sort_index: 1,
  };

  const alice = employee({
    employee_id: "alice",
    grades: [
      { grade_id: "g1", percent: 90 },
      { grade_id: "g2", percent: 40 },
    ],
  });
  const bob = employee({
    employee_id: "bob",
    grades: [
      { grade_id: "g1", percent: 80 },
      { grade_id: "g2", percent: 60 },
    ],
  });

  it("averages each grade in ladder order", () => {
    const rows = gradeAverages([alice, bob], [middle, junior], gradeTitle);
    expect(rows.map((r) => r.title)).toEqual(["Junior", "Middle"]);
    expect(rows.map((r) => r.percent)).toEqual([85, 50]);
  });

  it("marks the single best grade", () => {
    const rows = gradeAverages([alice, bob], [junior, middle], gradeTitle);
    expect(bestGradeIds(rows)).toEqual(["g1"]);
  });

  it("marks every joint-best grade on a tie", () => {
    const tied = employee({
      employee_id: "tied",
      grades: [
        { grade_id: "g1", percent: 70 },
        { grade_id: "g2", percent: 70 },
      ],
    });
    const rows = gradeAverages([tied], [junior, middle], gradeTitle);
    expect(bestGradeIds(rows).sort()).toEqual(["g1", "g2"]);
  });

  it("marks nothing when every grade is blank", () => {
    const blank = employee({
      employee_id: "blank",
      grades: [{ grade_id: "g1", percent: null }],
    });
    const rows = gradeAverages([blank], [junior], gradeTitle);
    expect(bestGradeIds(rows)).toEqual([]);
  });

  it("breaks matrix ties by the grade ladder, not the title", () => {
    const tied = employee({
      employee_id: "tied",
      grades: [
        { grade_id: "g1", percent: 70 },
        { grade_id: "g2", percent: 70 },
      ],
    });
    const rows = gradeMatrixRows([tied], [middle, junior], gradeTitle, "asc");
    expect(rows.map((r) => r.title)).toEqual(["Junior", "Middle"]);
  });
});

describe("competenceAverages (summary tree)", () => {
  it("averages per competence across everyone", () => {
    const out = competenceAverages([
      employee({
        employee_id: "a",
        competences: [{ competence_id: "c1", percent: 100 }],
      }),
      employee({
        employee_id: "b",
        competences: [{ competence_id: "c1", percent: 50 }],
      }),
    ]);
    expect(out.get("c1")).toBe(75);
  });

  it("keeps a competence with no usable values as null", () => {
    const out = competenceAverages([
      employee({
        employee_id: "a",
        competences: [{ competence_id: "c1", percent: null }],
      }),
    ]);
    expect(out.get("c1")).toBeNull();
  });
});
