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
export const PDP_STATUS_LABELS: Record<PDPStatus, string> = {
  draft: "Draft",
  sent: "Sent",
  in_progress: "In progress",
  review: "On review",
  done: "Done",
  returned: "Returned",
  cancelled: "Cancelled",
};

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

export function pdpStatusLabel(status: string): string {
  return PDP_STATUS_LABELS[status as PDPStatus] ?? status;
}

export function pdpStatusColor(status: string): string {
  return PDP_STATUS_COLORS[status as PDPStatus] ?? "";
}

export function pdpNextStatuses(status: string): PDPStatus[] {
  return PDP_STATUS_TRANSITIONS[status as PDPStatus] ?? [];
}

// Action-button labels — short English verbs that read naturally on a button
// ("send", "cancel"), distinct from PDP_STATUS_LABELS (full status names
// shown on badges).
export const PDP_STATUS_ACTION_LABELS: Record<PDPStatus, string> = {
  draft: "draft",
  sent: "send",
  in_progress: "start",
  review: "submit for review",
  done: "complete",
  returned: "return",
  cancelled: "cancel",
};

export function pdpStatusActionLabel(status: string): string {
  return PDP_STATUS_ACTION_LABELS[status as PDPStatus] ?? status;
}
