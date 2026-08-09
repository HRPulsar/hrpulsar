/**
 * HRP-528: client-side aggregation for the mass-assessment Analytics block.
 *
 * The endpoint ships per-employee values (computed with the HRP-62 formulas)
 * and the two unfiltered competence highlight lists. Everything the filter
 * bar can reshape — average match level, matrix rows, matrix "Average"
 * columns — is derived here so a filter toggle costs no round-trip.
 *
 * Employees whose percent is `null` answered entirely with "Don't know".
 * They stay visible in the matrices but never enter a divisor.
 */

import type {
  GroupAnalyticsCompetenceRef,
  GroupAnalyticsEmployee,
  GroupAnalyticsGradeRef,
} from "@/lib/types";

/** Employees strictly below this percent are "at risk". */
export const AT_RISK_MAX_PERCENT = 50;
/** Employees strictly above this percent are "top performers". */
export const TOP_PERFORMER_MIN_PERCENT = 75;
/** Avatars rendered inline on a highlight plate before collapsing to "+n". */
export const MAX_INLINE_AVATARS = 5;

export type SortDirection = "asc" | "desc";

export interface AnalyticsFilters {
  divisions: string[];
  specializations: string[];
  competences: string[];
  employees: string[];
}

export const EMPTY_FILTERS: AnalyticsFilters = {
  divisions: [],
  specializations: [],
  competences: [],
  employees: [],
};

/** Arithmetic mean of the values that exist, math-rounded to an integer. */
export function meanPercent(
  values: (number | null | undefined)[],
): number | null {
  const present = values.filter(
    (v): v is number => v !== null && v !== undefined && !Number.isNaN(v),
  );
  if (present.length === 0) return null;
  return Math.round(present.reduce((sum, v) => sum + v, 0) / present.length);
}

function byName(a: GroupAnalyticsEmployee, b: GroupAnalyticsEmployee): number {
  return (a.full_name ?? "").localeCompare(b.full_name ?? "");
}

/** Filter bar predicate. An empty list for a facet means "all". */
export function filterEmployees(
  employees: GroupAnalyticsEmployee[],
  filters: AnalyticsFilters,
): GroupAnalyticsEmployee[] {
  return employees.filter((e) => {
    if (
      filters.divisions.length > 0 &&
      (!e.division_id || !filters.divisions.includes(e.division_id))
    ) {
      return false;
    }
    if (
      filters.specializations.length > 0 &&
      (!e.specialization_id ||
        !filters.specializations.includes(e.specialization_id))
    ) {
      return false;
    }
    if (
      filters.employees.length > 0 &&
      !filters.employees.includes(e.employee_id)
    ) {
      return false;
    }
    return true;
  });
}

/** Highest match first, ties alphabetically — the sheet ordering. */
export function sortByPercentDesc(
  employees: GroupAnalyticsEmployee[],
): GroupAnalyticsEmployee[] {
  // Callers pass pre-filtered non-null lists today, but sink blanks explicitly
  // rather than letting `?? 0` rank a missing result above a genuine low one.
  return [...employees].sort((a, b) => {
    if (a.percent === null && b.percent === null) return byName(a, b);
    if (a.percent === null) return 1;
    if (b.percent === null) return -1;
    return b.percent - a.percent || byName(a, b);
  });
}

export function sortEmployeesByName(
  employees: GroupAnalyticsEmployee[],
): GroupAnalyticsEmployee[] {
  return [...employees].sort(byName);
}

/** Employees with a computed result, ordered by percent. */
export function sortEmployeesByPercent(
  employees: GroupAnalyticsEmployee[],
  direction: SortDirection,
): GroupAnalyticsEmployee[] {
  return [...employees].sort((a, b) => {
    const av = a.percent;
    const bv = b.percent;
    // No result sinks to the bottom regardless of direction.
    if (av === null && bv === null) return byName(a, b);
    if (av === null) return 1;
    if (bv === null) return -1;
    if (av !== bv) return direction === "asc" ? av - bv : bv - av;
    return byName(a, b);
  });
}

export function employeesAtRisk(
  employees: GroupAnalyticsEmployee[],
): GroupAnalyticsEmployee[] {
  return sortByPercentDesc(
    employees.filter((e) => e.percent !== null && e.percent < AT_RISK_MAX_PERCENT),
  );
}

export function topPerformers(
  employees: GroupAnalyticsEmployee[],
): GroupAnalyticsEmployee[] {
  return sortByPercentDesc(
    employees.filter(
      (e) => e.percent !== null && e.percent > TOP_PERFORMER_MIN_PERCENT,
    ),
  );
}

/**
 * Average match level across everyone who has a computed result.
 *
 * With a competence filter on, each employee's result is re-derived from the
 * selected competences alone: the filter bar reshapes every number in the
 * Detailed results sub-block, and the gauge sits inside it, so leaving it on
 * the whole-campaign overall would contradict the matrix right below it.
 */
export function averageMatchLevel(
  employees: GroupAnalyticsEmployee[],
  selectedCompetenceIds: string[] = [],
): number | null {
  if (selectedCompetenceIds.length === 0) {
    return meanPercent(employees.map((e) => e.percent));
  }
  const selected = new Set(selectedCompetenceIds);
  return meanPercent(
    employees.map((employee) =>
      meanPercent(
        employee.competences
          .filter((c) => selected.has(c.competence_id))
          .map((c) => c.percent),
      ),
    ),
  );
}

export interface MatrixRow {
  id: string;
  title: string;
  /** Mean across the employees currently in scope. */
  average: number | null;
  /** employee_id → percent (null = no value / all "Don't know"). */
  cells: Record<string, number | null>;
  /** Grade ordering fallback; competences do not use it. */
  sortIndex: number;
}

function sortRows(
  rows: MatrixRow[],
  direction: SortDirection,
  tieBreak: (a: MatrixRow, b: MatrixRow) => number,
): MatrixRow[] {
  return [...rows].sort((a, b) => {
    const av = a.average;
    const bv = b.average;
    if (av === null && bv === null) return tieBreak(a, b);
    if (av === null) return 1;
    if (bv === null) return -1;
    if (av !== bv) return direction === "asc" ? av - bv : bv - av;
    return tieBreak(a, b);
  });
}

/**
 * Matrix rows for the competence layout.
 *
 * A competence is kept when at least one in-scope employee was assessed on
 * it — including when that employee answered "Don't know" throughout, which
 * renders as a dash rather than hiding the row.
 */
export function competenceMatrixRows(
  employees: GroupAnalyticsEmployee[],
  competences: GroupAnalyticsCompetenceRef[],
  selectedCompetenceIds: string[],
  direction: SortDirection,
): MatrixRow[] {
  const rows: MatrixRow[] = [];
  for (const competence of competences) {
    if (
      selectedCompetenceIds.length > 0 &&
      !selectedCompetenceIds.includes(competence.competence_id)
    ) {
      continue;
    }
    const cells: Record<string, number | null> = {};
    let assessed = false;
    for (const employee of employees) {
      const entry = employee.competences.find(
        (c) => c.competence_id === competence.competence_id,
      );
      if (entry) assessed = true;
      cells[employee.employee_id] = entry?.percent ?? null;
    }
    if (!assessed) continue;
    rows.push({
      id: competence.competence_id,
      title: competence.competence_title,
      average: meanPercent(Object.values(cells)),
      cells,
      sortIndex: 0,
    });
  }
  return sortRows(rows, direction, (a, b) => a.title.localeCompare(b.title));
}

/** Matrix rows for the "Target position: All grades" layout. */
export function gradeMatrixRows(
  employees: GroupAnalyticsEmployee[],
  grades: GroupAnalyticsGradeRef[],
  gradeTitle: (grade: GroupAnalyticsGradeRef) => string,
  direction: SortDirection,
): MatrixRow[] {
  const rows: MatrixRow[] = [];
  for (const grade of grades) {
    const cells: Record<string, number | null> = {};
    let assessed = false;
    for (const employee of employees) {
      const entry = employee.grades.find((g) => g.grade_id === grade.grade_id);
      if (entry) assessed = true;
      cells[employee.employee_id] = entry?.percent ?? null;
    }
    if (!assessed) continue;
    rows.push({
      id: grade.grade_id,
      title: gradeTitle(grade),
      average: meanPercent(Object.values(cells)),
      cells,
      sortIndex: grade.sort_index,
    });
  }
  // Ties fall back to the grade ladder (junior → senior), not the title.
  return sortRows(rows, direction, (a, b) => a.sortIndex - b.sortIndex);
}

export interface GradeAverage {
  grade_id: string;
  title: string;
  sortIndex: number;
  percent: number | null;
}

/** Average match per grade, in ladder order. */
export function gradeAverages(
  employees: GroupAnalyticsEmployee[],
  grades: GroupAnalyticsGradeRef[],
  gradeTitle: (grade: GroupAnalyticsGradeRef) => string,
): GradeAverage[] {
  return [...grades]
    .sort((a, b) => a.sort_index - b.sort_index)
    .map((grade) => ({
      grade_id: grade.grade_id,
      title: gradeTitle(grade),
      sortIndex: grade.sort_index,
      percent: meanPercent(
        employees.map(
          (e) => e.grades.find((g) => g.grade_id === grade.grade_id)?.percent ?? null,
        ),
      ),
    }));
}

/**
 * Ids of the best-matching grades. Several ids come back on a tie — the spec
 * asks for every joint-best grade to be highlighted.
 */
export function bestGradeIds(averages: GradeAverage[]): string[] {
  const present = averages.filter(
    (a): a is GradeAverage & { percent: number } => a.percent !== null,
  );
  if (present.length === 0) return [];
  const max = Math.max(...present.map((a) => a.percent));
  return present.filter((a) => a.percent === max).map((a) => a.grade_id);
}

/** Average per competence across the in-scope employees, for the tree. */
export function competenceAverages(
  employees: GroupAnalyticsEmployee[],
): Map<string, number | null> {
  const buckets = new Map<string, (number | null)[]>();
  for (const employee of employees) {
    for (const row of employee.competences) {
      const list = buckets.get(row.competence_id) ?? [];
      list.push(row.percent);
      buckets.set(row.competence_id, list);
    }
  }
  const out = new Map<string, number | null>();
  for (const [competenceId, values] of buckets) {
    out.set(competenceId, meanPercent(values));
  }
  return out;
}
