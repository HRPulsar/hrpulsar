import { describe, expect, it } from "vitest";

import type { TopupEligibility } from "@/lib/recruitment-types";

// HRP-269: pure-logic guards for the AI Insights split-button on the
// candidate card. Vitest runs without jsdom, so we re-implement the
// same decision tree the component uses and pin it here — keeps the
// "Resume + interview" dropdown item from regressing back to a single
// always-enabled action and asserts the API payload shape.

interface SplitButtonState {
  primaryDisabled: boolean;
  fullModeDisabled: boolean;
  fullModeTooltip: string;
}

function deriveSplitButtonState(args: {
  selectedCvId: string | null;
  busy: boolean;
  inFlight: boolean;
  eligibility: TopupEligibility | null;
}): SplitButtonState {
  const { selectedCvId, busy, inFlight, eligibility } = args;
  const disabled = !selectedCvId || busy || inFlight;
  const hasTranscribedInterview = !!eligibility?.transcribed_interview_id;
  const topupEligible = !!eligibility?.eligible;
  const fullModeBlocked = !hasTranscribedInterview || topupEligible;
  const fullModeTooltip = !hasTranscribedInterview
    ? "Upload and transcribe an interview to enable full analysis"
    : topupEligible
      ? "Use the +20-cr upgrade above — full analysis here would charge 40 cr"
      : "Run resume + interview analysis (40 cr)";
  return {
    primaryDisabled: disabled,
    fullModeDisabled: disabled || fullModeBlocked,
    fullModeTooltip,
  };
}

function buildAnalyzePayload(
  mode: "resume_only" | "topup_to_full" | "full",
  eligibility: TopupEligibility | null,
): Record<string, unknown> | null {
  if (mode === "full") {
    const interviewId = eligibility?.transcribed_interview_id ?? null;
    if (!interviewId) return null;
    return { mode, interview_id: interviewId };
  }
  return { mode };
}

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
    ...overrides,
  };
}

describe("AnalyzeSplitButton state derivation", () => {
  it("disables both actions when no candidate-vacancy is selected", () => {
    const state = deriveSplitButtonState({
      selectedCvId: null,
      busy: false,
      inFlight: false,
      eligibility: null,
    });
    expect(state.primaryDisabled).toBe(true);
    expect(state.fullModeDisabled).toBe(true);
  });

  it("disables both actions while an in-flight run exists", () => {
    const state = deriveSplitButtonState({
      selectedCvId: "cv-1",
      busy: false,
      inFlight: true,
      eligibility: mkEligibility({
        transcribed_interview_id: "interview-1",
      }),
    });
    expect(state.primaryDisabled).toBe(true);
    expect(state.fullModeDisabled).toBe(true);
  });

  it("keeps the full-mode item disabled with the upload tooltip when no transcript exists", () => {
    const state = deriveSplitButtonState({
      selectedCvId: "cv-1",
      busy: false,
      inFlight: false,
      eligibility: mkEligibility({ transcribed_interview_id: null }),
    });
    expect(state.primaryDisabled).toBe(false);
    expect(state.fullModeDisabled).toBe(true);
    expect(state.fullModeTooltip).toMatch(/upload and transcribe/i);
  });

  it("enables the full-mode item when a transcribed interview is available", () => {
    const state = deriveSplitButtonState({
      selectedCvId: "cv-1",
      busy: false,
      inFlight: false,
      eligibility: mkEligibility({
        transcribed_interview_id: "interview-1",
      }),
    });
    expect(state.primaryDisabled).toBe(false);
    expect(state.fullModeDisabled).toBe(false);
    expect(state.fullModeTooltip).toMatch(/40 cr/i);
  });

  it("does not require a resume-only baseline — eligible=false still enables the full-mode item when a transcript exists", () => {
    const state = deriveSplitButtonState({
      selectedCvId: "cv-1",
      busy: false,
      inFlight: false,
      eligibility: mkEligibility({
        eligible: false,
        reason: "no_active_resume_only_run",
        transcribed_interview_id: "interview-1",
      }),
    });
    expect(state.fullModeDisabled).toBe(false);
  });

  it("disables the full-mode item when topup is eligible (cheaper +20 cr upgrade exists)", () => {
    const state = deriveSplitButtonState({
      selectedCvId: "cv-1",
      busy: false,
      inFlight: false,
      eligibility: mkEligibility({
        eligible: true,
        transcribed_interview_id: "interview-1",
      }),
    });
    expect(state.fullModeDisabled).toBe(true);
    expect(state.fullModeTooltip).toMatch(/\+20-cr upgrade/i);
  });
});

describe("AnalyzeSplitButton dispatch payload", () => {
  it("dispatches resume_only without an interview id", () => {
    const payload = buildAnalyzePayload(
      "resume_only",
      mkEligibility({ transcribed_interview_id: "interview-1" }),
    );
    expect(payload).toEqual({ mode: "resume_only" });
  });

  it("dispatches full with the transcribed interview id", () => {
    const payload = buildAnalyzePayload(
      "full",
      mkEligibility({ transcribed_interview_id: "interview-7" }),
    );
    expect(payload).toEqual({ mode: "full", interview_id: "interview-7" });
  });

  it("refuses to dispatch full when no transcribed interview is available", () => {
    const payload = buildAnalyzePayload(
      "full",
      mkEligibility({ transcribed_interview_id: null }),
    );
    expect(payload).toBeNull();
  });

  it("dispatches topup_to_full without an interview id (server derives it)", () => {
    const payload = buildAnalyzePayload(
      "topup_to_full",
      mkEligibility({ transcribed_interview_id: "interview-1" }),
    );
    expect(payload).toEqual({ mode: "topup_to_full" });
  });
});
