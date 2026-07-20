"use client";

import type {
  AssessmentCompetence,
  CriteriaType,
} from "@/lib/types";
import { Badge } from "@/components/ui/badge";

const TYPE_LABEL: Record<CriteriaType, string> = {
  current_positions: "Employees' current positions",
  target_position: "Target position",
  competences: "Individual competences",
};

/**
 * HRP-98: pure helpers for the Evaluation criteria block layout so the
 * conditional logic is unit-testable without a React renderer.
 */
export function formatCriteriaTypeValue(
  criteriaType: CriteriaType,
  specializationTitle: string | null,
  gradeTitle: string | null,
  gradeId: string | null,
): string {
  if (criteriaType !== "target_position") {
    return TYPE_LABEL[criteriaType];
  }
  const parts = [
    specializationTitle,
    gradeId ? gradeTitle : "All grades",
  ].filter((part): part is string => Boolean(part));
  if (parts.length === 0) {
    return TYPE_LABEL[criteriaType];
  }
  return `${TYPE_LABEL[criteriaType]}: ${parts.join(" - ")}`;
}

export function shouldShowCurrentPositionsHint(
  criteriaType: CriteriaType | null,
  isMassParent: boolean,
): boolean {
  return criteriaType === "current_positions" && isMassParent;
}

export function shouldShowCompetencesBlock(
  criteriaType: CriteriaType | null,
  competencesCount: number,
  isMassParent: boolean,
): boolean {
  if (competencesCount === 0) return false;
  if (isMassParent && criteriaType === "current_positions") return false;
  return true;
}

export interface CriteriaSummaryProps {
  criteriaType: CriteriaType | null;
  specializationTitle: string | null;
  gradeTitle: string | null;
  gradeId: string | null;
  competences: AssessmentCompetence[];
  /**
   * HRP-98: on the mass-assessment parent page, competences vary per child
   * employee's position, so the parent only shows the helper text and hides
   * the aggregated Competences block.
   */
  isMassParent?: boolean;
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[140px_1fr] items-baseline gap-2">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-sm">{value}</span>
    </div>
  );
}

export function CriteriaSummary({
  criteriaType,
  specializationTitle,
  gradeTitle,
  gradeId,
  competences,
  isMassParent = false,
}: CriteriaSummaryProps) {
  if (!criteriaType) {
    return (
      <p className="py-4 text-center text-sm text-muted-foreground">
        No evaluation criteria selected yet.
      </p>
    );
  }

  const typeValue = formatCriteriaTypeValue(
    criteriaType,
    specializationTitle,
    gradeTitle,
    gradeId,
  );
  const showCurrentPositionsHint = shouldShowCurrentPositionsHint(
    criteriaType,
    isMassParent,
  );
  const showCompetencesBlock = shouldShowCompetencesBlock(
    criteriaType,
    competences.length,
    isMassParent,
  );

  return (
    <div className="space-y-3">
      <Field label="Type" value={<span className="font-medium">{typeValue}</span>} />

      {showCurrentPositionsHint && (
        <p className="text-xs text-muted-foreground">
          Competences are picked automatically from each employee&apos;s current position.
        </p>
      )}

      {showCompetencesBlock && (
        <Field
          label="Competences"
          value={
            <div className="flex flex-wrap gap-1.5">
              {competences.map((c) => (
                <Badge key={c.competence_id} variant="secondary">
                  {c.competence_title}
                  {c.skill_level_title && (
                    <span className="ml-1 text-muted-foreground">
                      · {c.skill_level_title}
                    </span>
                  )}
                </Badge>
              ))}
            </div>
          }
        />
      )}
    </div>
  );
}
