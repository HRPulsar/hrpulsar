/**
 * HRP-1066: labels for values the employee card's Education and
 * Compensation blocks store, keyed in the `employees` namespace.
 *
 * The degree is stored as the English word the select offers (the set
 * follows the tenant region, see degreeChoices); the import
 * writes "Bachelor" by default and free text otherwise, the dev seed
 * "M.S." - so a value outside the set shows as it was stored. The
 * compensation type is a wire code (salary | bonus | allowance).
 */

type Translate = (key: string) => string;

/** The Degree select's options, each saved verbatim in `education.degree`. */
export const DEGREE_OPTIONS = [
  "Secondary",
  "Vocational",
  "Bachelor",
  "Master",
  "PhD",
  "Doctorate",
  "Other",
] as const;

/**
 * The levels of the Russian education law plus the academic degrees, for a
 * tenant whose region is RU. Values already in DEGREE_OPTIONS are reused.
 */
export const RU_DEGREE_OPTIONS = [
  "Secondary",
  "Vocational",
  "Bachelor",
  "Specialist",
  "Master",
  "Postgraduate",
  "Candidate of Sciences",
  "Doctor of Sciences",
  "Other",
] as const;

const DEGREE_KEYS: Record<string, string> = {
  Secondary: "degreeSecondary",
  Vocational: "degreeVocational",
  Bachelor: "degreeBachelor",
  Master: "degreeMaster",
  PhD: "degreePhd",
  Doctorate: "degreeDoctorate",
  Other: "degreeOther",
  Specialist: "degreeSpecialist",
  Postgraduate: "degreePostgraduate",
  "Candidate of Sciences": "degreeCandidateOfSciences",
  "Doctor of Sciences": "degreeDoctorOfSciences",
};

export function degreeLabel(t: Translate, degree: string): string {
  const key = DEGREE_KEYS[degree];
  return key ? t(key) : degree;
}

/**
 * The Degree select's choices for the tenant's region (ISO 3166-1, null when
 * not set). A stored value outside the set - an older record, an import, the
 * other region's set - is appended, so the edit dialog keeps it selected;
 * where its label repeats one of the set (PhD reads "Candidate of Sciences"
 * in ru) the stored value is added to tell the two apart.
 */
export function degreeChoices(
  t: Translate,
  region: string | null | undefined,
  current = "",
): { value: string; label: string }[] {
  const base: readonly string[] = region === "RU" ? RU_DEGREE_OPTIONS : DEGREE_OPTIONS;
  const choices = base.map((value) => ({ value, label: degreeLabel(t, value) }));
  if (current && !base.includes(current)) {
    const label = degreeLabel(t, current);
    const clash = choices.some((c) => c.label === label);
    choices.push({ value: current, label: clash ? `${label} (${current})` : label });
  }
  return choices;
}

export const COMPENSATION_TYPES = ["salary", "bonus", "allowance"] as const;

const COMPENSATION_TYPE_KEYS: Record<string, string> = {
  salary: "compTypeSalary",
  bonus: "compTypeBonus",
  allowance: "compTypeAllowance",
};

export function compensationTypeLabel(t: Translate, type: string): string {
  const key = COMPENSATION_TYPE_KEYS[type];
  return key ? t(key) : type;
}
