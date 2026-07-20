import { describe, expect, it } from "vitest";

import {
  STEP_COPY,
  STEP_ORDER,
} from "@/components/recruitment/onboarding-banner";

describe("RecruitmentOnboardingBanner — step mapping", () => {
  it("orders the five active steps in the expected flow", () => {
    expect(STEP_ORDER).toEqual([
      "welcome",
      "vacancy_created",
      "candidate_invited",
      "interview_scheduled",
      "report_reviewed",
    ]);
  });

  it("never exposes the terminal `done` step (banner hides on done)", () => {
    expect(STEP_ORDER).not.toContain("done");
    expect(Object.keys(STEP_COPY)).not.toContain("done");
  });

  it("provides title, hint, cta and href for every active step", () => {
    for (const step of STEP_ORDER) {
      const copy = STEP_COPY[step];
      expect(copy.title, `${step}.title`).toMatch(/\S/);
      expect(copy.hint, `${step}.hint`).toMatch(/\S/);
      expect(copy.cta, `${step}.cta`).toMatch(/\S/);
      expect(copy.href, `${step}.href`).toMatch(/^\/recruitment\//);
    }
  });

  it("routes the welcome CTA to the new-vacancy wizard", () => {
    expect(STEP_COPY.welcome.href).toBe("/recruitment/requisitions/new");
  });

  it("routes the final step CTA to the reports section", () => {
    expect(STEP_COPY.report_reviewed.href).toBe("/recruitment/reports");
  });
});
