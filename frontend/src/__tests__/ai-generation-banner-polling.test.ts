import { describe, it, expect } from "vitest";
import { shouldPollGenerationBanner } from "@/components/ai-generation-banner";
import type { SessionStatus } from "@/lib/api/competence-generation";

const ACTIVE: SessionStatus[] = ["pending", "running", "ready"];
const TERMINAL: SessionStatus[] = ["applied", "cancelled", "error"];

describe("shouldPollGenerationBanner (HRP-232)", () => {
  it.each(ACTIVE)("polls while session status is %s", (status) => {
    expect(shouldPollGenerationBanner(status)).toBe(true);
  });

  it.each(TERMINAL)("stops polling once session status is %s", (status) => {
    expect(shouldPollGenerationBanner(status)).toBe(false);
  });

  it("does not poll when there is no active session", () => {
    expect(shouldPollGenerationBanner(null)).toBe(false);
  });
});
