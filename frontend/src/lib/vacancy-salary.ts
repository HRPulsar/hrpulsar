// HRP-440: one salary contract for every vacancy surface.
//
// The Overview block already edited salary_min / salary_max /
// salary_currency inline; the Create and Edit forms did not offer the
// fields at all, so a recruiter had to save the vacancy first and then
// reopen it to enter a range. Both surfaces now share these helpers, so
// the parsing and the validation rules cannot drift apart.

export interface SalaryFormValues {
  salary_min: string;
  salary_max: string;
  salary_currency: string;
}

export interface SalaryBand {
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string | null;
}

/** Empty string → null; anything unparseable stays null (never NaN). */
export function parseSalaryInput(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

/**
 * Returns the i18n key of the violated rule, or null when the range is
 * acceptable. A half-filled range is fine — "from 100000" and "up to
 * 100000" are both legitimate postings.
 */
export function validateSalaryRange(values: SalaryFormValues): string | null {
  const min = parseSalaryInput(values.salary_min);
  const max = parseSalaryInput(values.salary_max);
  if (values.salary_min.trim() && min === null) return "vacancySalaryNotANumber";
  if (values.salary_max.trim() && max === null) return "vacancySalaryNotANumber";
  if ((min !== null && min < 0) || (max !== null && max < 0)) {
    return "vacancySalaryNegative";
  }
  if (min !== null && max !== null && min > max) {
    return "vacancySalaryRangeInverted";
  }
  return null;
}

export function isSalaryEmpty(values: SalaryFormValues): boolean {
  return (
    !values.salary_min.trim() &&
    !values.salary_max.trim() &&
    !values.salary_currency.trim()
  );
}

/**
 * Collapse the salary bands of the picked Specialization × Grade pairs
 * into one range: the lowest floor, the highest ceiling.
 *
 * Currency only carries over when every contributing band agrees — a
 * mixed-currency selection has no meaningful range, so the caller is
 * told to leave the fields alone (null) rather than shown a number in a
 * currency that only applies to half of it.
 */
export function deriveSalaryFromBands(
  bands: SalaryBand[],
): SalaryFormValues | null {
  const usable = bands.filter(
    (b) => b.salary_min !== null || b.salary_max !== null,
  );
  if (usable.length === 0) return null;

  const currencies = new Set(
    usable.map((b) => (b.salary_currency || "").trim()).filter(Boolean),
  );
  if (currencies.size > 1) return null;

  const mins = usable
    .map((b) => b.salary_min)
    .filter((v): v is number => v !== null);
  const maxes = usable
    .map((b) => b.salary_max)
    .filter((v): v is number => v !== null);

  return {
    salary_min: mins.length ? String(Math.min(...mins)) : "",
    salary_max: maxes.length ? String(Math.max(...maxes)) : "",
    salary_currency: currencies.size === 1 ? [...currencies][0] : "",
  };
}

export function sameSalary(a: SalaryFormValues, b: SalaryFormValues): boolean {
  return (
    a.salary_min === b.salary_min &&
    a.salary_max === b.salary_max &&
    a.salary_currency === b.salary_currency
  );
}
