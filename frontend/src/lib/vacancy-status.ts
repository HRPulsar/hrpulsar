// HRP-476 (i18n F2): the vacancy status machine the recruitment UI renders.
//
// The list page and the detail page each carried their own inline
// `statusColors` map plus an ad-hoc `charAt(0).toUpperCase()` label, so the
// wording drifted between the badge (raw lowercase code) and the filter
// dropdown (title case). Both places now pull from here, and the wording
// itself lives in the `recruitment` i18n namespace — this module only owns
// the code → key relation (same shape as `lib/assessment-status.ts`).
//
// Two key families on purpose: the badge keeps the lowercase rendering it
// had before ("draft", "open", …, matching the existing `vacancyBadgeArchived`
// wording), while the status filter keeps its capitalised options.

import { BADGE_COLOR } from "@/lib/badge-tones";

export type VacancyStatusCode =
  | "draft"
  | "open"
  | "paused"
  | "closed"
  | "cancelled";

/** Statuses offered by the list page filter, in display order. */
export const VACANCY_STATUS_OPTIONS = [
  "draft",
  "open",
  "paused",
  "closed",
  "cancelled",
] as const satisfies readonly VacancyStatusCode[];

export const VACANCY_STATUS_COLORS: Record<string, string> = {
  draft: BADGE_COLOR.neutral,
  open: BADGE_COLOR.green,
  paused: BADGE_COLOR.yellow,
  closed: BADGE_COLOR.red,
  cancelled: BADGE_COLOR.neutral,
};

/** Lowercase badge wording (`recruitment` namespace). */
const VACANCY_STATUS_BADGE_KEYS: Record<VacancyStatusCode, string> = {
  draft: "vacancyBadgeDraft",
  open: "vacancyBadgeOpen",
  paused: "vacancyBadgePaused",
  closed: "vacancyBadgeClosed",
  cancelled: "vacancyBadgeCancelled",
};

/** Capitalised filter-option wording (`recruitment` namespace). */
const VACANCY_STATUS_OPTION_KEYS: Record<VacancyStatusCode, string> = {
  draft: "vacancyStatusDraft",
  open: "vacancyStatusOpen",
  paused: "vacancyStatusPaused",
  closed: "vacancyStatusClosed",
  cancelled: "vacancyStatusCancelled",
};

/** Badge i18n key for a known status code, or `null` for anything else. */
export function vacancyStatusBadgeKey(status: string): string | null {
  return VACANCY_STATUS_BADGE_KEYS[status as VacancyStatusCode] ?? null;
}

/** Filter-option i18n key for a known status code, or `null`. */
export function vacancyStatusOptionKey(status: string): string | null {
  return VACANCY_STATUS_OPTION_KEYS[status as VacancyStatusCode] ?? null;
}

/** Badge label; unknown codes fall back to the raw code (pre-i18n render). */
export function vacancyStatusBadgeLabel(
  t: (key: string) => string,
  status: string,
): string {
  const key = vacancyStatusBadgeKey(status);
  return key ? t(key) : status;
}

/** Filter-option label; unknown codes keep the previous capitalisation. */
export function vacancyStatusOptionLabel(
  t: (key: string) => string,
  status: string,
): string {
  const key = vacancyStatusOptionKey(status);
  return key ? t(key) : status.charAt(0).toUpperCase() + status.slice(1);
}
