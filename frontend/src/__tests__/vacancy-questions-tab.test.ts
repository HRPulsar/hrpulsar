// HRP-504: the vacancy Questions tab now reads one vacancy-level
// endpoint instead of fanning out per candidate against a table nothing
// writes any more. Candidate options carry real names, the competence
// filter is fed by the vacancy profile and accepts several competences
// at once.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const TAB = readFileSync(
  resolve(__dirname, "../components/recruitment/vacancy-questions-tab.tsx"),
  "utf8",
);
const FLAT = TAB.replace(/\s+/g, " ");

const PAGE = readFileSync(
  resolve(__dirname, "../app/(dashboard)/recruitment/requisitions/[id]/page.tsx"),
  "utf8",
);

describe("Vacancy questions tab (HRP-504)", () => {
  it("reads the vacancy-level question sets endpoint", () => {
    expect(FLAT).toContain(
      "`/recruitment/vacancies/${vacancyId}/question-sets`",
    );
  });

  it("no longer touches the legacy per-candidate questions API", () => {
    expect(TAB).not.toContain("/questions?");
    expect(TAB).not.toContain("CandidateQuestion");
    expect(TAB).not.toContain("QuestionCard");
  });

  it("labels candidate options by name, never by uuid", () => {
    expect(FLAT).toContain(
      "<SelectItem key={c.candidate_id} value={c.candidate_id}> {c.candidate_name || tc(\"candidate\")}",
    );
    expect(TAB).not.toContain("cv.candidate_name || cv.candidate_id");
  });

  it("fills the competence filter from the vacancy profile competences", () => {
    expect(FLAT).toContain("...(data?.competences ?? []).map((c) => ({ value: c.id, label: c.name, }))");
    expect(FLAT).toContain(
      '{ value: NO_COMPETENCE, label: t("vacancyQuestionsTabWithoutCompetency") }',
    );
  });

  it("supports selecting several competences at once", () => {
    expect(TAB).toContain("<MultiSelectFilter");
    expect(FLAT).toContain("const selected = new Set(filterCompetences);");
    expect(FLAT).toContain(
      "return q.competence_id ? selected.has(q.competence_id) : selected.has(NO_COMPETENCE);",
    );
  });

  it("keeps the filter testids the e2e catalogue documents", () => {
    expect(TAB).toContain('data-testid="vacancy-questions-filter-candidate"');
    expect(TAB).toContain('data-testid="vacancy-questions-filter-competence"');
    expect(TAB).toContain('data-testid="vacancy-questions-tab"');
  });

  it("stops the page from prefetching candidates for a prop that is gone", () => {
    expect(PAGE).toContain("<VacancyQuestionsTab vacancyId={vacancy.id} />");
    expect(PAGE).not.toContain("loadCandidateVacancies");
  });
});
