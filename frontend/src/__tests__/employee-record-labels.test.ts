// HRP-1066: the Education degree and the Compensation type showed their
// stored value (an English word, a wire code) instead of a label.

import { readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import {
  COMPENSATION_TYPES,
  DEGREE_OPTIONS,
  RU_DEGREE_OPTIONS,
  compensationTypeLabel,
  degreeChoices,
  degreeLabel,
} from "@/components/employees/employee-record-labels";

const t = (key: string) => `t:${key}`;

describe("degreeLabel", () => {
  it("labels every option of the select", () => {
    for (const d of [...DEGREE_OPTIONS, ...RU_DEGREE_OPTIONS])
      expect(degreeLabel(t, d)).toMatch(/^t:degree/);
    expect(degreeLabel(t, "PhD")).toBe("t:degreePhd");
  });

  it("has a label for every option in each catalog", () => {
    // Catalogs are discovered: ru.json is absent from the public repo.
    const dir = resolve(__dirname, "../../messages");
    const files = readdirSync(dir).filter((f) => f.endsWith(".json"));
    expect(files).toContain("en.json");
    for (const file of files) {
      const { employees } = JSON.parse(readFileSync(resolve(dir, file), "utf8"));
      const label = (key: string) => employees[key] ?? `missing:${key}`;
      for (const d of [...DEGREE_OPTIONS, ...RU_DEGREE_OPTIONS])
        expect(degreeLabel(label, d), `${file} ${d}`).not.toMatch(/^missing:/);
    }
  });

  it("shows a value written outside the select as it was stored", () => {
    // The import takes free text; the dev seed writes "M.S.".
    expect(degreeLabel(t, "M.S.")).toBe("M.S.");
  });
});

describe("degreeChoices", () => {
  const values = (region: string | null | undefined, current?: string) =>
    degreeChoices(t, region, current).map((c) => c.value);

  it("offers the Russian levels to an RU tenant only", () => {
    expect(values("RU")).toEqual(RU_DEGREE_OPTIONS);
    expect(values("RU")).toContain("Specialist");
    for (const region of [null, undefined, "DE", "US"])
      expect(values(region)).toEqual(DEGREE_OPTIONS);
    expect(degreeChoices(t, "RU")[3]).toEqual({
      value: "Specialist",
      label: "t:degreeSpecialist",
    });
  });

  it("keeps a stored value from outside the set selectable", () => {
    // An older record, the import's free text, the other region's set.
    expect(values("RU", "PhD")).toEqual([...RU_DEGREE_OPTIONS, "PhD"]);
    expect(values(null, "M.S.")).toEqual([...DEGREE_OPTIONS, "M.S."]);
    expect(degreeChoices(t, null, "M.S.").at(-1)).toEqual({ value: "M.S.", label: "M.S." });
    expect(values(null, "Specialist").at(-1)).toBe("Specialist");
    expect(values("RU", "Master")).toEqual(RU_DEGREE_OPTIONS);
    expect(values("RU", "")).toEqual(RU_DEGREE_OPTIONS);
  });

  it("tells an appended value apart when its label repeats one of the set", () => {
    // In ru both PhD and Candidate of Sciences read "Kandidat nauk".
    const ru = (key: string) =>
      key === "degreePhd" || key === "degreeCandidateOfSciences" ? "KN" : key;
    const choices = degreeChoices(ru, "RU", "PhD");
    expect(choices.filter((c) => c.label === "KN").map((c) => c.value)).toEqual([
      "Candidate of Sciences",
    ]);
    expect(choices.at(-1)).toEqual({ value: "PhD", label: "KN (PhD)" });
  });
});

describe("compensationTypeLabel", () => {
  it("labels each type the API accepts", () => {
    expect(COMPENSATION_TYPES.map((c) => compensationTypeLabel(t, c))).toEqual([
      "t:compTypeSalary",
      "t:compTypeBonus",
      "t:compTypeAllowance",
    ]);
  });
});
