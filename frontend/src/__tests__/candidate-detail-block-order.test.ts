// HRP-424: the right-hand column of the candidate page must follow the
// sourcing timeline:
//   Parsed resume -> Vacancy applications -> AI Insights ->
//   Interview questions -> Interviews -> Manager assessments
// The HRP-205 hiring-manager flag still lifts the questions to the top,
// but the remaining blocks keep the chronological order underneath it.
//
// The page can't be mounted under vitest (heavy data deps), so the order
// is pinned by source-grep, as with the sibling structural tests.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const SOURCE = readFileSync(
  resolve(__dirname, "../app/(dashboard)/recruitment/candidates/[id]/page.tsx"),
  "utf8",
);

const FLAT = SOURCE.replace(/\s+/g, " ");

describe("Candidate detail block order (HRP-424)", () => {
  it("renders the applications card from the ordered list, not inline", () => {
    // Exactly one render site, and it carries a key => it lives in the array.
    expect(FLAT).toContain('<VacancyApplicationsCard key="vacancy-applications"');
    expect(FLAT.match(/<VacancyApplicationsCard/g)).toHaveLength(1);
    expect(FLAT).not.toContain("<VacancyApplicationsCard card={card} />");
  });

  it("uses the chronological default order", () => {
    expect(FLAT).toContain(
      ": [ resumeSection, applicationsSection, insightsSection, questionsSection, ];",
    );
  });

  it("keeps questions on top for hiring managers with the flag on", () => {
    expect(FLAT).toContain(
      "questionsAboveResume && isHiringManager ? [ questionsSection, resumeSection, applicationsSection, insightsSection, ]",
    );
  });

  it("keeps interviews and manager assessments last, in that order", () => {
    const applications = FLAT.indexOf("<VacancyApplicationsCard");
    const interviews = FLAT.indexOf("<CandidateInterviewsSection");
    const assessments = FLAT.indexOf("<ManagerAssessmentSection");
    expect(applications).toBeGreaterThan(-1);
    expect(interviews).toBeGreaterThan(applications);
    expect(assessments).toBeGreaterThan(interviews);
  });
});
