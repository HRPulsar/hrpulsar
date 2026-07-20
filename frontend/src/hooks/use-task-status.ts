"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { TaskStatus } from "@/lib/api";
import { useWebSocketEvent } from "@/lib/ws";

type TaskUpdatePayload<T> = {
  task_id: string;
  status: TaskStatus<T>["status"];
  result: T | null;
  error: string | null;
  module: string | null;
  action: string | null;
};

export type UseTaskStatusResult<T> = {
  status: TaskStatus<T>["status"] | null;
  result: T | null;
  error: string | null;
  isLoading: boolean;
};

const POLL_INTERVAL_MS = 2000;

/**
 * HRP-232: pure predicate — should this task still be polled? REST polling
 * runs while the task is in a non-terminal state regardless of WS state.
 * Redis pub/sub on the backend is at-most-once and wsState lags silent
 * disconnects (see HRP-122 REDO #3), so gating polling on "WS is open"
 * stranded users on "processing…" forever when a frame was dropped.
 */
export function shouldPollTaskStatus(
  taskId: string | null,
  status: TaskStatus<unknown>["status"] | null,
): boolean {
  if (!taskId) return false;
  return status !== "SUCCESS" && status !== "FAILURE";
}

/**
 * Subscribe to a Celery task's status via WebSocket with cold-fetch race
 * coverage. REST polling runs whenever the task is active — WS pushes are
 * a fast-path but cannot be relied on for delivery.
 *
 * Returns the task's terminal state once it arrives. Pass `null` for
 * `taskId` to disable the hook (useful when the task hasn't been enqueued
 * yet inside the same component).
 */
export function useTaskStatus<T = unknown>(
  taskId: string | null,
): UseTaskStatusResult<T> {
  const [status, setStatus] = useState<TaskStatus<T>["status"] | null>(null);
  const [result, setResult] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  // React 19 idiom for "reset state when prop changes" — comparing during
  // render and calling setState restarts this render, no extra commit.
  const [prevTaskId, setPrevTaskId] = useState(taskId);
  if (taskId !== prevTaskId) {
    setPrevTaskId(taskId);
    setStatus(null);
    setResult(null);
    setError(null);
  }

  const terminal = status === "SUCCESS" || status === "FAILURE";

  useWebSocketEvent<TaskUpdatePayload<T>>("task.updated", (msg) => {
    const payload = msg.payload;
    if (!payload || payload.task_id !== taskId) return;
    setStatus(payload.status);
    if (payload.status === "SUCCESS") {
      setResult(payload.result);
    } else if (payload.status === "FAILURE") {
      setError(payload.error || "Background task failed");
    }
  });

  // Cold-fetch on mount / taskId change to cover "task already done before subscribe".
  useEffect(() => {
    if (!taskId) return;
    let cancelled = false;
    api
      .get<TaskStatus<T>>(`/tasks/${taskId}`)
      .then((res) => {
        if (cancelled) return;
        setStatus((cur) => (cur === "SUCCESS" || cur === "FAILURE" ? cur : res.status));
        if (res.status === "SUCCESS") {
          setResult((res.result as T | undefined) ?? null);
        } else if (res.status === "FAILURE") {
          setError(res.error || "Background task failed");
        }
      })
      .catch(() => {
        // Best-effort: if the cold-fetch fails the WS path is still alive.
      });
    return () => {
      cancelled = true;
    };
  }, [taskId]);

  // HRP-232: polling runs while the task is active regardless of WS state.
  useEffect(() => {
    if (!shouldPollTaskStatus(taskId, status)) return;
    let cancelled = false;
    const handle = setInterval(() => {
      api
        .get<TaskStatus<T>>(`/tasks/${taskId}`)
        .then((res) => {
          if (cancelled) return;
          setStatus(res.status);
          if (res.status === "SUCCESS") {
            setResult((res.result as T | undefined) ?? null);
            clearInterval(handle);
          } else if (res.status === "FAILURE") {
            setError(res.error || "Background task failed");
            clearInterval(handle);
          }
        })
        .catch(() => {
          /* keep trying on next tick */
        });
    }, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(handle);
    };
  }, [taskId, status, terminal]);

  return {
    status,
    result,
    error,
    isLoading: !!taskId && !terminal,
  };
}
