import { describe, expect, it } from "vitest";

import {
  emptyVacancyForm,
  vacancyFormToPayload,
} from "@/app/(dashboard)/recruitment/requisitions/_components/VacancyForm";

// HRP-320: the create-vacancy form drives the competence matrix seed on the
// backend via library_refs.specialization_grade_pairs. When the recruiter
// picks Specializations × Grades the payload MUST forward grade_ids inside
// every pair — otherwise _seed_competences_from_library short-circuits and
// the Competences & indicators block lands empty (task 2 of the spec).

describe("vacancyFormToPayload", () => {
  it("omits library_refs entirely when nothing was picked", () => {
    const payload = vacancyFormToPayload({
      ...emptyVacancyForm,
      title: "Senior Backend Developer",
    });
    expect(payload.title).toBe("Senior Backend Developer");
    expect(payload.library_refs).toBeUndefined();
    expect(payload.position_id).toBeNull();
    expect(payload.specialization_ids).toEqual([]);
    expect(payload.grade_ids).toEqual([]);
    expect(payload.division_id).toBeNull();
  });

  it("forwards every chosen Specialization with the full set of Grades", () => {
    const payload = vacancyFormToPayload({
      ...emptyVacancyForm,
      title: "Senior Backend Developer",
      position_id: "pos-1",
      specialization_ids: ["spec-a", "spec-b"],
      grade_ids: ["grade-1", "grade-2"],
      division_id: "div-1",
    });
    expect(payload.position_id).toBe("pos-1");
    expect(payload.specialization_ids).toEqual(["spec-a", "spec-b"]);
    expect(payload.grade_ids).toEqual(["grade-1", "grade-2"]);
    expect(payload.division_id).toBe("div-1");
    expect(payload.library_refs).toEqual({
      position_ids: ["pos-1"],
      specialization_grade_pairs: [
        { specialization_id: "spec-a", grade_ids: ["grade-1", "grade-2"] },
        { specialization_id: "spec-b", grade_ids: ["grade-1", "grade-2"] },
      ],
      division_ids: ["div-1"],
    });
  });

  it("still emits library_refs when only a Position is picked", () => {
    // Position alone is enough for _seed_competences_from_library to load
    // GradeSpecialization rows from the Position's (spec, grade) pair.
    const payload = vacancyFormToPayload({
      ...emptyVacancyForm,
      title: "Junior QA",
      position_id: "pos-1",
    });
    expect(payload.library_refs).toEqual({
      position_ids: ["pos-1"],
      specialization_grade_pairs: [],
      division_ids: [],
    });
  });

  it("encodes Specialization-only picks as pairs with an empty grade list", () => {
    const payload = vacancyFormToPayload({
      ...emptyVacancyForm,
      title: "Junior QA",
      position_id: "pos-1",
      specialization_ids: ["spec-a"],
    });
    expect(payload.library_refs).toEqual({
      position_ids: ["pos-1"],
      specialization_grade_pairs: [
        { specialization_id: "spec-a", grade_ids: [] },
      ],
      division_ids: [],
    });
  });

  it("trims the title and converts blank task text to null", () => {
    const payload = vacancyFormToPayload({
      ...emptyVacancyForm,
      title: "  Senior Backend Developer  ",
      tasks_main: "  ",
      tasks_additional: "Pair on a real ticket",
    });
    expect(payload.title).toBe("Senior Backend Developer");
    expect(payload.tasks_main).toBeNull();
    expect(payload.tasks_additional).toEqual({ text: "Pair on a real ticket" });
  });
});
