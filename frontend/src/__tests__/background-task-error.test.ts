/**
 * HRP-512: background-task failures must not reach a toast as English
 * text. The transport layer has no translator, so it raises TaskError
 * with a stable code and the toast boundary renders `common.<code>`
 * (the UploadError pattern).
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { ApiError, TaskError, taskErrorKey, waitForTask } from "@/lib/api";

type StatusHandler = (msg: {
  payload: {
    task_id: string;
    status: string;
    result: unknown;
    error: string | null;
  };
}) => void;

const handlers: StatusHandler[] = [];

vi.mock("@/lib/ws-bus", () => ({
  subscribeWs: (_event: string, handler: StatusHandler) => {
    handlers.push(handler);
    return () => {};
  },
  getWsState: () => "open",
}));

function emit(status: string, error: string | null) {
  for (const handler of handlers) {
    handler({ payload: { task_id: "t-1", status, result: null, error } });
  }
}

const EN = JSON.parse(
  readFileSync(resolve(__dirname, "../../messages/en.json"), "utf8"),
) as { common: Record<string, string> };

describe("taskErrorKey", () => {
  it("maps a TaskError to its catalog key and ignores everything else", () => {
    expect(taskErrorKey(new TaskError("backgroundTaskFailed", 500, "x"))).toBe(
      "backgroundTaskFailed",
    );
    expect(
      taskErrorKey(new TaskError("backgroundTaskTimedOut", 504, "x")),
    ).toBe("backgroundTaskTimedOut");
    expect(taskErrorKey(new ApiError(500, "boom"))).toBeNull();
    expect(taskErrorKey(new Error("boom"))).toBeNull();
    expect(taskErrorKey(undefined)).toBeNull();
  });

  it("returns keys that exist in the common catalog namespace", () => {
    for (const code of ["backgroundTaskFailed", "backgroundTaskTimedOut"]) {
      expect(EN.common[code], `common.${code} missing from en.json`).toBeTruthy();
    }
  });
});

describe("waitForTask failure codes", () => {
  beforeEach(() => {
    handlers.length = 0;
    // Cold-fetch and the polling loop must not reach the network.
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
  });

  it("raises a coded TaskError when the worker reports no message", async () => {
    const pending = waitForTask("t-1", { intervalMs: 10_000 });
    await vi.waitFor(() => expect(handlers.length).toBeGreaterThan(0));
    emit("FAILURE", null);
    await expect(pending).rejects.toBeInstanceOf(TaskError);
    await expect(pending).rejects.toMatchObject({
      code: "backgroundTaskFailed",
    });
  });

  it("keeps a worker-supplied message verbatim instead of the generic key", async () => {
    const pending = waitForTask("t-1", { intervalMs: 10_000 });
    await vi.waitFor(() => expect(handlers.length).toBeGreaterThan(0));
    emit("FAILURE", "Resume parser crashed");
    await expect(pending).rejects.toThrow("Resume parser crashed");
    await expect(pending).rejects.not.toBeInstanceOf(TaskError);
  });

  it("raises a coded TaskError when the deadline passes", async () => {
    const pending = waitForTask("t-1", { intervalMs: 10_000, timeoutMs: 5 });
    await expect(pending).rejects.toMatchObject({
      code: "backgroundTaskTimedOut",
      status: 504,
    });
  });
});
