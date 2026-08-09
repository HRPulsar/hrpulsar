// @vitest-environment jsdom
//
// HRP-488 / HRP-489 / HRP-492 — what the AI Insights block actually
// renders. The sibling suites pin the pure decision functions; this one
// mounts the real component so a refactor of the visual shell cannot
// quietly reintroduce the controls the tickets removed (the refresh
// icon, the `data:` chip, the footer that repeated Analyze) or drop the
// ones they added.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import type {
  AiAnalysisRun,
  TopupEligibility,
} from "@/lib/recruitment-types";

const runs: AiAnalysisRun[] = [];
let eligibility: TopupEligibility | null = null;

vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {},
  api: {
    get: vi.fn((url: string) =>
      Promise.resolve(url.includes("topup-eligibility") ? eligibility : runs),
    ),
    post: vi.fn(() => Promise.resolve({ status: "queued" })),
  },
}));

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ user: { deployment_mode: "saas" } }),
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

const { AiInsightsSection } = await import(
  "@/components/recruitment/ai-insights-section"
);

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  runs.length = 0;
  eligibility = null;
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

const APPLICATION = {
  cv_id: "cv-1",
  vacancy_id: "vac-1",
  vacancy_title: "QA Engineer",
  stage_id: null,
  stage_name: null,
  stage_type: null,
  status: "active",
  manager_score: null,
  ai_score: null,
  ai_verdict: "pending" as const,
  ai_verdict_summary: null,
  added_at: "2026-08-01T10:00:00Z",
};

function mkRun(overrides: Partial<AiAnalysisRun> = {}): AiAnalysisRun {
  return {
    id: "run-1",
    candidate_vacancy_id: "cv-1",
    mode: "resume_only",
    status: "completed",
    data_completeness: "partial",
    interview_id: null,
    verdict: "needs_check",
    verdict_summary: "Solid on paper.",
    key_strength: null,
    key_risk: null,
    risk_mitigation: null,
    recommendation_for_next_step: null,
    ai_score: 0.42,
    vacancy_profile_version: 1,
    archived_at: null,
    replaced_by_id: null,
    supersedes_id: null,
    created_by_id: null,
    created_at: "2026-08-01T10:00:00Z",
    updated_at: "2026-08-01T10:00:00Z",
    current_stage: null,
    cancelled_at: null,
    cancelled_by_id: null,
    resume_excerpts: null,
    resume_outdated: false,
    ...overrides,
  };
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
    active_run_mode: "resume_only",
    resume_outdated: false,
    profile_outdated: false,
    analysis_expired: false,
    transcript_outdated: false,
    newer_transcribed_interview_id: null,
    ...overrides,
  };
}

async function render(hasParsedResume: boolean) {
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <AiInsightsSection
          candidateId="cand-1"
          vacancyApplications={[APPLICATION]}
          hasParsedResume={hasParsedResume}
        />
      </NextIntlClientProvider>,
    );
  });
  // Flush the eligibility + runs fetches kicked off on mount.
  await act(async () => {
    await Promise.resolve();
  });
}

const byTestId = (id: string) =>
  container.querySelector(`[data-testid="${id}"]`);

describe("AI Insights — empty state (HRP-488)", () => {
  it("keeps Analyze disabled and asks for a resume when there is none", async () => {
    eligibility = mkEligibility();
    await render(false);

    const empty = byTestId("candidate-section-ai-insights-empty-state");
    expect(empty).not.toBeNull();
    expect(empty!.textContent).toContain("No analysis yet");
    expect(empty!.textContent).toContain("Upload or parse a resume");

    const trigger = byTestId(
      "candidate-section-ai-insights-analyze-menu-trigger",
    ) as HTMLButtonElement;
    // Visible but dead: the option stays discoverable, pressing it could
    // only 409.
    expect(trigger).not.toBeNull();
    expect(trigger.disabled).toBe(true);
  });

  it("enables Analyze and changes the hint once a resume is parsed", async () => {
    eligibility = mkEligibility();
    await render(true);

    const empty = byTestId("candidate-section-ai-insights-empty-state");
    expect(empty!.textContent).toContain("Click Analyze");
    expect(empty!.textContent).not.toContain("Upload or parse a resume");

    const trigger = byTestId(
      "candidate-section-ai-insights-analyze-menu-trigger",
    ) as HTMLButtonElement;
    expect(trigger.disabled).toBe(false);
  });

  it("puts the action inside the empty state, not in a footer", async () => {
    eligibility = mkEligibility();
    await render(true);

    const empty = byTestId("candidate-section-ai-insights-empty-state")!;
    expect(
      empty.querySelector(
        '[data-testid="candidate-section-ai-insights-analyze-menu-trigger"]',
      ),
    ).not.toBeNull();
    // Exactly one Analyze control on the whole section.
    expect(
      container.querySelectorAll(
        '[data-testid="candidate-section-ai-insights-analyze-menu-trigger"]',
      ),
    ).toHaveLength(1);
  });
});

describe("AI Insights — removed chrome (HRP-489, HRP-492)", () => {
  it("has no refresh control", async () => {
    runs.push(mkRun());
    eligibility = mkEligibility();
    await render(true);

    const refresh = Array.from(container.querySelectorAll("button")).filter(
      (b) => /refresh/i.test(b.getAttribute("aria-label") ?? ""),
    );
    expect(refresh).toHaveLength(0);
  });

  it("has no data-completeness chip next to the mode badge", async () => {
    runs.push(mkRun({ data_completeness: "partial" }));
    eligibility = mkEligibility();
    await render(true);

    expect(byTestId("ai-analysis-mode-badge-resume_only")).not.toBeNull();
    expect(container.textContent).not.toContain("data: partial");
  });

  it("hides the history button until there is history", async () => {
    eligibility = mkEligibility();
    await render(true);
    expect(byTestId("ai-analysis-history-btn")).toBeNull();
  });

  it("shows the history button once a run exists", async () => {
    runs.push(mkRun());
    eligibility = mkEligibility();
    await render(true);
    expect(byTestId("ai-analysis-history-btn")).not.toBeNull();
  });

  it("drops the Analyze control entirely from a settled full run", async () => {
    // HRP-492 case 1: nothing to re-run, so nothing is offered.
    runs.push(mkRun({ mode: "full", verdict: "recommended" }));
    eligibility = mkEligibility({ active_run_mode: "full" });
    await render(true);

    expect(
      byTestId("candidate-section-ai-insights-analyze-menu-trigger"),
    ).toBeNull();
    expect(byTestId("ai-analysis-outdated-banner")).toBeNull();
  });
});

describe("AI Insights — staleness banners (HRP-489, HRP-492)", () => {
  it("offers the split-button for a re-parsed resume", async () => {
    runs.push(mkRun());
    eligibility = mkEligibility({ resume_outdated: true });
    await render(true);

    const banner = byTestId("ai-analysis-outdated-banner")!;
    expect(banner.getAttribute("data-staleness")).toBe("resume");
    expect(banner.textContent).toContain("Resume was updated");
    expect(
      banner.querySelector(
        '[data-testid="candidate-section-ai-insights-analyze-menu-trigger"]',
      ),
    ).not.toBeNull();
  });

  it("names edited vacancy competences", async () => {
    runs.push(mkRun());
    eligibility = mkEligibility({ profile_outdated: true });
    await render(true);

    const banner = byTestId("ai-analysis-outdated-banner")!;
    expect(banner.getAttribute("data-staleness")).toBe("profile");
    expect(banner.textContent).toContain("competences");
  });

  it("offers only a full re-run for a transcript the analysis never saw", async () => {
    // HRP-492 case 2 — a resume-only re-run would not consume the new
    // transcript, so the menu would be a trap here.
    runs.push(mkRun({ mode: "full" }));
    eligibility = mkEligibility({
      active_run_mode: "full",
      transcript_outdated: true,
      newer_transcribed_interview_id: "interview-2",
      transcribed_interview_id: "interview-2",
    });
    await render(true);

    const banner = byTestId("ai-analysis-outdated-banner")!;
    expect(banner.getAttribute("data-staleness")).toBe("transcript");
    expect(banner.textContent).toContain("Interview transcript was updated");
    expect(byTestId("ai-analysis-reanalyze-full-btn")).not.toBeNull();
    expect(
      banner.querySelector(
        '[data-testid="candidate-section-ai-insights-analyze-menu-trigger"]',
      ),
    ).toBeNull();
  });

  it("shows no banner while every signal is clear", async () => {
    runs.push(mkRun());
    eligibility = mkEligibility();
    await render(true);
    expect(byTestId("ai-analysis-outdated-banner")).toBeNull();
  });
});

describe("AI Insights — top-up callout (HRP-489)", () => {
  it("disables the upgrade and explains why when no transcript exists", async () => {
    runs.push(mkRun());
    eligibility = mkEligibility({ reason: "no_transcribed_interview" });
    await render(true);

    const callout = byTestId("ai-analysis-topup-callout")!;
    expect(callout.getAttribute("data-eligible")).toBe("false");
    expect(callout.textContent).toContain(
      "Upload and transcribe an interview to enable full analysis",
    );

    const upgrade = byTestId(
      "ai-analysis-upgrade-to-full-btn",
    ) as HTMLButtonElement;
    expect(upgrade).not.toBeNull();
    expect(upgrade.disabled).toBe(true);
  });

  it("enables the upgrade once a transcript makes it available", async () => {
    runs.push(mkRun());
    eligibility = mkEligibility({
      eligible: true,
      transcribed_interview_id: "interview-1",
      interview_id: "interview-1",
    });
    await render(true);

    const callout = byTestId("ai-analysis-topup-callout")!;
    expect(callout.getAttribute("data-eligible")).toBe("true");
    const upgrade = byTestId(
      "ai-analysis-upgrade-to-full-btn",
    ) as HTMLButtonElement;
    expect(upgrade.disabled).toBe(false);
    expect(upgrade.textContent).toContain("20");
  });
});
