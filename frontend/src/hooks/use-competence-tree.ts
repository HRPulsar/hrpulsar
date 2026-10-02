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

/**
 * One module-level store per tree URL. HRP-632: the pickers read the tree
 * without personal drafts - a draft is attached nowhere until published -
 * while the catalogue page reads it with the drafts its viewer may see.
 */
function createTreeStore(path: string) {
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
        const data = await api.get<CompetenceGroupTree[]>(path);
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

  function subscribe(listener: () => void): () => void {
    listeners.add(listener);
    // First subscriber triggers the initial load.
    if (cache.data === null && !cache.loading && !inflight) {
      void startFetch();
    }
    return () => {
      listeners.delete(listener);
    };
  }

  return {
    subscribe,
    getSnapshot: (): TreeState => cache,
    startFetch,
    // A first fetch still in flight counts: it read the tree before the
    // write, and skipped here it would land and be kept as fresh.
    inUse: (): boolean => listeners.size > 0 || cache.data !== null || inflight !== null,
  };
}

const pickerTree = createTreeStore("/competence-tree");
const catalogueTree = createTreeStore("/competence-tree?drafts=true");

function getServerSnapshot(): TreeState {
  return SERVER_SNAPSHOT;
}

/**
 * Force a re-fetch of the shared competence tree. Every subscriber
 * re-renders with the new payload through `useCompetenceTree()`.
 *
 * Bumps the fetch sequence so any in-flight response from before the
 * invalidate call is discarded — otherwise a slow stale fetch could
 * land after a fresh one and overwrite it. The catalogue page's tree is
 * re-fetched too once something reads it.
 */
export function invalidateCompetenceTree(): Promise<void> {
  const fetches = [pickerTree.startFetch()];
  if (catalogueTree.inUse()) fetches.push(catalogueTree.startFetch());
  return Promise.all(fetches).then(() => undefined);
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
 * - `{ drafts: true }` is the catalogue page's tree: it carries the personal
 *   drafts the viewer may see (HRP-632); every picker leaves it off.
 */
export function useCompetenceTree(opts: { drafts?: boolean } = {}): UseCompetenceTreeResult {
  const store = opts.drafts ? catalogueTree : pickerTree;
  const state = useSyncExternalStore(store.subscribe, store.getSnapshot, getServerSnapshot);
  const refresh = useCallback(() => invalidateCompetenceTree(), []);
  return {
    tree: state.data ?? EMPTY_TREE,
    loading: state.loading,
    error: state.error,
    refresh,
  };
}
