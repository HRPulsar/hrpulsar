"use client";

import { useTranslations } from "next-intl";

import type {
  AssessmentCompetence,
  CriteriaType,
} from "@/lib/types";
import { dictionaryItemLabel, skillLevelLabel } from "@/lib/reference-labels";
import { Badge } from "@/components/ui/badge";

/** Criteria type codes → keys in the `assessments` i18n namespace. */
export const CRITERIA_TYPE_KEYS: Record<CriteriaType, string> = {
  current_positions: "criteriaTypeCurrentPositions",
  target_position: "criteriaTypeTargetPosition",
  competences: "criteriaTypeCompetences",
};

/**
 * HRP-98: pure helpers for the Evaluation criteria block layout so the
 * conditional logic is unit-testable without a React renderer.
 */
export function formatCriteriaTypeValue(
  t: (key: string) => string,
  criteriaType: CriteriaType,
  specializationTitle: string | null,
  gradeTitle: string | null,
  gradeId: string | null,
): string {
  const typeLabel = t(CRITERIA_TYPE_KEYS[criteriaType]);
  if (criteriaType !== "target_position") {
    return typeLabel;
  }
  const parts = [
    specializationTitle,
    gradeId ? gradeTitle : t("allGrades"),
  ].filter((part): part is string => Boolean(part));
  if (parts.length === 0) {
    return typeLabel;
  }
  return `${typeLabel}: ${parts.join(" - ")}`;
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
  // HRP-479: reference.dictionary.* keys for origin rows; the titles are
  // resolved before entering the pure `formatCriteriaTypeValue` helper.
  specializationI18nKey?: string | null;
  gradeI18nKey?: string | null;
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
  specializationI18nKey,
  gradeI18nKey,
  gradeId,
  competences,
  isMassParent = false,
}: CriteriaSummaryProps) {
  const t = useTranslations("assessments");
  const tRef = useTranslations("reference");

  if (!criteriaType) {
    return (
      <p className="py-4 text-center text-sm text-muted-foreground">
        {t("noCriteriaYet")}
      </p>
    );
  }

  const typeValue = formatCriteriaTypeValue(
    t,
    criteriaType,
    specializationTitle === null
      ? null
      : dictionaryItemLabel(tRef, {
          type: "specialization",
          title: specializationTitle,
          i18n_key: specializationI18nKey,
        }),
    gradeTitle === null
      ? null
      : dictionaryItemLabel(tRef, {
          type: "grade",
          title: gradeTitle,
          i18n_key: gradeI18nKey,
        }),
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
      <Field
        label={t("fieldType")}
        value={<span className="font-medium">{typeValue}</span>}
      />

      {showCurrentPositionsHint && (
        <p className="text-xs text-muted-foreground">
          {t("criteriaCurrentPositionsHint")}
        </p>
      )}

      {showCompetencesBlock && (
        <Field
          label={t("fieldCompetences")}
          value={
            <div className="flex flex-wrap gap-1.5">
              {competences.map((c) => (
                <Badge key={c.competence_id} variant="secondary">
                  {c.competence_title}
                  {c.skill_level_title && (
                    <span className="ml-1 text-muted-foreground">
                      ·{" "}
                      {skillLevelLabel(tRef, {
                        title: c.skill_level_title,
                        i18n_key: c.skill_level_i18n_key,
                      })}
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
