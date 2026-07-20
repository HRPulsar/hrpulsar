// HRP-247 / HRP-246: shared formulas for the Employee profile header
// KPI tiles. Lives outside the page so the (i) tooltip wording, the
// Assessments / Goals KPI sub-line and vitest can agree on what "open"
// means without diverging.

import {
  ASSESSMENT_TERMINAL_STATUSES,
  type AssessmentStatusCode,
} from "@/lib/assessment-status";
import { PDP_TERMINAL_STATUSES, type PDPStatus } from "@/lib/pdp-status";

const PDP_TERMINAL: ReadonlySet<string> = new Set<string>(PDP_TERMINAL_STATUSES);

export interface OpenPdpInput {
  status: string;
  total_progress: number;
}

export interface OpenAssessmentInput {
  status_code: string;
}

export function isOpenPdp(p: OpenPdpInput): boolean {
  // HRP-246: "open" excludes both Done and Cancelled. The previous code
  // compared against a non-existent ``"completed"`` literal — PDPs use
  // ``done`` for the terminal success status (see `PDPStatus`) — so the
  // count silently included Done / Cancelled plans.
  return !PDP_TERMINAL.has(p.status as PDPStatus);
}

export function isOpenAssessment(a: OpenAssessmentInput): boolean {
  // HRP-246: same definition the Assessments tab list uses — Done and
  // Cancelled are terminal; everything else (Draft, Sent, In progress,
  // On review) counts as open.
  return !ASSESSMENT_TERMINAL_STATUSES.has(a.status_code as AssessmentStatusCode);
}

/**
 * Returns the average of `total_progress` across open PDPs, rounded to
 * the nearest integer. `null` means the employee has no open plans, so
 * the caller should render a dash instead of "0%".
 *
 * HRP-247: explanation surfaced verbatim in the Goals progress tooltip
 * — keep the wording there in sync with this docstring.
 */
export function goalsProgressPercent(pdps: OpenPdpInput[]): number | null {
  const open = pdps.filter(isOpenPdp);
  if (open.length === 0) return null;
  const sum = open.reduce((acc, p) => acc + (p.total_progress ?? 0), 0);
  return Math.round(sum / open.length);
}

export function openPdpCount(pdps: OpenPdpInput[]): number {
  return pdps.filter(isOpenPdp).length;
}

export function openAssessmentCount(asmts: OpenAssessmentInput[]): number {
  return asmts.filter(isOpenAssessment).length;
}
