// HRP-660: actions whose subject is one employee start from that employee's
// card and finish on the screen that already owns the flow.
//
// The employee travels in the URL — `?create=1&employee_id=<uuid>` — so the
// card never grows a second copy of a dialog it does not own, and the
// prefill logic (specialization and grade from the employee's position)
// stays where it was written. Anything else that wants to hand an employee
// to one of these flows (HRP-665's talent-market card) links to the same
// builders instead of inventing a third contract.

export const EMPLOYEE_CREATE_PARAM = "create";
export const EMPLOYEE_ID_PARAM = "employee_id";

function createHref(path: string, employeeId: string): string {
  const params = new URLSearchParams({
    [EMPLOYEE_CREATE_PARAM]: "1",
    [EMPLOYEE_ID_PARAM]: employeeId,
  });
  return `${path}?${params}`;
}

/** `/development` with the Create plan dialog open on this employee. */
export function createPdpHref(employeeId: string): string {
  return createHref("/development", employeeId);
}

/** `/assessments` with the single-assessment dialog open on this employee. */
export function createAssessmentHref(employeeId: string): string {
  return createHref("/assessments", employeeId);
}

/**
 * The employee a create deep link names, or `null` when the query string is
 * not one. Both target pages read the link through this so a typo on one
 * side cannot make them disagree about the contract.
 */
export function readCreateDeepLink(search: string): string | null {
  const params = new URLSearchParams(search);
  if (params.get(EMPLOYEE_CREATE_PARAM) !== "1") return null;
  const id = params.get(EMPLOYEE_ID_PARAM)?.trim();
  return id ? id : null;
}
