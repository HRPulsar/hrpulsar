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

// HRP-440: a row of the Specialization page's grade matrix.
export interface SpecializationGradeRow {
  grade_id: string;
  salary_min?: number | null;
  salary_max?: number | null;
  salary_currency?: string | null;
}

/**
 * The range the current Specialization × Grade selection implies, or null
 * when the library has nothing usable to say about it (no pick, no band on
 * the picked pairs, or bands in mixed currencies).
 *
 * The grade fetch is injected rather than imported so this stays a pure
 * function of its inputs — `useSalaryAutofill` passes the API client.
 * A specialization that fails to load contributes no band instead of
 * failing the whole recompute: the other picks still carry a range.
 */
export async function deriveSalaryForSelection(
  specializationIds: string[],
  gradeIds: string[],
  fetchGrades: (specializationId: string) => Promise<SpecializationGradeRow[]>,
): Promise<SalaryFormValues | null> {
  if (specializationIds.length === 0 || gradeIds.length === 0) return null;
  const wanted = new Set(gradeIds);
  const bands: SalaryBand[] = [];
  for (const specializationId of specializationIds) {
    try {
      for (const row of await fetchGrades(specializationId)) {
        if (!wanted.has(row.grade_id)) continue;
        bands.push({
          salary_min: row.salary_min ?? null,
          salary_max: row.salary_max ?? null,
          salary_currency: row.salary_currency ?? null,
        });
      }
    } catch {
      // Unreadable specialization — no band, not a failed recompute.
    }
  }
  return deriveSalaryFromBands(bands);
}
