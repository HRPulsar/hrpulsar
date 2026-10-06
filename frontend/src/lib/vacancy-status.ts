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
function vacancyStatusBadgeKey(status: string): string | null {
  return VACANCY_STATUS_BADGE_KEYS[status as VacancyStatusCode] ?? null;
}

/** Filter-option i18n key for a known status code, or `null`. */
function vacancyStatusOptionKey(status: string): string | null {
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

// HRP-836: what a vacancy's status freezes, surface by surface. Mirror of
// ``VACANCY_LOCKED_SURFACES`` in backend/app/modules/recruitment/common.py,
// which answers 409 on the same surfaces. A paused vacancy stops the
// interview work on its candidates; a closed or cancelled one is read-only
// as a whole, AI Insights included.
export type VacancySurface =
  | "vacancy"
  | "ai_insights"
  | "questions"
  | "interviews"
  | "manager_assessments";

const FROZEN_WHEN_ENDED: readonly VacancySurface[] = [
  "vacancy",
  "ai_insights",
  "questions",
  "interviews",
  "manager_assessments",
];

export const VACANCY_READ_ONLY_SURFACES: Record<
  string,
  readonly VacancySurface[]
> = {
  paused: ["questions", "interviews", "manager_assessments"],
  closed: FROZEN_WHEN_ENDED,
  cancelled: FROZEN_WHEN_ENDED,
};

export function vacancyLocks(
  status: string | null | undefined,
  surface: VacancySurface,
): boolean {
  return (VACANCY_READ_ONLY_SURFACES[status ?? ""] ?? []).includes(surface);
}

// HRP-427 / HRP-836: the lifecycle commands of the kebab menu, between
// Edit and Archive, in the order the tickets list them. Closed and
// cancelled are final — they offer none (and no Edit either).
export type VacancyStatusCommand =
  | "publish"
  | "pause"
  | "reopen"
  | "close"
  | "cancel";

export const VACANCY_STATUS_COMMANDS: Record<
  string,
  readonly VacancyStatusCommand[]
> = {
  draft: ["publish"],
  open: ["pause", "close", "cancel"],
  paused: ["reopen", "close", "cancel"],
};

/** Target status per command; ``close`` goes through ``/close`` instead. */
export const VACANCY_COMMAND_TARGET: Record<
  Exclude<VacancyStatusCommand, "close">,
  "open" | "paused" | "cancelled"
> = {
  publish: "open",
  pause: "paused",
  reopen: "open",
  cancel: "cancelled",
};

// HRP-836: the two close resolutions, as the backend stores them.
export type VacancyCloseResolution = "hired" | "closed_no_hire";

const VACANCY_RESOLUTION_KEYS: Record<VacancyCloseResolution, string> = {
  hired: "vacancyResolutionHired",
  closed_no_hire: "vacancyResolutionNoHire",
};

/** "Closed with hiring" / "Closed without hiring"; null for anything else. */
export function vacancyResolutionLabel(
  t: (key: string) => string,
  resolution: string | null | undefined,
): string | null {
  const key = VACANCY_RESOLUTION_KEYS[resolution as VacancyCloseResolution];
  return key ? t(key) : null;
}
