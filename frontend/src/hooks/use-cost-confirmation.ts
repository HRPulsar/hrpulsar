"use client";

import { useCallback, useEffect, useState } from "react";

import { useIsSaas } from "@/hooks/use-is-saas";
import { api } from "@/lib/api";
import { API_BASE } from "@/lib/api-base";
import type { CreditBalance } from "@/lib/types";

interface CostAction {
  action: string;
  name: string;
  cost: number;
}

interface CostCategory {
  category: string;
  actions: CostAction[];
}

let costsCache: Record<string, number> | null = null;
let costsCachedAt = 0;
let costsFetchPromise: Promise<Record<string, number>> | null = null;
// Bumped by invalidateCostConfirmationCache() so a fetch that was already in
// flight when the invalidation happened cannot write its pre-change prices
// back into the cache with a fresh timestamp (review fix).
let costsCacheGeneration = 0;
let balanceCache: CreditBalance | null = null;
let balanceFetchPromise: Promise<CreditBalance | null> | null = null;

/**
 * How long a quoted price list may be reused.
 *
 * Effective prices depend on the workspace's model, so they change when an
 * admin switches models or a platform admin reprices one. Explicit
 * invalidation covers the flows we own (see `invalidateCostConfirmationCache`
 * callers); this TTL is the backstop for the ones we don't — another admin's
 * change, or a tab left open for a day (review #3).
 */
const COSTS_TTL_MS = 5 * 60 * 1000;

function costsCacheIsFresh(): boolean {
  return costsCache !== null && Date.now() - costsCachedAt < COSTS_TTL_MS;
}

function flattenCosts(categories: CostCategory[]): Record<string, number> {
  const map: Record<string, number> = {};
  for (const cat of categories) {
    for (const act of cat.actions ?? []) {
      map[act.action] = act.cost;
    }
  }
  return map;
}

/**
 * Price list for the signed-in workspace.
 *
 * HRP-509: `/billing/costs` is the public, tenant-agnostic base list —
 * LLM actions are charged `base x model multiplier`, so quoting it made a
 * workspace on a heavier model see 200 and pay 340. `/billing/costs/effective`
 * returns the numbers the charge path computes. Falls back to the public
 * list when the effective endpoint is unavailable (no token yet, community
 * build) so the badge degrades instead of disappearing.
 */
export async function fetchCosts(): Promise<Record<string, number>> {
  if (costsCacheIsFresh()) return costsCache as Record<string, number>;
  if (costsFetchPromise) return costsFetchPromise;

  const token =
    typeof window !== "undefined" ? localStorage.getItem("access_token") : null;

  const pending = (async (): Promise<Record<string, number>> => {
    const generation = costsCacheGeneration;
    let categories: CostCategory[] | null = null;
    if (token) {
      // Through the api client, not a raw fetch: an expired access token
      // must go through the 401-refresh pipeline rather than silently
      // degrade to the tenant-agnostic base list — quoting the base price
      // while charging the multiplied one is the exact HRP-509 defect
      // this endpoint exists to fix (review fix). A 404 (community build)
      // or any other failure falls through to the public list.
      try {
        const effective = await api.get<CostCategory[]>(
          "/billing/costs/effective",
        );
        // An empty list is not a price list — fall back rather than
        // caching "everything is free" for the TTL (review fix).
        if (Array.isArray(effective) && effective.length > 0) {
          categories = effective;
        }
      } catch {
        categories = null;
      }
    }
    if (categories === null) {
      try {
        const res = await fetch(`${API_BASE}/billing/costs`);
        const base = res.ok ? ((await res.json()) as CostCategory[]) : null;
        categories = Array.isArray(base) ? base : null;
      } catch {
        categories = null;
      }
    }
    if (categories === null) return {};
    const map = flattenCosts(categories);
    if (generation === costsCacheGeneration) {
      costsCache = map;
      costsCachedAt = Date.now();
    }
    return map;
  })();

  // Deduplicates concurrent callers, then clears itself: a promise left in
  // place would be returned forever and the TTL below could never trigger
  // a re-fetch.
  costsFetchPromise = pending;
  void pending.finally(() => {
    if (costsFetchPromise === pending) costsFetchPromise = null;
  });

  return pending;
}

/**
 * Fetch the workspace credit balance once and cache it. Returns null in
 * community builds where `/billing/credits` is not mounted (404) — callers
 * treat null as "billing disabled".
 */
async function fetchCreditBalance(): Promise<CreditBalance | null> {
  if (balanceCache) return balanceCache;
  if (balanceFetchPromise) return balanceFetchPromise;

  const token =
    typeof window !== "undefined" ? localStorage.getItem("access_token") : null;

  balanceFetchPromise = fetch(`${API_BASE}/billing/credits`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
    .then((res) => (res.ok ? res.json() : null))
    .then((data: CreditBalance | null) => {
      balanceCache = data;
      return data;
    })
    .catch(() => {
      balanceFetchPromise = null;
      return null;
    });

  return balanceFetchPromise;
}

async function fetchThreshold(): Promise<number> {
  const balance = await fetchCreditBalance();
  const t = balance?.credit_warning_threshold;
  // null → billing disabled (community build) → no confirmation.
  return typeof t === "number" ? t : 0;
}

/**
 * Drop the cached price list and balance.
 *
 * Call after anything that can change what an action costs this
 * workspace — saving AI settings (model / effort level) or a platform-admin
 * repricing — otherwise the dialog keeps quoting the old multiplier until a
 * full reload (review #3).
 */
export function invalidateCostConfirmationCache() {
  costsCache = null;
  costsCachedAt = 0;
  costsFetchPromise = null;
  costsCacheGeneration += 1;
  balanceCache = null;
  balanceFetchPromise = null;
}

/** Drop only the cached balance — call after an action spends credits. */
export function invalidateCreditBalanceCache() {
  balanceCache = null;
  balanceFetchPromise = null;
}

interface CostInfo {
  cost: number | null;
  threshold: number;
  requiresConfirmation: boolean;
}

/**
 * Returns a `confirm(action)` helper that checks billing cost vs the workspace
 * warning threshold. If cost >= threshold > 0 → user must approve a dialog.
 * Billing is SaaS-only: community/on-prem builds skip the requests entirely
 * (HRP-397) and keep the no-confirmation defaults.
 */
export function useCostConfirmation(actionKey: string) {
  const isSaas = useIsSaas();
  const [info, setInfo] = useState<CostInfo>({
    cost: null,
    threshold: 0,
    requiresConfirmation: false,
  });

  useEffect(() => {
    if (!isSaas) return;
    let cancelled = false;
    Promise.all([fetchCosts(), fetchThreshold()]).then(([map, threshold]) => {
      if (cancelled) return;
      const cost = map[actionKey] ?? null;
      const requiresConfirmation =
        threshold > 0 && cost !== null && cost >= threshold;
      setInfo({ cost, threshold, requiresConfirmation });
    });
    return () => {
      cancelled = true;
    };
  }, [actionKey, isSaas]);

  return info;
}

interface UseCostConfirmationDialogResult extends CostInfo {
  open: boolean;
  /**
   * Run `action`. If confirmation is required, opens the dialog and resolves
   * after the user confirms (or rejects with `Error("cancelled")`).
   */
  runWithConfirmation: <T>(action: () => Promise<T> | T) => Promise<T>;
  /** Internal: dialog state, exposed so a single shared dialog can be rendered. */
  setOpen: (v: boolean) => void;
  pendingLabel: string;
  /** Resolves the pending action once the user clicks "Confirm". */
  confirm: () => void;
  /** Cancels the pending action. */
  cancel: () => void;
}

interface PendingAction<T> {
  resolve: (value: T) => void;
  reject: (reason: unknown) => void;
  run: () => Promise<T> | T;
}

/**
 * Variant that owns dialog state. Use this when one component needs to gate a
 * single action behind a confirmation dialog.
 */
export function useCostConfirmationDialog(
  actionKey: string,
  label: string,
): UseCostConfirmationDialogResult {
  const info = useCostConfirmation(actionKey);
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState<PendingAction<unknown> | null>(null);

  const runWithConfirmation = useCallback(
    async <T,>(action: () => Promise<T> | T): Promise<T> => {
      if (!info.requiresConfirmation) {
        return await action();
      }
      return new Promise<T>((resolve, reject) => {
        setPending({
          resolve: resolve as (v: unknown) => void,
          reject,
          run: action as () => Promise<unknown> | unknown,
        });
        setOpen(true);
      });
    },
    [info.requiresConfirmation],
  );

  const confirm = useCallback(() => {
    if (!pending) {
      setOpen(false);
      return;
    }
    const { resolve, reject, run } = pending;
    setOpen(false);
    setPending(null);
    Promise.resolve()
      .then(() => run())
      .then(resolve)
      .catch(reject);
  }, [pending]);

  const cancel = useCallback(() => {
    if (pending) pending.reject(new Error("cancelled"));
    setPending(null);
    setOpen(false);
  }, [pending]);

  return {
    ...info,
    open,
    setOpen,
    pendingLabel: label,
    runWithConfirmation,
    confirm,
    cancel,
  };
}

export interface CreditGate {
  /** True only on SaaS deployments where credit billing is active. */
  isSaas: boolean;
  /** Server-priced cost of `action`, or null while loading / in community. */
  cost: number | null;
  /** Current workspace credit balance, or null in community. */
  balance: number | null;
  /** True when the balance is known and cannot cover `cost` (SaaS only). */
  insufficient: boolean;
  /** Re-fetch the balance after an action spends credits. */
  refresh: () => void;
}

/**
 * Billing seam for community-safe credit UI. Reads the server price list
 * (`/billing/costs`) and balance (`/billing/credits`) — both 404 in community
 * builds, so `cost`/`balance` stay null and `insufficient` stays false. Gate
 * credit labels on `isSaas` so on-prem builds never render dead SaaS copy, and
 * source the number from `cost` instead of hardcoding it (keeps the UI in sync
 * with `backend/ee/credits.yaml`).
 */
export function useCreditGate(actionKey: string): CreditGate {
  const isSaas = useIsSaas();
  const [cost, setCost] = useState<number | null>(null);
  const [balance, setBalance] = useState<number | null>(null);

  const load = useCallback(() => {
    if (!isSaas) {
      setCost(null);
      setBalance(null);
      return;
    }
    Promise.all([fetchCosts(), fetchCreditBalance()]).then(([costs, bal]) => {
      setCost(costs[actionKey] ?? null);
      // HRP-547: what can actually be spent, not the headline total —
      // credits held by an upload in flight are not available here.
      setBalance(bal?.available ?? bal?.total ?? null);
    });
  }, [actionKey, isSaas]);

  useEffect(() => {
    let cancelled = false;
    if (!isSaas) return;
    Promise.all([fetchCosts(), fetchCreditBalance()]).then(([costs, bal]) => {
      if (cancelled) return;
      setCost(costs[actionKey] ?? null);
      // HRP-547: what can actually be spent, not the headline total —
      // credits held by an upload in flight are not available here.
      setBalance(bal?.available ?? bal?.total ?? null);
    });
    return () => {
      cancelled = true;
    };
  }, [actionKey, isSaas]);

  const refresh = useCallback(() => {
    invalidateCreditBalanceCache();
    load();
  }, [load]);

  const insufficient =
    isSaas && balance !== null && cost !== null && balance < cost;

  return { isSaas, cost, balance, insufficient, refresh };
}
