/** Division id -> its head and its parent, flattened from the `/divisions` tree. */
export type DivisionChain = Map<string, { managerId: string | null; parentId: string | null }>;

/**
 * HRP-1049: does the employee have a line manager - the head of their
 * division, or, when that seat is empty or their own, the nearest assigned
 * head up the parent chain? Mirrors the server's
 * company.line_manager.resolve_line_manager, which picks the 180/360
 * manager participant.
 */
export function hasLineManager(
  employeeId: string,
  divisionId: string | null | undefined,
  divisions: DivisionChain,
): boolean {
  const seen = new Set<string>();
  let id = divisionId ?? null;
  while (id !== null && !seen.has(id)) {
    seen.add(id);
    const division = divisions.get(id);
    if (!division) return false;
    if (division.managerId && division.managerId !== employeeId) return true;
    id = division.parentId;
  }
  return false;
}
