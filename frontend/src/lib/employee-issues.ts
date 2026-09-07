// HRP-638: the dashboard links into the employee list with the cohort it
// just counted, and the list names every problem a row has. Both halves
// read the codes from here.
//
// Mirrors backend/app/modules/employee/issues.py (development-loop codes)
// and employee/alerts.py (profile-hygiene codes). Adding a code on either
// side without adding it here renders a badge with no label.

import type { EmployeeIssueCode } from "@/lib/types";

// The subset ``GET /employees?issue=`` accepts — the development-loop codes
// the dashboard tiles and findings are built from. The hygiene codes are
// display-only: filtering by them would need a tenant-wide profile scan for
// a question `unassigned_only` and the status filter already answer.
// ponytail: display/filter split, widen the API literal if HR asks for it.
export const FILTERABLE_ISSUE_CODES = [
  "gaps_without_plan",
  "competence_gap",
  "pdp_overdue",
  "pdp_stuck_review",
  "assessment_stale",
] as const;

// Badge tone by how urgent the problem is: rose blocks, amber needs
// attention, violet is waiting on someone, blue/neutral is informational.
export const ISSUE_TONE: Record<EmployeeIssueCode, string> = {
  user_inactive:
    "border-rose-300 bg-rose-50 text-rose-700 dark:border-rose-800 dark:bg-rose-950 dark:text-rose-300",
  profile_incomplete:
    "border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-300",
  assessment_overdue:
    "border-rose-300 bg-rose-50 text-rose-700 dark:border-rose-800 dark:bg-rose-950 dark:text-rose-300",
  assessment_pending:
    "border-blue-300 bg-blue-50 text-blue-700 dark:border-blue-800 dark:bg-blue-950 dark:text-blue-300",
  pdp_pending_review:
    "border-violet-300 bg-violet-50 text-violet-700 dark:border-violet-800 dark:bg-violet-950 dark:text-violet-300",
  pdp_overdue:
    "border-rose-300 bg-rose-50 text-rose-700 dark:border-rose-800 dark:bg-rose-950 dark:text-rose-300",
  // HRP-656: a gap nobody is working on is the alarm — a gap with an open
  // plan stays amber under `competence_gap`.
  gaps_without_plan:
    "border-rose-300 bg-rose-50 text-rose-700 dark:border-rose-800 dark:bg-rose-950 dark:text-rose-300",
  competence_gap:
    "border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-300",
  pdp_stuck_review:
    "border-violet-300 bg-violet-50 text-violet-700 dark:border-violet-800 dark:bg-violet-950 dark:text-violet-300",
  assessment_stale:
    "border-border bg-muted text-muted-foreground",
};

// HRP-660: one competence row is a gap when its score sits below the passing
// bar of the assessment that produced it — the same rule `competence_gap`
// applies in backend/app/modules/employee/issues.py, narrowed to a single
// row. A row with no score is "never assessed", not a gap: the badge would
// accuse the employee of failing something nobody measured.
/**
 * HRP-731: the one growth-zone / gap rule, twin of ``is_gap`` in
 * employee/issues.py.
 *
 * At or below the bar is a gap. The boundary is inclusive on purpose —
 * scoring exactly the bar is not a closed competence — and the two sides
 * must never disagree about it.
 */
export function isGap(percent: number, bar: number): boolean {
  return percent <= bar;
}

/** The same rule for the row shape the competence surfaces carry. */
export function isCompetenceGap(row: {
  percent: number | null;
  passing_score: number;
}): boolean {
  // A never-assessed competence has no verdict either way.
  return row.percent !== null && isGap(row.percent, row.passing_score);
}

/**
 * HRP-731: the bar a single assessment's results are judged against.
 *
 * Mirrors ``passing_bar`` in employee/issues.py: the assessment's own
 * snapshot when it has one, else the product default. Assessments built
 * from "Individual competences" criteria never store a bar, so the default
 * is what their results are read against.
 */
export const DEFAULT_PASSING_SCORE = 75;

export function assessmentBar(passingScore: number | null | undefined): number {
  // Identity check, not truthiness: 0 is a legitimate stored bar.
  return passingScore === null || passingScore === undefined
    ? DEFAULT_PASSING_SCORE
    : passingScore;
}
