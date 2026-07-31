// Source of truth for PDP status flow on the frontend.
//
// Keep PDP_STATUS_TRANSITIONS in sync with
// backend/app/modules/assessment/pdp_service.py:PDP_STATUS_TRANSITIONS.
// HRP-16 dropped on_approval / approved / expired — admin closes plans
// straight from ``review`` and overdue is now a pure UI cue (red deadline).

import { BADGE_COLOR } from "@/lib/badge-tones";

export type PDPStatus =
  | "draft"
  | "sent"
  | "in_progress"
  | "review"
  | "done"
  | "returned"
  | "cancelled";

export const PDP_STATUSES: readonly PDPStatus[] = [
  "draft",
  "sent",
  "in_progress",
  "review",
  "done",
  "returned",
  "cancelled",
] as const;

export const PDP_TERMINAL_STATUSES: readonly PDPStatus[] = [
  "done",
  "cancelled",
] as const;

// HRP-189: spec/grade is editable only while the plan is still in Draft;
// pressing Send freezes it for the rest of the lifecycle. Mirrors
// PDP_GRADE_LOCKED_STATUSES in backend/app/modules/assessment/pdp_service.py.
export const PDP_GRADE_LOCKED_STATUSES: readonly PDPStatus[] = [
  "sent",
  "in_progress",
  "review",
  "returned",
  "done",
  "cancelled",
] as const;

// HRP-188: Assessment-style status labels — `Under review` renamed to
// `On review` and `Completed` renamed to `Done` so the PDP chip wording
// matches Assessments.
//
// HRP-476: the wording itself now lives in the `development` i18n
// namespace; every caller goes through PDP_STATUS_KEYS / translatePdpStatus.
//
// HRP-476: code → key in the `development` i18n namespace (same shape as
// `components/employees/employee-status.ts` / `lib/assessment-status.ts`).
export const PDP_STATUS_KEYS: Record<PDPStatus, string> = {
  draft: "statusDraft",
  sent: "statusSent",
  in_progress: "statusInProgress",
  review: "statusReview",
  done: "statusDone",
  returned: "statusReturned",
  cancelled: "statusCancelled",
};

/** i18n key for a known status code, or `null` for anything unexpected. */
export function pdpStatusKey(status: string): string | null {
  return PDP_STATUS_KEYS[status as PDPStatus] ?? null;
}

/** Translated status label with a raw-code fallback for unknown statuses. */
export function translatePdpStatus(
  t: (key: string) => string,
  status: string,
): string {
  const key = pdpStatusKey(status);
  return key ? t(key) : status;
}

export const PDP_STATUS_COLORS: Record<PDPStatus, string> = {
  draft: BADGE_COLOR.neutral,
  sent: BADGE_COLOR.blue,
  in_progress: BADGE_COLOR.yellow,
  review: BADGE_COLOR.purple,
  done: BADGE_COLOR.green,
  returned: BADGE_COLOR.orange,
  cancelled: BADGE_COLOR.red,
};

// HRP-197: ``sent`` only exposes ``cancel`` manually — promotion to
// in_progress happens automatically when the owner ticks the first item.
// HRP-198: ``returned`` accepts ``review`` (submit for review) or
// ``cancelled``; the old ``returned → sent`` step was removed.
export const PDP_STATUS_TRANSITIONS: Record<PDPStatus, PDPStatus[]> = {
  draft: ["sent", "cancelled"],
  sent: ["cancelled"],
  in_progress: ["review", "cancelled"],
  review: ["done", "returned", "cancelled"],
  returned: ["review", "cancelled"],
  done: [],
  cancelled: [],
};

// HRP-197: statuses the admin can never set by hand from the list-page
// Change-status dialog. They're reachable only via system events
// (auto-promote when an item is ticked off in ``sent``).
export const PDP_MANUAL_BLOCKED_STATUSES: readonly PDPStatus[] = [
  "in_progress",
] as const;

export function isManualBlockedPDPStatus(status: string): boolean {
  return (PDP_MANUAL_BLOCKED_STATUSES as readonly string[]).includes(status);
}

export const PDP_STATUS_OPTIONS: readonly PDPStatus[] = PDP_STATUSES;

export function isTerminalPDPStatus(status: string): boolean {
  return (PDP_TERMINAL_STATUSES as readonly string[]).includes(status);
}

export function isPDPGradeLocked(status: string): boolean {
  return (PDP_GRADE_LOCKED_STATUSES as readonly string[]).includes(status);
}

export function pdpStatusColor(status: string): string {
  return PDP_STATUS_COLORS[status as PDPStatus] ?? "";
}

export function pdpNextStatuses(status: string): PDPStatus[] {
  return PDP_STATUS_TRANSITIONS[status as PDPStatus] ?? [];
}

// Action-button labels — short verbs that read naturally on a button
// ("send", "cancel"), distinct from the status names shown on badges.
//
// HRP-476: only the code → key relation lives here; the wording is in the
// `development` i18n namespace.
export const PDP_STATUS_ACTION_KEYS: Record<PDPStatus, string> = {
  draft: "actionDraft",
  sent: "actionSend",
  in_progress: "actionStart",
  review: "actionSubmitForReview",
  done: "actionComplete",
  returned: "actionReturn",
  cancelled: "actionCancel",
};

/** i18n key for a status action verb, or `null` for unknown statuses. */
export function pdpStatusActionKey(status: string): string | null {
  return PDP_STATUS_ACTION_KEYS[status as PDPStatus] ?? null;
}

/** Translated action verb with a raw-code fallback for unknown statuses. */
export function translatePdpStatusAction(
  t: (key: string) => string,
  status: string,
): string {
  const key = pdpStatusActionKey(status);
  return key ? t(key) : status;
}
