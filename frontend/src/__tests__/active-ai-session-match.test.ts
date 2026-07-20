import { describe, expect, it } from "vitest";
import type { ActiveAiSession } from "@/hooks/use-active-ai-sessions";
import { findMatrixSessionForSpec } from "@/lib/active-ai-session-match";

function matrix(
  kind: "own" | "other",
  session_id: string,
  target_id: string | null,
  position_id: string | null = null,
): ActiveAiSession {
  if (kind === "own") {
    return {
      kind: "own",
      session_id,
      scope: "specialization_matrix",
      target_id,
      status: "running",
      position_id,
    };
  }
  return {
    kind: "other",
    session_id,
    user_full_name: "Vera",
    scope: "specialization_matrix",
    target_id,
    status: "ready",
    position_id: null,
  };
}

describe("findMatrixSessionForSpec", () => {
  it("returns null when the spec id is null/undefined", () => {
    expect(findMatrixSessionForSpec([matrix("own", "s1", "x")], null)).toBeNull();
    expect(findMatrixSessionForSpec([matrix("own", "s1", "x")], undefined)).toBeNull();
  });

  it("returns null when no session matches the spec", () => {
    const sessions = [matrix("own", "s1", "x"), matrix("other", "s2", "y")];
    expect(findMatrixSessionForSpec(sessions, "z")).toBeNull();
  });

  it("ignores non-matrix scopes even on the same target", () => {
    const sessions: ActiveAiSession[] = [
      {
        kind: "own",
        session_id: "s1",
        scope: "group",
        target_id: "spec-1",
        status: "running",
        position_id: null,
      },
      {
        kind: "other",
        session_id: "s2",
        user_full_name: "Max",
        scope: "whole_base",
        target_id: null,
        status: "running",
        position_id: null,
      },
    ];
    expect(findMatrixSessionForSpec(sessions, "spec-1")).toBeNull();
  });

  it("prefers the caller's own session over another admin's", () => {
    const sessions = [
      matrix("other", "other-1", "spec-1"),
      matrix("own", "own-1", "spec-1"),
    ];
    const hit = findMatrixSessionForSpec(sessions, "spec-1");
    expect(hit?.kind).toBe("own");
    expect(hit?.session_id).toBe("own-1");
  });

  it("falls back to the first other session when there is no own match", () => {
    const sessions = [
      matrix("other", "other-1", "spec-1"),
      matrix("other", "other-2", "spec-1"),
    ];
    const hit = findMatrixSessionForSpec(sessions, "spec-1");
    expect(hit?.session_id).toBe("other-1");
  });

  it("propagates position_id from the matched own session", () => {
    const sessions = [matrix("own", "own-1", "spec-1", "pos-42")];
    const hit = findMatrixSessionForSpec(sessions, "spec-1");
    expect(hit?.position_id).toBe("pos-42");
  });
});
