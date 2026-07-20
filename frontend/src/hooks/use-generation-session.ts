"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  CompetenceGenerationSession,
  RefinementInput,
  competenceGenerationApi,
} from "@/lib/api/competence-generation";
import { useWebSocketEvent } from "@/lib/ws";
import { shouldPollGenerationSession } from "@/hooks/generation-session-polling";

export type ActiveQuery = "active" | { sessionId: string };

const POLL_INTERVAL_MS = 5_000;
const ACTIVE_STATUSES: CompetenceGenerationSession["status"][] = [
  "pending",
  "running",
  "ready",
];
const RUNNING_STATUSES: CompetenceGenerationSession["status"][] = [
  "pending",
  "running",
];

interface UseGenerationSessionResult {
  session: CompetenceGenerationSession | null;
  loading: boolean;
  error: string | null;
  isActive: boolean;
  isRunning: boolean;
  refresh: () => Promise<void>;
  // Mutations resolve to the new (or refreshed) session and update local state.
  cancel: () => Promise<CompetenceGenerationSession | null>;
  clear: () => Promise<CompetenceGenerationSession | null>;
  refine: (
    input: RefinementInput,
  ) => Promise<CompetenceGenerationSession | null>;
  regenerate: () => Promise<CompetenceGenerationSession | null>;
  apply: (body: {
    publish: boolean;
    idempotency_key: string;
  }) => Promise<{ created_competences: string[] } | null>;
  updateSelection: (
    nodeId: string,
    selected: boolean,
  ) => Promise<CompetenceGenerationSession | null>;
}

/**
 * Source of truth for one AI-generation session.
 *
 * - Mounts → cold-fetches the snapshot (REST is the source of truth).
 * - WS `compgen.session.updated` → invalidates by re-fetching the same id.
 * - Polls every 5s whenever the session is in an active state. HRP-122
 *   REDO #3: Redis pub/sub delivery on the backend is at-most-once and
 *   wsState lags silent disconnects, so a "WS is open" check was letting
 *   running→ready and running→cancelled transitions go unnoticed until
 *   the drawer remounted. REST polling is now the source of truth; the
 *   WS push only shortens the median latency from ~5s to ~100ms.
 */
export function useGenerationSession(
  query: ActiveQuery = "active",
): UseGenerationSessionResult {
  const [session, setSession] = useState<CompetenceGenerationSession | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Latch onto a concrete session id once we have one. Subsequent
  // mutations replace it; cold-fetches keep using the same id so we
  // don't accidentally jump back to "active" after the session goes
  // applied/cancelled.
  const trackedIdRef = useRef<string | null>(
    typeof query === "object" ? query.sessionId : null,
  );

  const fetchOnce = useCallback(async () => {
    setError(null);
    try {
      const id = trackedIdRef.current;
      const next = id
        ? await competenceGenerationApi.get(id)
        : await competenceGenerationApi.getActive();
      setSession(next);
      if (next) trackedIdRef.current = next.id;
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to load session";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial cold-fetch + re-fetch when query target changes.
  useEffect(() => {
    if (typeof query === "object") {
      trackedIdRef.current = query.sessionId;
    } else {
      trackedIdRef.current = null;
    }
    setLoading(true);
    fetchOnce();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [typeof query === "object" ? query.sessionId : "active"]);

  // WS push → invalidate. Backend routes to the user's channel already, so
  // we only need to filter by session id when we're tracking a specific one.
  useWebSocketEvent<{ session_id?: string; status?: string }>(
    "compgen.session.updated",
    useCallback(
      (msg) => {
        const eventId = msg.payload?.session_id ?? null;
        const tracked = trackedIdRef.current;
        if (!tracked || !eventId || tracked === eventId) {
          fetchOnce();
        }
      },
      [fetchOnce],
    ),
  );

  // HRP-122 REDO #3: poll while the session is active regardless of WS
  // state. The fast-path WS push still arrives when delivery succeeds —
  // the polling just guarantees the UI catches every transition even
  // when a push is dropped. Effect re-runs only when status flips, not
  // on every selection-state mutation, so the interval is stable.
  const sessionStatus = session?.status ?? null;
  useEffect(() => {
    if (!shouldPollGenerationSession(sessionStatus)) return;
    const id = setInterval(fetchOnce, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [sessionStatus, fetchOnce]);

  // HRP-122 re-spec: after the initial load returns nothing for the
  // "active" query, keep retrying for ~30s so a session that lands a
  // beat later (POST → WS → render race when the user clicks Generate
  // and the drawer opens before the row is committed) still shows up
  // without forcing the user to refresh the page. Caps the retries so an
  // idle drawer doesn't poll forever on a real "no session" state.
  useEffect(() => {
    if (typeof query !== "string") return; // tracked by explicit session id, no race
    if (session || loading) return;
    let cancelled = false;
    let attempts = 0;
    const MAX_ATTEMPTS = 6; // 6 × 5 s = 30 s
    const id = setInterval(() => {
      if (cancelled || attempts >= MAX_ATTEMPTS) {
        clearInterval(id);
        return;
      }
      attempts += 1;
      void fetchOnce();
    }, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [query, session, loading, fetchOnce]);

  const cancel = useCallback(async () => {
    if (!session) return null;
    const next = await competenceGenerationApi.cancel(session.id);
    setSession(next);
    return next;
  }, [session]);

  const clear = useCallback(async () => {
    if (!session) return null;
    const next = await competenceGenerationApi.clear(session.id);
    setSession(next);
    return next;
  }, [session]);

  const refine = useCallback(
    async (input: RefinementInput) => {
      if (!session) return null;
      const child = await competenceGenerationApi.refine(session.id, input);
      trackedIdRef.current = child.id;
      setSession(child);
      return child;
    },
    [session],
  );

  const regenerate = useCallback(async () => {
    if (!session) return null;
    const child = await competenceGenerationApi.regenerate(session.id);
    trackedIdRef.current = child.id;
    setSession(child);
    return child;
  }, [session]);

  const apply = useCallback(
    async (body: { publish: boolean; idempotency_key: string }) => {
      if (!session) return null;
      const result = await competenceGenerationApi.apply(session.id, body);
      // Re-fetch so we get the now-applied session back into state.
      await fetchOnce();
      return result;
    },
    [session, fetchOnce],
  );

  const updateSelection = useCallback(
    async (nodeId: string, selected: boolean) => {
      if (!session) return null;
      // Optimistic — patch local state, rollback on error.
      const prev = session.selection_state ?? {};
      const optimistic: CompetenceGenerationSession = {
        ...session,
        selection_state: { ...prev, [nodeId]: selected },
      };
      setSession(optimistic);
      try {
        const next = await competenceGenerationApi.updateSelection(session.id, {
          node_id: nodeId,
          selected,
        });
        setSession(next);
        return next;
      } catch (err) {
        setSession(session);
        throw err;
      }
    },
    [session],
  );

  return useMemo(
    () => ({
      session,
      loading,
      error,
      isActive: session ? ACTIVE_STATUSES.includes(session.status) : false,
      isRunning: session ? RUNNING_STATUSES.includes(session.status) : false,
      refresh: fetchOnce,
      cancel,
      clear,
      refine,
      regenerate,
      apply,
      updateSelection,
    }),
    [
      session,
      loading,
      error,
      fetchOnce,
      cancel,
      clear,
      refine,
      regenerate,
      apply,
      updateSelection,
    ],
  );
}
