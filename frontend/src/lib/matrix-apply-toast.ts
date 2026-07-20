// HRP-105: shared helper so the Position card and the spec AI Generate
// page agree on when Apply did nothing visible. Warning fires only when
// both arrays are empty — grade-link-only applies still moved the matrix.

import type { ApplyResult } from "@/lib/api/competence-generation";

export type ApplyToastKind = "warning" | "success";

export interface ApplyToastDecision {
  kind: ApplyToastKind;
  addedCompetences: number;
  addedGradeLinks: number;
}

export function resolveApplyToast(result: ApplyResult): ApplyToastDecision {
  const addedCompetences = result.created_competences.length;
  const addedGradeLinks = result.created_grade_links.length;
  const kind: ApplyToastKind =
    addedCompetences === 0 && addedGradeLinks === 0 ? "warning" : "success";
  return { kind, addedCompetences, addedGradeLinks };
}
