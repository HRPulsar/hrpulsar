// HRP-115 / HRP-116 / HRP-117: pins the manual status machine the
// assessments UI walks. Backend enforces the same shape — done from
// in_progress and on_review from draft are 400s — so the test guards
// against drift between client and server.

import { describe, expect, it } from "vitest";
import {
  ASSESSMENT_MANUAL_FORBIDDEN_STATUSES,
  ASSESSMENT_MANUAL_FORBIDDEN_TOOLTIP,
  ASSESSMENT_STATUS_FLOW,
  ASSESSMENT_STATUS_LABELS,
  ASSESSMENT_STATUS_OPTIONS,
  ASSESSMENT_TERMINAL_STATUSES,
  assessmentStatusLabel,
} from "@/lib/assessment-status";

describe("ASSESSMENT_STATUS_OPTIONS", () => {
  it("includes on_review between in_progress and done so the Change Status modal exposes it", () => {
    expect(ASSESSMENT_STATUS_OPTIONS).toEqual([
      "draft",
      "sent",
      "in_progress",
      "on_review",
      "done",
      "cancelled",
    ]);
  });
});

describe("ASSESSMENT_TERMINAL_STATUSES", () => {
  it("treats on_review as non-terminal so the Details action buttons still render", () => {
    expect(ASSESSMENT_TERMINAL_STATUSES.has("on_review")).toBe(false);
    expect(ASSESSMENT_TERMINAL_STATUSES.has("done")).toBe(true);
    expect(ASSESSMENT_TERMINAL_STATUSES.has("cancelled")).toBe(true);
  });
});

describe("ASSESSMENT_STATUS_FLOW (HRP-117 — in_progress no longer jumps to done)", () => {
  it("offers on_review and cancelled out of in_progress, never done", () => {
    expect(ASSESSMENT_STATUS_FLOW.in_progress).toEqual(["on_review", "cancelled"]);
    expect(ASSESSMENT_STATUS_FLOW.in_progress).not.toContain("done");
  });

  it("offers done and cancelled out of on_review (HRP-116 Details buttons)", () => {
    expect(ASSESSMENT_STATUS_FLOW.on_review).toEqual(["done", "cancelled"]);
  });

  it("offers only cancel out of sent (HRP-192 — In progress is auto-only)", () => {
    expect(ASSESSMENT_STATUS_FLOW.draft).toEqual(["sent"]);
    expect(ASSESSMENT_STATUS_FLOW.sent).toEqual(["cancelled"]);
    expect(ASSESSMENT_STATUS_FLOW.sent).not.toContain("in_progress");
  });

  it("leaves terminal statuses with no outgoing transitions", () => {
    expect(ASSESSMENT_STATUS_FLOW.done).toEqual([]);
    expect(ASSESSMENT_STATUS_FLOW.cancelled).toEqual([]);
  });

  it("never offers a forward jump that skips on_review on the way to done", () => {
    for (const [from, targets] of Object.entries(ASSESSMENT_STATUS_FLOW)) {
      if (from !== "on_review") {
        expect(targets, `${from} should not promote straight to done`).not.toContain(
          "done",
        );
      }
    }
  });
});

describe("ASSESSMENT_STATUS_LABELS (HRP-194 — filter/Change status modals)", () => {
  it("renames In Progress / On Review to sentence case to match the rest of the UI", () => {
    expect(ASSESSMENT_STATUS_LABELS.in_progress).toBe("In progress");
    expect(ASSESSMENT_STATUS_LABELS.on_review).toBe("On review");
  });

  it("covers every option so the filter dropdown never falls back to raw codes", () => {
    for (const code of ASSESSMENT_STATUS_OPTIONS) {
      expect(ASSESSMENT_STATUS_LABELS[code]).toBeTruthy();
      expect(ASSESSMENT_STATUS_LABELS[code]).not.toBe(code);
    }
  });

  it("falls back to the raw code when given an unknown status", () => {
    expect(assessmentStatusLabel("unknown_code")).toBe("unknown_code");
  });
});

describe("ASSESSMENT_MANUAL_FORBIDDEN_STATUSES (HRP-192 — Change status modal)", () => {
  it("flags in_progress as manual-forbidden so the modal greys it out", () => {
    expect(ASSESSMENT_MANUAL_FORBIDDEN_STATUSES.has("in_progress")).toBe(true);
  });

  it("does not flag any other status as forbidden", () => {
    for (const code of ASSESSMENT_STATUS_OPTIONS) {
      if (code === "in_progress") continue;
      expect(ASSESSMENT_MANUAL_FORBIDDEN_STATUSES.has(code)).toBe(false);
    }
  });

  it("ships a tooltip the operator can hover for context", () => {
    expect(ASSESSMENT_MANUAL_FORBIDDEN_TOOLTIP).toBe(
      "Manual transition is not allowed",
    );
  });
});
