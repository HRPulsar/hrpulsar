"use client";

import { useCallback } from "react";
import { useTranslations } from "next-intl";

/** `create_event` → `Create Event` — the label a code carries with no catalog key. */
export function humanizeAction(name: string): string {
  return name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// HRP-653: the price catalog is tenant-agnostic — the server does not know
// who is reading it, so `credits.yaml` ships one English label per category
// and per action and the translation happens here, keyed by the code. A
// code the catalog has no key for (a new entry in credits.yaml) falls back
// to the server label, so the page grows a row instead of breaking.
export function useCatalogLabel(prefix: "billingCategory" | "billingAction") {
  const t = useTranslations("settings");
  // Stable identity: the search memo in the Prices page depends on it.
  return useCallback(
    (code: string, fallback: string): string => {
      const key = `${prefix}.${code}`;
      return t.has(key) ? t(key) : fallback;
    },
    [t, prefix],
  );
}

// HRP-671: spending analytics and the transaction history render whole
// action codes, which are dotted — `employee.create`, and `.refund` appended
// on a refund row (`employee.create.refund`). The catalog keys the segments
// separately (`billingCategory.employee` + `billingAction.create`), so the
// code is translated segment by segment; anything the catalog misses stays
// readable through `humanizeAction`. Dotless codes (`purchase`,
// `monthly_refill`) are action codes on their own.
export function useBillingActionLabel(): (code: string) => string {
  const categoryLabel = useCatalogLabel("billingCategory");
  const actionLabel = useCatalogLabel("billingAction");
  return useCallback(
    (code: string): string => {
      const [head, ...rest] = code.split(".");
      if (rest.length === 0) return actionLabel(head, humanizeAction(head));
      return [
        categoryLabel(head, humanizeAction(head)),
        ...rest.map((part) => actionLabel(part, humanizeAction(part))),
      ].join(" · ");
    },
    [categoryLabel, actionLabel],
  );
}
