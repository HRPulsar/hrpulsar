import { describe, expect, it } from "vitest";

import { aiVerdictCellState } from "@/lib/recruitment-types";
import type { AiReadiness, AiVerdict } from "@/lib/recruitment-types";

// HRP-493 (task 2) — the AI DATA / AI VERDICT matrix from the ticket.
//
// The column used to render a "Pending" chip for every row whose
// verdict had not been written yet, which conflated three genuinely
// different situations: no resume at all, a resume waiting to be
// analysed, and an analysis actually running. Only the last two are
// recoverable by waiting; the first needs a resume first.

describe("AI VERDICT cell state", () => {
  it("shows the no-analysis icon when there is no resume", () => {
    expect(
      aiVerdictCellState({ verdict: "pending", readiness: "none" }),
    ).toBe("no-analysis");
  });

  it("shows a spinner while a resume-only run executes", () => {
    expect(
      aiVerdictCellState({
        verdict: "pending",
        readiness: "resume_only",
        inProgress: true,
      }),
    ).toBe("analyzing");
  });

  it("shows a spinner while a full run executes", () => {
    expect(
      aiVerdictCellState({
        verdict: "pending",
        readiness: "resume_and_transcript",
        inProgress: true,
      }),
    ).toBe("analyzing");
  });

  it("keeps the spinner ahead of a stale verdict from a prior run", () => {
    // A re-analysis of an already-scored candidate: the old verdict is
    // still on the row, but it is being replaced right now.
    expect(
      aiVerdictCellState({
        verdict: "needs_check",
        readiness: "resume_and_transcript",
        inProgress: true,
      }),
    ).toBe("analyzing");
  });

  it.each<[AiVerdict, AiReadiness]>([
    ["not_recommended", "resume_only"],
    ["needs_check", "resume_only"],
    ["not_recommended", "resume_and_transcript"],
    ["needs_check", "resume_and_transcript"],
    ["recommended", "resume_and_transcript"],
  ])("renders the %s verdict for %s readiness", (verdict, readiness) => {
    expect(aiVerdictCellState({ verdict, readiness })).toBe("verdict");
  });

  it("still shows Pending when a resume is parsed but nothing runs yet", () => {
    // Not in the ticket's matrix, which only enumerates in-flight and
    // finished runs. The row is actionable — the recruiter presses
    // Analyze — so it keeps the neutral chip rather than the icon that
    // means "you cannot analyse this yet".
    expect(
      aiVerdictCellState({ verdict: "pending", readiness: "resume_only" }),
    ).toBe("verdict");
  });

  it("defaults to the verdict branch when readiness is unknown", () => {
    // Surfaces that render the badge without a readiness prop (the
    // candidate card's application list) must not fall into the
    // "no resume" branch on missing data.
    expect(aiVerdictCellState({ verdict: "pending" })).toBe("verdict");
  });
});
