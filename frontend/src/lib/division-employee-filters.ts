// HRP-58: derived filter options + AND-matcher for the Division detail
// Employees block. Three filters (specialization / position / grade) all
// combine via AND. Position and Grade options are derived from the loaded
// employees of the division so the dropdowns never show stale catalog
// items; Specialization additionally unions in the division's mapped
// specializations, because the tiles render that catalogue (see
// `deriveSpecializationOptions`).

export interface DivisionEmployeeForFilter {
  id: string;
  specialization_id?: string | null;
  specialization_title?: string | null;
  position_id?: string | null;
  position_title?: string | null;
  grade_id?: string | null;
  grade_title?: string | null;
}

/** One row of the division's specialization catalogue (the tiles). */
export interface DivisionSpecializationForFilter {
  specialization_id: string;
  specialization_title?: string | null;
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
  idKey: "position_id" | "grade_id",
  titleKey: "position_title" | "grade_title",
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

/**
 * Specialization options are the UNION of two sources, because neither
 * alone is complete:
 *
 *  - the division's specialization catalogue (what the clickable tiles
 *    render). A tile must always resolve to an option, including one with
 *    zero employees — otherwise clicking it would leave the select
 *    trigger showing "All specializations" while the filter is active.
 *  - the specializations actually present on the loaded employees. An
 *    employee's specialization comes from their *position*, not from the
 *    division mapping, so someone can hold a specialization the division
 *    was never mapped to. Catalogue-only options would make those rows
 *    unreachable by this filter while Position and Grade still list them.
 *
 * The catalogue title wins on collision — it is the curated one.
 */
export function deriveSpecializationOptions(
  specializations: DivisionSpecializationForFilter[],
  employees: DivisionEmployeeForFilter[] = [],
): FilterDropdownOption[] {
  const map = new Map<string, string>();
  for (const e of employees) {
    if (!e.specialization_id) continue;
    if (!map.has(e.specialization_id)) {
      map.set(e.specialization_id, e.specialization_title || "—");
    }
  }
  // Catalogue second so its title overwrites the employee-derived one.
  for (const s of specializations) {
    if (!s.specialization_id) continue;
    map.set(s.specialization_id, s.specialization_title || "—");
  }
  return Array.from(map, ([id, title]) => ({ id, title })).sort((a, b) =>
    a.title.localeCompare(b.title),
  );
}

/** A node of the division tree as returned by `GET /divisions`. */
export interface DivisionTreeNode {
  id: string;
  children?: DivisionTreeNode[] | null;
}

/**
 * HRP-58: ids of `rootId` and every division nested under it, at any
 * depth. Returns `[rootId]` when the root is a leaf, and `[]` when the
 * root is not in the tree (still loading / out of the caller's scope).
 *
 * The page uses this only to decide whether the "include sub-divisions"
 * control is meaningful — the actual widening happens server-side via
 * `include_sub_divisions`, so a partially loaded tree can never silently
 * truncate the employee list.
 */
export function collectDivisionSubtreeIds(
  tree: DivisionTreeNode[],
  rootId: string,
): string[] {
  const found = findDivisionNode(tree, rootId);
  if (!found) return [];
  const ids: string[] = [];
  const seen = new Set<string>();
  const queue: DivisionTreeNode[] = [found];
  while (queue.length > 0) {
    const node = queue.shift() as DivisionTreeNode;
    if (seen.has(node.id)) continue;
    seen.add(node.id);
    ids.push(node.id);
    for (const child of node.children ?? []) queue.push(child);
  }
  return ids;
}

function findDivisionNode(
  tree: DivisionTreeNode[],
  id: string,
): DivisionTreeNode | null {
  for (const node of tree) {
    if (node.id === id) return node;
    const hit = findDivisionNode(node.children ?? [], id);
    if (hit) return hit;
  }
  return null;
}

/** One clickable specialization tile on the division page. */
export interface DivisionSpecializationTile {
  specializationId: string;
  title: string;
  count: number;
}

/**
 * HRP-58 REDO: the tiles of the Specializations block.
 *
 * They used to render the division's mapped specializations only, which
 * is why a nested division showed "Specializations (0)": mappings are
 * usually curated on the upper levels, while an employee's specialization
 * follows their *position* and needs no mapping at all. The Employees
 * filter already unioned both sources — the tiles did not, so the two
 * blocks disagreed on the same page.
 *
 * Tiles are now the same union the filter uses, with the headcount of the
 * employees passed in (the caller decides whether that set covers nested
 * divisions). A mapped specialization with nobody in it keeps its tile
 * with a zero count — that is real information about the org chart, not
 * an empty block.
 */
export function deriveSpecializationTiles(
  specializations: DivisionSpecializationForFilter[],
  employees: DivisionEmployeeForFilter[],
): DivisionSpecializationTile[] {
  const counts = new Map<string, number>();
  for (const e of employees) {
    if (!e.specialization_id) continue;
    counts.set(e.specialization_id, (counts.get(e.specialization_id) ?? 0) + 1);
  }
  return deriveSpecializationOptions(specializations, employees).map((opt) => ({
    specializationId: opt.id,
    title: opt.title,
    count: counts.get(opt.id) ?? 0,
  }));
}

/**
 * HRP-58 review fix: drop filter values that the current scope no longer
 * offers.
 *
 * Turning "Include sub-divisions" off shrinks the employee set, and with
 * it the option lists. A value picked under the wider scope would survive
 * as a dangling id: the chip renders "Unknown", the select falls back to
 * its placeholder, and the table is empty for no visible reason. Anything
 * that is no longer selectable is cleared.
 *
 * Returns the SAME object when nothing changed — the caller feeds this
 * straight into `setFilters`, and a fresh object every render would
 * re-trigger the effect that calls it.
 */
export function reconcileDivisionFilters(
  filters: DivisionEmployeeFilters,
  options: {
    specializations: FilterDropdownOption[];
    positions: FilterDropdownOption[];
    grades: FilterDropdownOption[];
  },
): DivisionEmployeeFilters {
  const keep = (id: string | null, opts: FilterDropdownOption[]) =>
    id && opts.some((o) => o.id === id) ? id : null;

  const next: DivisionEmployeeFilters = {
    specializationId: keep(filters.specializationId, options.specializations),
    positionId: keep(filters.positionId, options.positions),
    gradeId: keep(filters.gradeId, options.grades),
  };

  const unchanged =
    next.specializationId === filters.specializationId &&
    next.positionId === filters.positionId &&
    next.gradeId === filters.gradeId;
  return unchanged ? filters : next;
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
