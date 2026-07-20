import { describe, expect, it } from "vitest";

import {
  AI_ANALYSIS_STAGES,
  AI_ANALYSIS_STAGE_LABELS,
} from "@/lib/recruitment-types";
import type {
  AiAnalysisMode,
  AiAnalysisStage,
} from "@/lib/recruitment-types";

// HRP-270: pure-logic guards for the InFlightCard stepper. Vitest
// runs without jsdom, so we re-implement the same per-stage
// decision tree the component uses and pin it here — keeps a
// regression on "resume-only must grey out citations + process
// findings" or "skipped stage somehow shows a checkmark" from
// sneaking in.

const SKIPPED_FOR_RESUME_ONLY: ReadonlySet<AiAnalysisStage> = new Set([
  "process_findings",
  "citations",
]);

type StageVisual = "skipped" | "active" | "done" | "pending";

function deriveStageVisual(
  stage: AiAnalysisStage,
  mode: AiAnalysisMode,
  currentStage: AiAnalysisStage | null,
): StageVisual {
  const skipped =
    mode === "resume_only" && SKIPPED_FOR_RESUME_ONLY.has(stage);
  if (skipped) return "skipped";
  const idx = AI_ANALYSIS_STAGES.indexOf(stage);
  const activeIdx = currentStage
    ? AI_ANALYSIS_STAGES.indexOf(currentStage)
    : -1;
  if (activeIdx === -1) return "pending";
  if (idx === activeIdx) return "active";
  if (idx < activeIdx) return "done";
  return "pending";
}

describe("InFlightCard stage taxonomy", () => {
  it("exposes all six stages in canonical order", () => {
    expect(AI_ANALYSIS_STAGES).toEqual([
      "pre_check",
      "competences",
      "blind_spots",
      "process_findings",
      "citations",
      "verdict",
    ]);
  });

  it("ships a human label for every stage", () => {
    for (const s of AI_ANALYSIS_STAGES) {
      expect(AI_ANALYSIS_STAGE_LABELS[s]).toBeTruthy();
    }
  });
});

describe("deriveStageVisual", () => {
  it("greys out citations + process_findings for resume_only", () => {
    expect(
      deriveStageVisual("citations", "resume_only", "competences"),
    ).toBe("skipped");
    expect(
      deriveStageVisual("process_findings", "resume_only", "competences"),
    ).toBe("skipped");
  });

  it("does not grey out citations for full mode", () => {
    expect(deriveStageVisual("citations", "full", "competences")).toBe(
      "pending",
    );
  });

  it("marks the active stage", () => {
    expect(
      deriveStageVisual("competences", "resume_only", "competences"),
    ).toBe("active");
  });

  it("marks stages before the active one as done", () => {
    expect(
      deriveStageVisual("pre_check", "resume_only", "competences"),
    ).toBe("done");
  });

  it("marks stages after the active one as pending", () => {
    expect(
      deriveStageVisual("verdict", "resume_only", "competences"),
    ).toBe("pending");
  });

  it("falls back to pending for every non-skipped stage when current_stage is null", () => {
    for (const s of AI_ANALYSIS_STAGES) {
      const expected =
        SKIPPED_FOR_RESUME_ONLY.has(s) ? "skipped" : "pending";
      expect(deriveStageVisual(s, "resume_only", null)).toBe(expected);
    }
  });
});
