"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  OtherActiveSession,
  SessionScope,
  SessionStatus,
  competenceGenerationApi,
} from "@/lib/api/competence-generation";
import { useWebSocketEvent } from "@/lib/ws";

/**
 * Discriminated view of one active AI generation session — own vs. another
 * tenant admin's. UI surfaces both so reviewers see when a competence is
 * already being generated for by a colleague (HRP-93).
 */
export type ActiveAiSession =
  | {
      kind: "own";
      session_id: string;
      scope: SessionScope;
      target_id: string | null;
      status: SessionStatus;
      /** HRP-33: position id stamped into `params.position_id` when the
       * matrix session was launched from a Position page. Used by the
       * positions/specializations list badges so they route Apply back to
       * the originating position. `null` for standalone matrix sessions
       * and for every non-matrix scope. */
      position_id: string | null;
    }
  | {
      kind: "other";
      session_id: string;
      user_full_name: string;
      scope: SessionScope;
      target_id: string | null;
      status: SessionStatus;
      /** Always `null` for other-users' sessions — `OtherActiveSessionRead`
       * does not expose `params.position_id` and we don't surface someone
       * else's originating position from a tenant-shared list view. */
      position_id: null;
    };

const POLL_INTERVAL_MS = 10_000;
const VISIBLE_STATUSES: SessionStatus[] = ["pending", "running", "ready"];

function keyFor(scope: SessionScope, target_id: string | null): string {
  return `${scope}:${target_id ?? "null"}`;
}

/**
 * HRP-232: pure predicate — should the hook keep polling? Polling runs
 * whenever at least one active session (own or another tenant admin's) is
 * being tracked, regardless of WS state. Stops when the tracked set is
 * empty. New-session discovery relies on the WS `compgen.session.updated`
 * push; HRP-122 REDO #3 covers why we cannot gate this polling on
 * `wsState === "open"`.
 */
export function shouldPollActiveSessions(
  hasOwn: boolean,
  othersCount: number,
): boolean {
  return hasOwn || othersCount > 0;
}

/**
 * Pure helper: groups a flat list of sessions into a Map keyed by
 * `${scope}:${target_id}`. Exposed for unit testing the bucketing logic
 * without spinning up React.
 */
export function buildActiveSessionsMap(
  sessions: ActiveAiSession[],
): Map<string, ActiveAiSession[]> {
  const map = new Map<string, ActiveAiSession[]>();
  for (const s of sessions) {
    const k = keyFor(s.scope, s.target_id);
    const bucket = map.get(k);
    if (bucket) bucket.push(s);
    else map.set(k, [s]);
  }
  return map;
}

interface UseActiveAiSessionsResult {
  /** All visible (non-terminal) sessions, own + others, indexed by
   * `${scope}:${target_id ?? "null"}`. */
  byTarget: Map<string, ActiveAiSession[]>;
  /** Flat list — useful when the caller wants to render a global counter. */
  all: ActiveAiSession[];
  refresh: () => Promise<void>;
}

/**
 * Aggregates the caller's own active session (`GET /sessions/active`) with
 * other tenant admins' active sessions (`GET /sessions/active-others`) into
 * a single keyed lookup. The map key is `${scope}:${target_id ?? "null"}`,
 * matching how the badge and matrix cells need to query.
 *
 * WS `compgen.session.updated` invalidates the cache; a 10s polling fallback
 * covers WS-down tenants. Cancelled / applied / errored sessions are filtered
 * out so the UI does not light up dead sessions.
 */
export function useActiveAiSessions(): UseActiveAiSessionsResult {
  const [own, setOwn] = useState<ActiveAiSession | null>(null);
  const [others, setOthers] = useState<ActiveAiSession[]>([]);
  // Monotonic request id — guards against a slow earlier refresh resolving
  // after a faster newer one and overwriting state with stale data.
  const requestSeqRef = useRef(0);

  const refresh = useCallback(async () => {
    const requestId = ++requestSeqRef.current;
    try {
      const [mine, theirs] = await Promise.all([
        competenceGenerationApi.getActive().catch(() => null),
        competenceGenerationApi.getActiveOthers().catch(
          () => [] as OtherActiveSession[],
        ),
      ]);
      if (requestId !== requestSeqRef.current) return;
      setOwn(
        mine && VISIBLE_STATUSES.includes(mine.status)
          ? {
              kind: "own",
              session_id: mine.id,
              scope: mine.scope,
              target_id: mine.target_id,
              status: mine.status,
              position_id: mine.params?.position_id ?? null,
            }
          : null,
      );
      setOthers(
        theirs
          .filter((s) => VISIBLE_STATUSES.includes(s.status))
          .map((s) => ({
            kind: "other",
            session_id: s.session_id,
            user_full_name: s.user_full_name,
            scope: s.scope,
            target_id: s.target_id,
            status: s.status,
            position_id: null,
          })),
      );
    } catch {
      // Best-effort; the badge layer is decorative.
    }
  }, []);

  useEffect(() => {
    // Initial cold-fetch synchronises React with the REST snapshot — setState
    // happens after an awaited fetch, not synchronously, so the linter false
    // positive on react-hooks/set-state-in-effect is acceptable here.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh();
  }, [refresh]);

  // WS push — invalidates regardless of which session the event refers to;
  // own/others are derived from a fresh REST snapshot every time anyway.
  useWebSocketEvent("compgen.session.updated", refresh);

  // HRP-232: poll whenever any active session is being tracked, regardless
  // of WS state. Skip when the tab is hidden so a forgotten open tab doesn't
  // hammer the API in the background.
  const hasOwn = own !== null;
  const othersCount = others.length;
  useEffect(() => {
    if (!shouldPollActiveSessions(hasOwn, othersCount)) return;
    const tick = () => {
      if (typeof document !== "undefined" && document.hidden) return;
      void refresh();
    };
    const id = setInterval(tick, POLL_INTERVAL_MS);
    const onVisible = () => {
      if (typeof document !== "undefined" && !document.hidden) void refresh();
    };
    if (typeof document !== "undefined") {
      document.addEventListener("visibilitychange", onVisible);
    }
    return () => {
      clearInterval(id);
      if (typeof document !== "undefined") {
        document.removeEventListener("visibilitychange", onVisible);
      }
    };
  }, [hasOwn, othersCount, refresh]);

  const { byTarget, all } = useMemo(() => {
    const list: ActiveAiSession[] = own ? [own, ...others] : [...others];
    return { byTarget: buildActiveSessionsMap(list), all: list };
  }, [own, others]);

  return { byTarget, all, refresh };
}

export const activeAiSessionsKey = keyFor;
