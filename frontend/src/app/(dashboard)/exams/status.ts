// HRP-236: status model + chip colors for mass exams.
//
// Backend codes: draft | sent | in_progress | done | cancelled (MassExam),
// plus assigned (per-employee Exam row before the first answer).
// Labels mirror the UX in Assessment / Development plan / Talent Market.

import { BADGE_COLOR } from "@/lib/badge-tones";

// HRP-476: only the code → key relation lives here; the wording is in the
// `exams` i18n namespace (same shape as `lib/assessment-status.ts`).
export const STATUS_KEYS: Record<string, string> = {
  draft: "statusDraft",
  sent: "statusSent",
  assigned: "statusAssigned",
  in_progress: "statusInProgress",
  done: "statusDone",
  cancelled: "statusCancelled",
};

export const STATUS_CHIP_COLOR: Record<string, string> = {
  draft: BADGE_COLOR.neutral,
  sent: BADGE_COLOR.blue,
  assigned: BADGE_COLOR.blue,
  in_progress: BADGE_COLOR.yellow,
  done: BADGE_COLOR.green,
  cancelled: BADGE_COLOR.red,
};

export const TERMINAL_STATUSES = new Set(["done", "cancelled"]);

// HRP-234 / HRP-236: only manager-initiated transitions live here. The
// sent → in_progress hop is automatic on the first answer.
export const STATUS_TRANSITIONS: Record<string, string[]> = {
  draft: ["sent", "cancelled"],
  sent: ["cancelled"],
  in_progress: ["done", "cancelled"],
  done: [],
  cancelled: [],
};

/** i18n key for a known status code, or `null` for anything unexpected. */
export function statusKey(code: string): string | null {
  return STATUS_KEYS[code] ?? null;
}

/** Translated status label with a raw-code fallback for unknown statuses. */
export function statusLabel(
  t: (key: string) => string,
  code: string,
): string {
  const key = statusKey(code);
  return key ? t(key) : code;
}

export function isTerminalStatus(code: string): boolean {
  return TERMINAL_STATUSES.has(code);
}
