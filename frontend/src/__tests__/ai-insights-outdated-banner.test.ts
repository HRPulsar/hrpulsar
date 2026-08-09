import { describe, expect, it } from "vitest";

import { analysisStalenessKind } from "@/lib/recruitment-types";
import type { TopupEligibility } from "@/lib/recruitment-types";

// HRP-489 / HRP-492: AI Insights shows at most one "this analysis no
// longer describes the current inputs" banner, and which one it is
// decides both the wording and the action offered. The tickets pin the
// order explicitly (resume → competences → age), with a newer
// transcript last because it is the only case whose fix is a specific
// mode rather than any fresh analysis.
//
// This exercises the real exported predicate — the component renders
// off its return value, so pinning it here is enough to keep the
// priority from drifting.

function mkEligibility(
  overrides: Partial<TopupEligibility> = {},
): TopupEligibility {
  return {
    eligible: false,
    reason: null,
    active_run_id: null,
    interview_id: null,
    transcribed_interview_id: null,
    age_days: null,
    window_days: null,
    stored_version: null,
    current_version: null,
    active_run_mode: "resume_only",
    resume_outdated: false,
    profile_outdated: false,
    analysis_expired: false,
    transcript_outdated: false,
    newer_transcribed_interview_id: null,
    ...overrides,
  };
}

describe("AI Insights staleness banner — which one shows", () => {
  it("shows nothing while every signal is clear", () => {
    expect(analysisStalenessKind(mkEligibility())).toBeNull();
  });

  it("shows nothing before the eligibility payload arrives", () => {
    expect(analysisStalenessKind(null)).toBeNull();
  });

  it("flags a re-parsed resume", () => {
    expect(
      analysisStalenessKind(mkEligibility({ resume_outdated: true })),
    ).toBe("resume");
  });

  it("flags edited vacancy competences", () => {
    expect(
      analysisStalenessKind(mkEligibility({ profile_outdated: true })),
    ).toBe("profile");
  });

  it("flags a run past the 30-day window", () => {
    expect(
      analysisStalenessKind(mkEligibility({ analysis_expired: true })),
    ).toBe("expired");
  });

  it("flags a transcript the full run never saw", () => {
    expect(
      analysisStalenessKind(
        mkEligibility({
          active_run_mode: "full",
          transcript_outdated: true,
          newer_transcribed_interview_id: "interview-2",
        }),
      ),
    ).toBe("transcript");
  });

  it("puts a changed resume ahead of changed competences", () => {
    expect(
      analysisStalenessKind(
        mkEligibility({ resume_outdated: true, profile_outdated: true }),
      ),
    ).toBe("resume");
  });

  it("puts changed competences ahead of an expired window", () => {
    expect(
      analysisStalenessKind(
        mkEligibility({ profile_outdated: true, analysis_expired: true }),
      ),
    ).toBe("profile");
  });

  it("puts an expired window ahead of a newer transcript", () => {
    expect(
      analysisStalenessKind(
        mkEligibility({
          active_run_mode: "full",
          analysis_expired: true,
          transcript_outdated: true,
        }),
      ),
    ).toBe("expired");
  });

  it("keeps the documented order when all four fire at once", () => {
    expect(
      analysisStalenessKind(
        mkEligibility({
          resume_outdated: true,
          profile_outdated: true,
          analysis_expired: true,
          transcript_outdated: true,
        }),
      ),
    ).toBe("resume");
  });

  it("treats a legacy payload without the staleness block as clean", () => {
    // Runs analysed before HRP-489 carry no snapshot to compare
    // against; the backend leaves every flag false rather than
    // guessing, and the banner must not appear on a guess.
    const legacy = {
      eligible: false,
      reason: "no_transcribed_interview",
      active_run_id: "run-1",
      interview_id: null,
      transcribed_interview_id: null,
      age_days: null,
      window_days: null,
      stored_version: null,
      current_version: null,
    } as TopupEligibility;
    expect(analysisStalenessKind(legacy)).toBeNull();
  });
});
