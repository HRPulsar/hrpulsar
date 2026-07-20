"use client";

import { useEffect, useRef, useState } from "react";

import { API_BASE } from "@/lib/api-base";
const POLL_INTERVAL_MS = 15_000;
// HRP-122: tolerate transient health blips before flagging the worker as
// offline. Beat refreshes every 30s and the Redis key has a 90s TTL, so a
// single failed probe means almost nothing — only a sustained gap (three
// consecutive failures ≈ 45s) reliably indicates beat is down.
const FAILURE_THRESHOLD = 3;

export type CeleryHealth = "unknown" | "available" | "unavailable";

/**
 * Polls `/api/health/celery`. The endpoint reads the Redis heartbeat key
 * `status:celery:heartbeat` (refreshed every 30s by Celery beat). If the
 * key is missing the worker stack is considered offline.
 *
 * Used by the AI generation drawer to surface "Worker offline" instead of
 * letting the session sit silently in `pending`.
 */
export function useCeleryHealth(enabled: boolean): CeleryHealth {
  const [state, setState] = useState<CeleryHealth>("unknown");
  const failuresRef = useRef(0);

  useEffect(() => {
    if (!enabled) {
      setState("unknown");
      failuresRef.current = 0;
      return;
    }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    async function probe() {
      try {
        const res = await fetch(`${API_BASE}/health/celery`, {
          cache: "no-store",
        });
        if (cancelled) return;
        if (res.ok) {
          failuresRef.current = 0;
          setState("available");
        } else {
          failuresRef.current += 1;
          if (failuresRef.current >= FAILURE_THRESHOLD) {
            setState("unavailable");
          }
        }
      } catch {
        if (cancelled) return;
        failuresRef.current += 1;
        if (failuresRef.current >= FAILURE_THRESHOLD) {
          setState("unavailable");
        }
      } finally {
        if (!cancelled) {
          timer = setTimeout(probe, POLL_INTERVAL_MS);
        }
      }
    }

    probe();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [enabled]);

  return state;
}