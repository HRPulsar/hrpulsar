import { describe, it, expect } from "vitest";
import { shouldPollTaskStatus } from "@/hooks/use-task-status";

describe("shouldPollTaskStatus (HRP-232)", () => {
  it("polls while the task has not started yet (status null)", () => {
    expect(shouldPollTaskStatus("task-1", null)).toBe(true);
  });

  it("polls while the task is PENDING", () => {
    expect(shouldPollTaskStatus("task-1", "PENDING")).toBe(true);
  });

  it("polls while the task is STARTED", () => {
    expect(shouldPollTaskStatus("task-1", "STARTED")).toBe(true);
  });

  it("polls while the task is RETRY", () => {
    expect(shouldPollTaskStatus("task-1", "RETRY")).toBe(true);
  });

  it("stops polling after SUCCESS", () => {
    expect(shouldPollTaskStatus("task-1", "SUCCESS")).toBe(false);
  });

  it("stops polling after FAILURE", () => {
    expect(shouldPollTaskStatus("task-1", "FAILURE")).toBe(false);
  });

  it("does not poll when there is no task id", () => {
    expect(shouldPollTaskStatus(null, null)).toBe(false);
    expect(shouldPollTaskStatus(null, "PENDING")).toBe(false);
  });
});
