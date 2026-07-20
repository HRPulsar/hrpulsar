// HRP-236: status model + chip colors for mass exams.
//
// Backend codes: draft | sent | in_progress | done | cancelled (MassExam),
// plus assigned (per-employee Exam row before the first answer).
// Labels mirror the UX in Assessment / Development plan / Talent Market.

import { BADGE_COLOR } from "@/lib/badge-tones";

export const STATUS_LABELS: Record<string, string> = {
  draft: "Draft",
  sent: "Sent",
  assigned: "Assigned",
  in_progress: "In progress",
  done: "Completed",
  cancelled: "Cancelled",
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

export function statusLabel(code: string): string {
  return STATUS_LABELS[code] ?? code;
}

export function isTerminalStatus(code: string): boolean {
  return TERMINAL_STATUSES.has(code);
}
