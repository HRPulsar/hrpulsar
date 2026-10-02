import type { Employee } from "@/lib/types";

/**
 * HRP-857: who may be named a division's head or deputy. Being named grants
 * the manager role, so below the admin level it is someone of one's own
 * subtree - the divisions `/divisions/scope` returns - or oneself; the API
 * answers 403 for anyone else.
 */
export function headCandidates(
  employees: Employee[],
  opts: { adminLevel: boolean; scopeIds: ReadonlySet<string>; userId?: string },
): Employee[] {
  if (opts.adminLevel) return employees;
  return employees.filter(
    (e) =>
      (opts.userId !== undefined && e.user_id === opts.userId) ||
      (e.division_id !== null && opts.scopeIds.has(e.division_id)),
  );
}
