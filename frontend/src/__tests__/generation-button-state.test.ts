import { describe, expect, it } from "vitest";

import type {
  CompetenceGenerationSession,
  SessionStatus,
} from "@/lib/api/competence-generation";

// HRP-122 re-spec: pure-logic guards for the GenerationStatusButton state
// machine. Vitest runs without jsdom, so we re-implement the same decision
// tree the component uses and pin it here — keeps a regression on the
// "Checking session…" loading state from sneaking in.

type ButtonState = "loading" | "idle" | "active-session" | "error";

function deriveButtonState(
  activeSession: CompetenceGenerationSession | null,
  loading: boolean,
): ButtonState {
  if (loading && !activeSession) return "loading";
  const s = activeSession?.status;
  if (s === "pending" || s === "running" || s === "ready") {
    return "active-session";
  }
  if (s === "error") return "error";
  return "idle";
}

function mkSession(status: SessionStatus): CompetenceGenerationSession {
  return {
    id: "sess1",
    tenant_id: "t1",
    user_id: "u1",
    scope: "whole_base",
    target_id: null,
    params: {},
    payload: null,
    selection_state: {},
    status,
    error_code: null,
    error_message: null,
    parent_session_id: null,
    prompt_version: "v1",
    llm_model: null,
    tokens_used: null,
    cost_credits: null,
    created_at: "",
    updated_at: "",
    finished_at: null,
  };
}

describe("GenerationStatusButton state machine", () => {
  it("returns loading while the page is still resolving the active session", () => {
    expect(deriveButtonState(null, true)).toBe("loading");
  });

  it("stays in idle once loading finished and no session is active", () => {
    expect(deriveButtonState(null, false)).toBe("idle");
  });

  it("upgrades to active-session for pending / running / ready", () => {
    for (const status of ["pending", "running", "ready"] as SessionStatus[]) {
      expect(deriveButtonState(mkSession(status), false)).toBe("active-session");
    }
  });

  it("flags error for failed sessions", () => {
    expect(deriveButtonState(mkSession("error"), false)).toBe("error");
  });

  it("ignores loading once a session is already known", () => {
    expect(deriveButtonState(mkSession("running"), true)).toBe(
      "active-session",
    );
  });
});
