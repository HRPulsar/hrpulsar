import { describe, expect, it } from "vitest";
import {
  activeSessionRoute,
  isActiveSessionConflict,
} from "@/lib/active-ai-session-route";

describe("activeSessionRoute", () => {
  // HRP-33 REDO: matrix sessions launched from a Position page must land on
  // the specialization AI-generate page (where the brief, progress UI and
  // review modal live), not the position page where the matrix flow used
  // to be embedded.
  it("routes specialization_matrix with position_id to the spec AI-generate page", () => {
    expect(
      activeSessionRoute({
        id: "sess-1",
        scope: "specialization_matrix",
        target_id: "spec-1",
        status: "running",
        params: { position_id: "pos-9" },
      }),
    ).toBe(
      "/company/specializations/spec-1/ai-generate?session=sess-1&position=pos-9",
    );
  });

  it("routes standalone specialization_matrix to the spec AI-generate page", () => {
    expect(
      activeSessionRoute({
        id: "sess-2",
        scope: "specialization_matrix",
        target_id: "spec-2",
        status: "ready",
        params: {},
      }),
    ).toBe("/company/specializations/spec-2/ai-generate?session=sess-2");
  });

  it("accepts an ActiveSessionRef shape (banner / 409 conflict)", () => {
    expect(
      activeSessionRoute({
        id: "sess-3",
        scope: "specialization_matrix",
        target_id: "spec-3",
        status: "running",
        position_id: "pos-3",
      }),
    ).toBe(
      "/company/specializations/spec-3/ai-generate?session=sess-3&position=pos-3",
    );
  });

  it("falls back to the global drawer on competences for non-matrix scopes", () => {
    expect(
      activeSessionRoute({
        id: "sess-4",
        scope: "group",
        target_id: "g-1",
        status: "running",
        params: {},
      }),
    ).toBe("/competences?session=sess-4");
    expect(
      activeSessionRoute({
        id: "sess-5",
        scope: "whole_base",
        target_id: null,
        status: "ready",
        params: {},
      }),
    ).toBe("/competences?session=sess-5");
  });

  it("falls back to /competences when matrix has no target", () => {
    expect(
      activeSessionRoute({
        id: "sess-6",
        scope: "specialization_matrix",
        target_id: null,
        status: "running",
        params: {},
      }),
    ).toBe("/competences?session=sess-6");
  });
});

describe("isActiveSessionConflict", () => {
  it("matches the documented 409 detail shape", () => {
    expect(
      isActiveSessionConflict({
        error_code: "active_session_exists",
        message: "...",
      }),
    ).toBe(true);
  });

  it("rejects unrelated detail payloads", () => {
    expect(isActiveSessionConflict(null)).toBe(false);
    expect(isActiveSessionConflict({})).toBe(false);
    expect(
      isActiveSessionConflict({ error_code: "insufficient_data" }),
    ).toBe(false);
  });
});
