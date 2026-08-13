import { describe, expect, it } from "vitest";

import {
  REFINE_ACTION_BY_SCOPE,
  START_ACTION_BY_SCOPE,
  regenerateActionForSession,
  startActionForScope,
} from "@/lib/billing-actions";

describe("regenerateActionForSession (HRP-509 review #5)", () => {
  it("quotes the refine price for a session created by Refine", () => {
    // The backend re-charges `params.billing_action`; quoting the start
    // action here showed 200 for a re-run that costs 30.
    const session = {
      scope: "whole_base" as const,
      params: { billing_action: "ai_competence_generation.refine" },
    };
    expect(regenerateActionForSession(session)).toBe(
      "ai_competence_generation.refine",
    );
  });

  it("quotes the start price for an initial generation", () => {
    const session = {
      scope: "whole_base" as const,
      params: { billing_action: "ai_competence_generation.start_whole_base" },
    };
    expect(regenerateActionForSession(session)).toBe(
      "ai_competence_generation.start_whole_base",
    );
  });

  it("falls back to the scope's start action when nothing was pinned", () => {
    // Mirrors the backend fallback for sessions created before the field.
    for (const scope of Object.keys(START_ACTION_BY_SCOPE) as Array<
      keyof typeof START_ACTION_BY_SCOPE
    >) {
      expect(regenerateActionForSession({ scope, params: {} })).toBe(
        startActionForScope(scope),
      );
      expect(regenerateActionForSession({ scope })).toBe(
        startActionForScope(scope),
      );
    }
  });

  it("returns null without a session so no price is quoted", () => {
    expect(regenerateActionForSession(null)).toBeNull();
    expect(regenerateActionForSession(undefined)).toBeNull();
  });

  it("maps the matrix scope to its own pricing category", () => {
    expect(START_ACTION_BY_SCOPE.specialization_matrix).toBe(
      "ai_specialization_matrix.start",
    );
    expect(REFINE_ACTION_BY_SCOPE.specialization_matrix).toBe(
      "ai_specialization_matrix.refine",
    );
  });
});
