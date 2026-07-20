// HRP-58: derived filter options + AND-matcher for the Division detail
// Employees block. Three filters (specialization / position / grade) all
// combine via AND. Option lists are derived from the loaded employees
// of the division so the dropdowns never show stale catalog items.

export interface DivisionEmployeeForFilter {
  id: string;
  specialization_id?: string | null;
  specialization_title?: string | null;
  position_id?: string | null;
  position_title?: string | null;
  grade_id?: string | null;
  grade_title?: string | null;
}

export interface DivisionEmployeeFilters {
  specializationId: string | null;
  positionId: string | null;
  gradeId: string | null;
}

export const EMPTY_FILTERS: DivisionEmployeeFilters = {
  specializationId: null,
  positionId: null,
  gradeId: null,
};

export type FilterDropdownOption = {
  id: string;
  title: string;
};

/**
 * Derive a sorted, de-duplicated list of options for one of the
 * dropdowns. `idKey`/`titleKey` point at the Employee fields that carry
 * the picked value. Options without an id are skipped — they cannot be
 * filtered on (the underlying employee row matches "no value").
 */
function deriveOptions(
  employees: DivisionEmployeeForFilter[],
  idKey: "position_id" | "grade_id" | "specialization_id",
  titleKey: "position_title" | "grade_title" | "specialization_title",
): FilterDropdownOption[] {
  const map = new Map<string, string>();
  for (const e of employees) {
    const id = e[idKey];
    if (!id) continue;
    const title = (e[titleKey] || "—") as string;
    if (!map.has(id)) {
      map.set(id, title);
    }
  }
  return Array.from(map, ([id, title]) => ({ id, title })).sort((a, b) =>
    a.title.localeCompare(b.title),
  );
}

export function derivePositionOptions(
  employees: DivisionEmployeeForFilter[],
): FilterDropdownOption[] {
  return deriveOptions(employees, "position_id", "position_title");
}

export function deriveGradeOptions(
  employees: DivisionEmployeeForFilter[],
): FilterDropdownOption[] {
  return deriveOptions(employees, "grade_id", "grade_title");
}

export function deriveSpecializationOptions(
  employees: DivisionEmployeeForFilter[],
): FilterDropdownOption[] {
  return deriveOptions(employees, "specialization_id", "specialization_title");
}

/** Combined AND matcher — all active filters must match. */
export function matchesDivisionFilters(
  employee: DivisionEmployeeForFilter,
  filters: DivisionEmployeeFilters,
): boolean {
  if (
    filters.specializationId &&
    employee.specialization_id !== filters.specializationId
  ) {
    return false;
  }
  if (filters.positionId && employee.position_id !== filters.positionId) {
    return false;
  }
  if (filters.gradeId && employee.grade_id !== filters.gradeId) {
    return false;
  }
  return true;
}

export function applyDivisionFilters<T extends DivisionEmployeeForFilter>(
  employees: T[],
  filters: DivisionEmployeeFilters,
): T[] {
  if (!hasActiveDivisionFilters(filters)) return employees;
  return employees.filter((e) => matchesDivisionFilters(e, filters));
}

export function hasActiveDivisionFilters(
  filters: DivisionEmployeeFilters,
): boolean {
  return Boolean(
    filters.specializationId || filters.positionId || filters.gradeId,
  );
}

export function activeFilterCount(filters: DivisionEmployeeFilters): number {
  let n = 0;
  if (filters.specializationId) n += 1;
  if (filters.positionId) n += 1;
  if (filters.gradeId) n += 1;
  return n;
}
