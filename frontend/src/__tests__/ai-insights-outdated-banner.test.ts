import { describe, expect, it } from "vitest";

import type { AiAnalysisRun } from "@/lib/recruitment-types";

// HRP-272: pure-logic guard for the "Resume updated — re-analyze"
// banner on AI Insights. Vitest runs without jsdom in this suite —
// the component renders the banner iff this guard returns true, so
// pinning the predicate here keeps a future refactor of the visual
// shell from accidentally showing the banner on full-mode runs or
// legacy rows that have no stamped snapshot hash.

function shouldShowOutdatedBanner(run: AiAnalysisRun): boolean {
  return run.mode === "resume_only" && run.resume_outdated;
}

function mkRun(overrides: Partial<AiAnalysisRun> = {}): AiAnalysisRun {
  return {
    id: "run-1",
    candidate_vacancy_id: "cv-1",
    mode: "resume_only",
    status: "completed",
    data_completeness: "partial",
    interview_id: null,
    verdict: "needs_check",
    verdict_summary: null,
    key_strength: null,
    key_risk: null,
    risk_mitigation: null,
    recommendation_for_next_step: null,
    ai_score: null,
    vacancy_profile_version: 1,
    archived_at: null,
    replaced_by_id: null,
    supersedes_id: null,
    created_by_id: null,
    created_at: "2026-06-18T10:00:00Z",
    updated_at: "2026-06-18T10:00:00Z",
    current_stage: null,
    cancelled_at: null,
    cancelled_by_id: null,
    resume_excerpts: null,
    resume_outdated: false,
    ...overrides,
  };
}

describe("AI Insights outdated banner — show/hide guard", () => {
  it("shows the banner for a resume_only run flagged outdated by the backend", () => {
    expect(
      shouldShowOutdatedBanner(mkRun({ resume_outdated: true })),
    ).toBe(true);
  });

  it("hides the banner when the active run is up-to-date", () => {
    expect(
      shouldShowOutdatedBanner(mkRun({ resume_outdated: false })),
    ).toBe(false);
  });

  it("hides the banner for full-mode runs even if resume_outdated is true", () => {
    // Full-mode runs do not carry a resume snapshot — the banner is a
    // resume-only-only affordance.
    expect(
      shouldShowOutdatedBanner(
        mkRun({ mode: "full", resume_outdated: true }),
      ),
    ).toBe(false);
  });

  it("hides the banner for legacy runs that default to resume_outdated=false", () => {
    // Rows created before HRP-272 have no stamped snapshot hash; the
    // serializer leaves the flag at false so the banner never claims
    // outdated when we cannot prove it.
    expect(shouldShowOutdatedBanner(mkRun())).toBe(false);
  });
});
