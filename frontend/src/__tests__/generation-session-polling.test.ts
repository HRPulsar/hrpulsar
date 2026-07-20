import { describe, it, expect } from "vitest";
import {
  shouldPollGenerationSession,
  type GenerationSessionStatus,
} from "@/hooks/generation-session-polling";

const ALL_STATUSES: GenerationSessionStatus[] = [
  "pending",
  "running",
  "ready",
  "applied",
  "cancelled",
  "error",
];

describe("shouldPollGenerationSession (HRP-122 REDO #3)", () => {
  it("polls while the session is pending", () => {
    expect(shouldPollGenerationSession("pending")).toBe(true);
  });

  it("polls while the session is running", () => {
    expect(shouldPollGenerationSession("running")).toBe(true);
  });

  it("polls while the session is ready (until applied/cancelled)", () => {
    expect(shouldPollGenerationSession("ready")).toBe(true);
  });

  it("stops polling after the session is applied", () => {
    expect(shouldPollGenerationSession("applied")).toBe(false);
  });

  it("stops polling after the session is cancelled — fixes 'session never finishes' UX", () => {
    expect(shouldPollGenerationSession("cancelled")).toBe(false);
  });

  it("stops polling after the session errored", () => {
    expect(shouldPollGenerationSession("error")).toBe(false);
  });

  it("does not poll when there is no session at all", () => {
    expect(shouldPollGenerationSession(null)).toBe(false);
  });

  it("covers every known status without throwing", () => {
    for (const s of ALL_STATUSES) {
      expect(() => shouldPollGenerationSession(s)).not.toThrow();
    }
  });
});
