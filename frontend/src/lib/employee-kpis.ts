// HRP-247 / HRP-246: shared formulas for the Employee profile header
// KPI tiles. Lives outside the page so the (i) tooltip wording, the
// Assessments / Goals KPI sub-line and vitest can agree on what "open"
// means without diverging.

import {
  ASSESSMENT_RUNNING_STATUSES,
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

export function isRunningAssessment(a: OpenAssessmentInput): boolean {
  // HRP-736: the Last assessment tile's "running" state mirrors the
  // server's set, which is narrower than "open" — a Draft is not running.
  return ASSESSMENT_RUNNING_STATUSES.has(a.status_code);
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

export interface LastAssessmentInput {
  status_code: string;
  finished_at?: string | null;
}

/**
 * HRP-736: the newest **completed** assessment, or `undefined` when the
 * employee has none.
 *
 * The Last assessment tile answers "when did we last learn something about
 * this person". Only a Done assessment answers it — an assessment still
 * running has no approved result and its percentages can still move in
 * calibration. This is the same rule the "No recent assessment" chip and
 * the dashboard queue use (``STALE_DAYS`` in employee/issues.py), so the
 * header can no longer contradict the chip sitting two lines above it.
 *
 * Dated by ``finished_at`` only: ``assessed_recent`` skips undated rows,
 * so dating one by ``created_at`` here could put "12 d" next to a
 * "No recent assessment" chip. Cancelled assessments never count.
 */
export function latestDoneAssessment<T extends LastAssessmentInput>(
  asmts: T[],
): (T & { finished_at: string }) | undefined {
  return asmts
    .filter(
      (a): a is T & { finished_at: string } =>
        a.status_code === "done" && !!a.finished_at,
    )
    .reduce<(T & { finished_at: string }) | undefined>(
      (best, a) =>
        best === undefined || completedAt(a) > completedAt(best) ? a : best,
      undefined,
    );
}

function completedAt(a: { finished_at: string }): number {
  return new Date(a.finished_at).getTime();
}

/** HRP-736: how long ago that assessment was completed, in whole days. */
export function daysSinceCompleted(a: { finished_at: string }, now = Date.now()): number {
  return Math.max(0, Math.floor((now - completedAt(a)) / (24 * 3600 * 1000)));
}
