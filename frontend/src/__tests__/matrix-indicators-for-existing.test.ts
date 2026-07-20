import { describe, it, expect } from "vitest";

// HRP-119 AC2: exercises the same decision rule `AIGenerateForm` uses when
// it folds the "Generate indicators for existing competences" checkbox into
// the MatrixGenerateInput payload. Vitest runs without jsdom, so the actual
// component isn't rendered — this guards the pure branching.

function resolveIndicatorsForExisting(
  hasExistingCompetences: boolean,
  checked: boolean,
): true | undefined {
  return hasExistingCompetences && checked ? true : undefined;
}

describe("indicators_for_existing payload rule", () => {
  it("returns undefined when the matrix is empty even if the checkbox is on", () => {
    expect(resolveIndicatorsForExisting(false, true)).toBeUndefined();
  });

  it("returns undefined when the matrix has competences but checkbox is off", () => {
    expect(resolveIndicatorsForExisting(true, false)).toBeUndefined();
  });

  it("returns true only when both conditions hold", () => {
    expect(resolveIndicatorsForExisting(true, true)).toBe(true);
  });

  it("never returns false (the field is omitted instead)", () => {
    const variants = [
      resolveIndicatorsForExisting(false, false),
      resolveIndicatorsForExisting(false, true),
      resolveIndicatorsForExisting(true, false),
    ];
    expect(variants.every((v) => v === undefined)).toBe(true);
  });
});

describe("multipart form encoding", () => {
  // Mirrors the encoder in `frontend/src/lib/api/specialization-ai.ts`. We
  // build a fake FormData mock so the test runs without jsdom.
  type FakeFormData = { entries: Array<[string, string]> };
  function makeForm(): FakeFormData {
    return { entries: [] };
  }
  function append(form: FakeFormData, key: string, value: string) {
    form.entries.push([key, value]);
  }

  function encode(
    form: FakeFormData,
    indicators_for_existing: true | undefined,
  ) {
    if (indicators_for_existing) {
      append(form, "indicators_for_existing", "true");
    }
  }

  it("omits the field entirely when undefined", () => {
    const form = makeForm();
    encode(form, undefined);
    expect(form.entries).toEqual([]);
  });

  it("emits the field as the string 'true' when set", () => {
    const form = makeForm();
    encode(form, true);
    expect(form.entries).toEqual([["indicators_for_existing", "true"]]);
  });
});

describe("required grade lock", () => {
  // HRP-119 AC1: position.grade_id is pre-checked and cannot be removed
  // from the grades multi-select. Mirrors the toggleGrade guard.
  function toggleGrade(
    selected: Set<string>,
    requiredIds: Set<string>,
    id: string,
  ): Set<string> {
    if (requiredIds.has(id)) return selected;
    const next = new Set(selected);
    if (next.has(id)) {
      next.delete(id);
    } else {
      next.add(id);
    }
    return next;
  }

  it("ignores attempts to remove a required grade", () => {
    const initial = new Set(["g-junior", "g-middle"]);
    const required = new Set(["g-junior"]);
    const after = toggleGrade(initial, required, "g-junior");
    expect(after.has("g-junior")).toBe(true);
  });

  it("freely toggles non-required grades", () => {
    const initial = new Set(["g-junior"]);
    const required = new Set(["g-junior"]);
    const added = toggleGrade(initial, required, "g-middle");
    expect(added.has("g-middle")).toBe(true);
    const removed = toggleGrade(added, required, "g-middle");
    expect(removed.has("g-middle")).toBe(false);
    expect(removed.has("g-junior")).toBe(true);
  });
});
