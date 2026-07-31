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

  // HRP-476: the wording moved into the `recruitment` i18n namespace —
  // the map now carries keys, so pin the keys instead of the English copy.
  it("provides title, hint, cta keys and href for every active step", () => {
    for (const step of STEP_ORDER) {
      const copy = STEP_COPY[step];
      expect(copy.titleKey, `${step}.titleKey`).toMatch(/\S/);
      expect(copy.hintKey, `${step}.hintKey`).toMatch(/\S/);
      expect(copy.ctaKey, `${step}.ctaKey`).toMatch(/\S/);
      expect(copy.href, `${step}.href`).toMatch(/^\/recruitment\//);
    }
  });

  it("maps every active step to its own i18n keys", () => {
    expect(STEP_ORDER.map((step) => STEP_COPY[step].titleKey)).toEqual([
      "onboardingWelcomeTitle",
      "onboardingVacancyCreatedTitle",
      "onboardingCandidateInvitedTitle",
      "onboardingInterviewScheduledTitle",
      "onboardingReportReviewedTitle",
    ]);
    expect(STEP_ORDER.map((step) => STEP_COPY[step].hintKey)).toEqual([
      "onboardingWelcomeHint",
      "onboardingVacancyCreatedHint",
      "onboardingCandidateInvitedHint",
      "onboardingInterviewScheduledHint",
      "onboardingReportReviewedHint",
    ]);
    expect(STEP_ORDER.map((step) => STEP_COPY[step].ctaKey)).toEqual([
      "onboardingWelcomeCta",
      "onboardingVacancyCreatedCta",
      "onboardingCandidateInvitedCta",
      "onboardingInterviewScheduledCta",
      "onboardingReportReviewedCta",
    ]);
  });

  it("routes the welcome CTA to the new-vacancy wizard", () => {
    expect(STEP_COPY.welcome.href).toBe("/recruitment/requisitions/new");
  });

  it("routes the final step CTA to the reports section", () => {
    expect(STEP_COPY.report_reviewed.href).toBe("/recruitment/reports");
  });
});
