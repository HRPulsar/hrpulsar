// HRP-27 / HRP-115 / HRP-116 / HRP-117: the assessment status machine
// the UI walks must match the server's. Both the list page (bulk Change
// Status modal) and the detail page (Details action buttons) pull from
// here so the on_review checkpoint shows up consistently, and vitest can
// pin the transitions without rendering React.

import { BADGE_COLOR } from "@/lib/badge-tones";

export type AssessmentStatusCode =
  | "draft"
  | "sent"
  | "in_progress"
  | "on_review"
  | "done"
  | "cancelled";

export const ASSESSMENT_STATUS_OPTIONS = [
  "draft",
  "sent",
  "in_progress",
  "on_review",
  "done",
  "cancelled",
] as const satisfies readonly AssessmentStatusCode[];

// Callers receive `status_code` as a raw string from the API — widening the
// key type here saves them from casting `as AssessmentStatusCode` at every
// `.has(...)` / index lookup. Unknown codes fall through to "no transitions"
// / "not terminal", matching the previous string-keyed maps.
export const ASSESSMENT_TERMINAL_STATUSES: ReadonlySet<string> = new Set([
  "done",
  "cancelled",
]);

/** Allowed forward transitions when the operator drives the assessment by
 *  hand. Done is reachable only from on_review — the backend enforces the
 *  same rule, so the Details buttons must not offer the shortcut. The
 *  auto-flip from in_progress into on_review fires server-side once every
 *  participant has completed and bypasses this map entirely.
 *
 *  HRP-192: in_progress is also auto-only — the first submitted answer
 *  flips Sent → In progress server-side. Operators cannot drive that
 *  transition manually, so it never appears as a target here. The Change
 *  status / Change status (all) modals additionally grey the option out
 *  with a tooltip so the choice stays visible but unselectable.
 */
export const ASSESSMENT_STATUS_FLOW: Readonly<Record<string, AssessmentStatusCode[]>> = {
  draft: ["sent"],
  sent: ["cancelled"],
  in_progress: ["on_review", "cancelled"],
  on_review: ["done", "cancelled"],
  done: [],
  cancelled: [],
};

// HRP-192: codes that the manual Change status / Change status (all)
// modals must render as disabled (instead of hidden) so the user sees
// the option exists but can't pick it. Pairs with MANUAL_FORBIDDEN_TOOLTIP.
export const ASSESSMENT_MANUAL_FORBIDDEN_STATUSES: ReadonlySet<string> = new Set([
  "in_progress",
]);

export const ASSESSMENT_MANUAL_FORBIDDEN_TOOLTIP = "Manual transition is not allowed";

export const ASSESSMENT_STATUS_COLORS: Record<string, string> = {
  draft: BADGE_COLOR.neutral,
  sent: BADGE_COLOR.blue,
  in_progress: BADGE_COLOR.yellow,
  on_review: BADGE_COLOR.purple,
  done: BADGE_COLOR.green,
  cancelled: BADGE_COLOR.red,
};

// HRP-194: filter dropdowns and Change status modals used to render raw
// status codes ("in_progress", "on_review"). Mirror the badge wording the
// backend ships in `status_title` so the UI reads consistently across the
// list page, group page, and details pane. Mirrors PDP_STATUS_LABELS.
export const ASSESSMENT_STATUS_LABELS: Record<AssessmentStatusCode, string> = {
  draft: "Draft",
  sent: "Sent",
  in_progress: "In progress",
  on_review: "On review",
  done: "Done",
  cancelled: "Cancelled",
};

export function assessmentStatusLabel(status: string): string {
  return ASSESSMENT_STATUS_LABELS[status as AssessmentStatusCode] ?? status;
}

// HRP-166: the list views surface a single date per row whose label tracks
// the lifecycle bucket — active rows show when they were created, terminal
// rows show when they entered Done/Cancelled. Centralised so the main list
// and the employee Assessments tab stay consistent.
export function assessmentRowDate(a: {
  status_code: string;
  created_at: string;
  finished_at: string | null;
}): { label: "Created" | "Completed" | "Cancelled"; iso: string } {
  if (a.status_code === "done") {
    return { label: "Completed", iso: a.finished_at ?? a.created_at };
  }
  if (a.status_code === "cancelled") {
    return { label: "Cancelled", iso: a.finished_at ?? a.created_at };
  }
  return { label: "Created", iso: a.created_at };
}
