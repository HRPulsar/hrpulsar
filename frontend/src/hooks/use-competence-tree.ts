"use client";

import { useCallback, useSyncExternalStore } from "react";
import { api } from "@/lib/api";
import type { CompetenceGroupTree } from "@/lib/types";

interface TreeState {
  data: CompetenceGroupTree[] | null;
  loading: boolean;
  error: string | null;
}

const EMPTY_TREE: CompetenceGroupTree[] = [];
const INITIAL_STATE: TreeState = { data: null, loading: false, error: null };
const SERVER_SNAPSHOT: TreeState = INITIAL_STATE;

let cache: TreeState = INITIAL_STATE;
let inflight: Promise<void> | null = null;
let fetchSeq = 0;
const listeners = new Set<() => void>();

function notify(): void {
  for (const l of listeners) {
    try {
      l();
    } catch (err) {
      console.error("competence-tree listener error", err);
    }
  }
}

function setState(next: Partial<TreeState>): void {
  cache = { ...cache, ...next };
  notify();
}

function startFetch(): Promise<void> {
  const myId = ++fetchSeq;
  setState({ loading: true, error: null });
  const p = (async () => {
    try {
      const data = await api.get<CompetenceGroupTree[]>("/competence-tree");
      if (myId === fetchSeq) setState({ data, loading: false, error: null });
    } catch (err) {
      if (myId === fetchSeq) {
        const msg = err instanceof Error ? err.message : "Failed to load competence tree";
        setState({ loading: false, error: msg });
      }
    } finally {
      if (myId === fetchSeq) inflight = null;
    }
  })();
  inflight = p;
  return p;
}

function fetchTree(): Promise<void> {
  if (inflight) return inflight;
  return startFetch();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  // First subscriber triggers the initial load.
  if (cache.data === null && !cache.loading && !inflight) {
    fetchTree();
  }
  return () => {
    listeners.delete(listener);
  };
}

function getSnapshot(): TreeState {
  return cache;
}

function getServerSnapshot(): TreeState {
  return SERVER_SNAPSHOT;
}

/**
 * Force a re-fetch of the shared competence tree. Every subscriber
 * re-renders with the new payload through `useCompetenceTree()`.
 *
 * Bumps the fetch sequence so any in-flight response from before the
 * invalidate call is discarded — otherwise a slow stale fetch could
 * land after a fresh one and overwrite it.
 */
export function invalidateCompetenceTree(): Promise<void> {
  return startFetch();
}

export interface UseCompetenceTreeResult {
  tree: CompetenceGroupTree[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

/**
 * Single source of truth for the competence tree (`GET /api/competence-tree`).
 *
 * - First mount triggers a cold fetch; concurrent mounts share the same
 *   inflight promise and the resolved cache.
 * - `invalidateCompetenceTree()` re-fetches and pushes the new payload to
 *   every subscriber.
 */
export function useCompetenceTree(): UseCompetenceTreeResult {
  const state = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  const refresh = useCallback(() => invalidateCompetenceTree(), []);
  return {
    tree: state.data ?? EMPTY_TREE,
    loading: state.loading,
    error: state.error,
    refresh,
  };
}
