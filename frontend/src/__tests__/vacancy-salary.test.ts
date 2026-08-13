// HRP-440: Create & Edit Vacancy gained the Salary range group that only
// the Overview block used to have, and both surfaces now share one
// parsing/validation contract plus the Specialization × Grade prefill.

import { readdirSync, readFileSync } from "node:fs";
import { basename, resolve } from "node:path";
import { describe, expect, it } from "vitest";

import {
  deriveSalaryFromBands,
  isSalaryEmpty,
  parseSalaryInput,
  sameSalary,
  validateSalaryRange,
} from "../lib/vacancy-salary";

const FORM = readFileSync(
  resolve(
    __dirname,
    "../app/(dashboard)/recruitment/requisitions/_components/VacancyForm.tsx",
  ),
  "utf8",
);
const OVERVIEW = readFileSync(
  resolve(
    __dirname,
    "../app/(dashboard)/recruitment/requisitions/_components/VacancyOverviewSection.tsx",
  ),
  "utf8",
);
const CREATE = readFileSync(
  resolve(__dirname, "../app/(dashboard)/recruitment/requisitions/new/page.tsx"),
  "utf8",
);
const EDIT = readFileSync(
  resolve(
    __dirname,
    "../app/(dashboard)/recruitment/requisitions/[id]/edit/page.tsx",
  ),
  "utf8",
);

// Catalogs are discovered rather than hardcoded: ru.json is enterprise-only
// and absent from the public repo, where a fixed readFileSync would fail
// collection with ENOENT. Same approach as i18n-catalog-parity.test.ts.
const MESSAGES_DIR = resolve(__dirname, "../../messages");

const CATALOGS: [string, { recruitment: Record<string, string> }][] =
  readdirSync(MESSAGES_DIR)
    .filter((file) => file.endsWith(".json"))
    .sort()
    .map((file) => [
      basename(file, ".json"),
      JSON.parse(readFileSync(resolve(MESSAGES_DIR, file), "utf8")),
    ]);

const salary = (min: string, max: string, currency = "") => ({
  salary_min: min,
  salary_max: max,
  salary_currency: currency,
});

describe("parseSalaryInput", () => {
  it("treats blank input as no value", () => {
    expect(parseSalaryInput("")).toBeNull();
    expect(parseSalaryInput("   ")).toBeNull();
  });

  it("never returns NaN for garbage", () => {
    expect(parseSalaryInput("abc")).toBeNull();
  });

  it("parses plain numbers", () => {
    expect(parseSalaryInput("120000")).toBe(120000);
    expect(parseSalaryInput(" 90.5 ")).toBe(90.5);
  });
});

describe("validateSalaryRange", () => {
  it("accepts an empty or half-filled range", () => {
    expect(validateSalaryRange(salary("", ""))).toBeNull();
    expect(validateSalaryRange(salary("100000", ""))).toBeNull();
    expect(validateSalaryRange(salary("", "200000"))).toBeNull();
  });

  it("accepts min below max and min equal to max", () => {
    expect(validateSalaryRange(salary("100", "200"))).toBeNull();
    expect(validateSalaryRange(salary("150", "150"))).toBeNull();
  });

  it("rejects an inverted range", () => {
    expect(validateSalaryRange(salary("300", "200"))).toBe(
      "vacancySalaryRangeInverted",
    );
  });

  it("rejects negatives and non-numbers", () => {
    expect(validateSalaryRange(salary("-5", ""))).toBe("vacancySalaryNegative");
    expect(validateSalaryRange(salary("abc", ""))).toBe(
      "vacancySalaryNotANumber",
    );
  });

  it("ships every message it can return, in every shipped catalog", () => {
    for (const key of [
      "vacancySalaryRangeInverted",
      "vacancySalaryNegative",
      "vacancySalaryNotANumber",
    ]) {
      for (const [locale, catalog] of CATALOGS) {
        expect(catalog.recruitment[key], `${locale}.${key}`).toBeTruthy();
      }
    }
  });
});

describe("deriveSalaryFromBands", () => {
  it("returns null when no band carries a number", () => {
    expect(deriveSalaryFromBands([])).toBeNull();
    expect(
      deriveSalaryFromBands([
        { salary_min: null, salary_max: null, salary_currency: "EUR" },
      ]),
    ).toBeNull();
  });

  it("spans the lowest floor and the highest ceiling", () => {
    expect(
      deriveSalaryFromBands([
        { salary_min: 100, salary_max: 200, salary_currency: "EUR" },
        { salary_min: 150, salary_max: 400, salary_currency: "EUR" },
      ]),
    ).toEqual({
      salary_min: "100",
      salary_max: "400",
      salary_currency: "EUR",
    });
  });

  it("refuses to merge bands priced in different currencies", () => {
    expect(
      deriveSalaryFromBands([
        { salary_min: 100, salary_max: 200, salary_currency: "EUR" },
        { salary_min: 150, salary_max: 400, salary_currency: "USD" },
      ]),
    ).toBeNull();
  });

  it("keeps a one-sided band one-sided", () => {
    expect(
      deriveSalaryFromBands([
        { salary_min: 100, salary_max: null, salary_currency: "EUR" },
      ]),
    ).toEqual({ salary_min: "100", salary_max: "", salary_currency: "EUR" });
  });
});

describe("isSalaryEmpty / sameSalary", () => {
  it("detects an untouched group", () => {
    expect(isSalaryEmpty(salary("", ""))).toBe(true);
    expect(isSalaryEmpty(salary("", "", "EUR"))).toBe(false);
  });

  it("compares all three fields", () => {
    expect(sameSalary(salary("1", "2", "EUR"), salary("1", "2", "EUR"))).toBe(
      true,
    );
    expect(sameSalary(salary("1", "2", "EUR"), salary("1", "2", "USD"))).toBe(
      false,
    );
  });
});

describe("Form wiring (HRP-440)", () => {
  it("puts the three salary fields on the create/edit form", () => {
    expect(FORM).toContain('data-testid="recruitment-vacancy-input-salary-min"');
    expect(FORM).toContain('data-testid="recruitment-vacancy-input-salary-max"');
    expect(FORM).toContain(
      'data-testid="recruitment-vacancy-input-salary-currency"',
    );
    expect(FORM).toContain('t("vacancyFieldSalaryRange")');
  });

  it("sends the salary fields in the payload and reads them back", () => {
    expect(FORM).toContain("salary_min: parseSalaryInput(values.salary_min),");
    expect(FORM).toContain("salary_max: parseSalaryInput(values.salary_max),");
    expect(FORM).toContain(
      "salary_currency: values.salary_currency.trim() || null,",
    );
    expect(FORM).toContain("salary_min: numberText(vacancy.salary_min),");
  });

  it("prefills from the Specialization × Grade bands without clobbering edits", () => {
    expect(FORM).toContain("`/specializations/${specId}/grades`");
    expect(FORM).toContain("deriveSalaryFromBands(bands)");
    expect(FORM.replace(/\s+/g, " ")).toContain(
      "const untouched = isSalaryEmpty(currentSalary) || (autofilledSalary.current !== null && sameSalary(currentSalary, autofilledSalary.current));",
    );
  });

  it("blocks saving an invalid range on all three surfaces", () => {
    for (const source of [CREATE, EDIT, OVERVIEW]) {
      expect(source).toContain("validateSalaryRange(form)");
      expect(source).toContain("toast.error(t(salaryError));");
    }
  });

  it("keeps the Overview block on the shared parser", () => {
    expect(OVERVIEW).toContain("parseSalaryInput(current.salary_min)");
    expect(OVERVIEW).not.toContain(
      "current.salary_min ? Number(current.salary_min) : null",
    );
  });
});
