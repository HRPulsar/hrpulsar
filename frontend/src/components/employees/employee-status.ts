/**
 * Employee status codes → keys in the `employees` i18n namespace.
 *
 * The set is owned by the frontend (the same four options back the status
 * filter, the edit form and the badges), so the label is a presentation
 * concern rather than API data. Anything the API sends outside the set
 * falls back to the raw code with underscores turned into spaces — the
 * pre-i18n rendering.
 */

export const EMPLOYEE_STATUS_CODES = [
  "active",
  "inactive",
  "on_leave",
  "terminated",
] as const;

const STATUS_KEYS: Record<string, string> = {
  active: "statusActive",
  inactive: "statusInactive",
  on_leave: "statusOnLeave",
  terminated: "statusTerminated",
};

/** i18n key for a known status code, or `null` for anything unexpected. */
export function employeeStatusKey(
  status: string | null | undefined,
): string | null {
  if (!status) return null;
  return STATUS_KEYS[status] ?? null;
}

/** Translated status label with a graceful fallback for unknown codes. */
export function employeeStatusLabel(
  t: (key: string) => string,
  status: string | null | undefined,
): string {
  if (!status) return "";
  const key = employeeStatusKey(status);
  return key ? t(key) : status.replace(/_/g, " ");
}
