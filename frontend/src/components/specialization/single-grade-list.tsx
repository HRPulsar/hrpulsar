// HRP-157 REDO: dedicated layout for a competence matrix that only has
// one grade configured. The QA REDO killed the previous "narrow table"
// attempt because the empty band on the right and the floating delete
// icons read as a broken table. This file owns the list paradigm — one
// row per competence with a color-coded level chip, fixed-width
// selector, and a delete button on a strict right-aligned axis.

"use client";

import { useState } from "react";
import Link from "next/link";
import {
  AlertCircle,
  CircleDollarSign,
  ExternalLink,
  X,
} from "lucide-react";
import { useTranslations } from "next-intl";

import { dictionaryItemLabel } from "@/lib/reference-labels";
import { toast } from "sonner";

import { specializationsApi, type SpecializationGrade } from "@/lib/api/specializations";
import type { Competence, SkillLevel } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { MatrixCell } from "@/components/specialization/matrix-cell";
import { ActiveAiSessionBadge } from "@/components/competence-generation/ActiveAiSessionBadge";
import type { ActiveAiSession } from "@/hooks/use-active-ai-sessions";
import { activeAiSessionsKey } from "@/hooks/use-active-ai-sessions";
import { coverageGapMessage, levelHueClass } from "@/lib/matrix-grading";
import { cn } from "@/lib/utils";

type Props = {
  specId: string;
  grade: SpecializationGrade;
  highlighted: boolean;
  competences: Competence[];
  competenceTitles: Map<string, string>;
  editState: Record<string, string | null>;
  sortedLevels: SkillLevel[];
  activeSessionsMap?: Map<string, ActiveAiSession[]>;
  onOpenActiveSession?: (sessionId: string) => void;
  saving: boolean;
  onLevelChange: (competenceId: string, levelId: string | null) => void;
  cellIsDirty: (competenceId: string) => boolean;
  onShowIndicators: (competenceId: string, levelId: string | null) => void;
  onRemoveCompetence: (competenceId: string) => void;
  onGradeUpdated: (next: SpecializationGrade) => void;
  onGradeRemoved: (gradeId: string) => void;
};

export function SingleGradeList({
  specId,
  grade,
  highlighted,
  competences,
  competenceTitles,
  editState,
  sortedLevels,
  activeSessionsMap,
  onOpenActiveSession,
  saving,
  onLevelChange,
  cellIsDirty,
  onShowIndicators,
  onRemoveCompetence,
  onGradeUpdated,
  onGradeRemoved,
}: Props) {
  const t = useTranslations("company");
  const tc = useTranslations("common");
  const tRef = useTranslations("reference");
  // HRP-479: localized display name for the grade; toasts and the header
  // share it so the wording matches the dictionary everywhere.
  const gradeLabel = grade.grade_title
    ? dictionaryItemLabel(tRef, {
        type: "grade",
        title: grade.grade_title,
        i18n_key: grade.grade_i18n_key,
      })
    : null;
  const [editingSalary, setEditingSalary] = useState(false);
  const [salaryMin, setSalaryMin] = useState<string>(
    grade.salary_min != null ? String(grade.salary_min) : "",
  );
  const [salaryMax, setSalaryMax] = useState<string>(
    grade.salary_max != null ? String(grade.salary_max) : "",
  );
  const [savingSalary, setSavingSalary] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [confirmRemoveOpen, setConfirmRemoveOpen] = useState(false);

  const hasSalary = grade.salary_min != null || grade.salary_max != null;
  const salaryLabel = hasSalary
    ? `${grade.salary_min ?? "?"} – ${grade.salary_max ?? "?"} ${grade.salary_currency}`
    : t("addSalary");

  async function handleSaveSalary() {
    const min = salaryMin.trim() === "" ? null : Number(salaryMin);
    const max = salaryMax.trim() === "" ? null : Number(salaryMax);
    if (min != null && Number.isNaN(min)) {
      toast.error(t("errorSalaryMinNumber"));
      return;
    }
    if (max != null && Number.isNaN(max)) {
      toast.error(t("errorSalaryMaxNumber"));
      return;
    }
    if (min != null && min < 0) {
      toast.error(t("errorSalaryMinNegative"));
      return;
    }
    if (max != null && max < 0) {
      toast.error(t("errorSalaryMaxNegative"));
      return;
    }
    if (min != null && max != null && min > max) {
      toast.error(t("errorSalaryMinGreaterThanMax"));
      return;
    }
    setSavingSalary(true);
    try {
      const next = await specializationsApi.patchGrade(specId, grade.grade_id, {
        salary_min: min,
        salary_max: max,
      });
      onGradeUpdated(next);
      setEditingSalary(false);
      toast.success(t("toastSalaryUpdated"));
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("toastSalarySaveFailed"),
      );
    } finally {
      setSavingSalary(false);
    }
  }

  async function handleConfirmedRemoveGrade() {
    setRemoving(true);
    try {
      await specializationsApi.deleteGrade(specId, grade.grade_id);
      onGradeRemoved(grade.grade_id);
      toast.success(
        t("toastGradeRemoved", { grade: gradeLabel ?? t("gradeFallback") }),
      );
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("toastGradeRemoveFailed"),
      );
    } finally {
      setRemoving(false);
    }
  }

  return (
    <div
      data-testid="matrix-single-grade-list"
      data-single-grade="true"
      data-grade-id={grade.grade_id}
      className={cn(
        "rounded-lg border bg-card transition-colors duration-150",
        highlighted && "ring-2 ring-primary/30",
      )}
    >
      {/* Section header — replaces the "lone column header" of the old
          table. Title + salary pill + remove control sit on one row so
          the operator can tell at a glance which grade this list
          belongs to without re-reading column labels. */}
      <div
        data-testid={`matrix-single-grade-header-${grade.grade_id}`}
        className="flex flex-wrap items-center justify-between gap-2 border-b bg-muted/30 px-4 py-3"
      >
        <div className="flex flex-wrap items-center gap-3">
          <h3 className="text-base font-semibold tracking-tight">
            {gradeLabel ?? "—"}
          </h3>
          {editingSalary ? (
            <div
              data-testid={`matrix-single-grade-salary-edit-${grade.grade_id}`}
              className="flex flex-wrap items-center gap-1"
            >
              <Input
                data-testid={`matrix-single-grade-salary-min-${grade.grade_id}`}
                type="number"
                min={0}
                value={salaryMin}
                onChange={(e) => setSalaryMin(e.target.value)}
                placeholder={t("salaryMinPlaceholder")}
                className="h-7 w-24 px-1.5 text-xs"
              />
              <Input
                data-testid={`matrix-single-grade-salary-max-${grade.grade_id}`}
                type="number"
                min={0}
                value={salaryMax}
                onChange={(e) => setSalaryMax(e.target.value)}
                placeholder={t("salaryMaxPlaceholder")}
                className="h-7 w-24 px-1.5 text-xs"
              />
              <Button
                data-testid={`matrix-single-grade-salary-save-${grade.grade_id}`}
                size="sm"
                onClick={handleSaveSalary}
                disabled={savingSalary}
                className="h-7 px-2 text-xs"
              >
                {savingSalary ? "…" : t("save")}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setSalaryMin(
                    grade.salary_min != null ? String(grade.salary_min) : "",
                  );
                  setSalaryMax(
                    grade.salary_max != null ? String(grade.salary_max) : "",
                  );
                  setEditingSalary(false);
                }}
                disabled={savingSalary}
                className="h-7 px-2 text-xs"
              >
                {tc("cancel")}
              </Button>
            </div>
          ) : (
            <button
              type="button"
              data-testid={`matrix-single-grade-salary-${grade.grade_id}`}
              onClick={() => setEditingSalary(true)}
              className={cn(
                "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                hasSalary
                  ? "border-border bg-background text-foreground hover:border-primary/40"
                  : "border-dashed border-muted-foreground/40 text-muted-foreground hover:border-primary hover:text-primary",
              )}
            >
              <CircleDollarSign className="h-3 w-3 shrink-0" />
              <span className="truncate">{salaryLabel}</span>
            </button>
          )}
        </div>
        <button
          type="button"
          data-testid={`matrix-single-grade-remove-${grade.grade_id}`}
          onClick={() => setConfirmRemoveOpen(true)}
          disabled={removing}
          aria-label={t("removeGrade", {
            grade: gradeLabel ?? t("gradeFallback"),
          })}
          title={t("removeGradeTitle")}
          className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition hover:bg-destructive/10 hover:text-destructive focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* Row list — divide-y between rows so the eye reads a clean
          vertical column; hover lights up the whole row to signal
          interactivity. Delete buttons share a fixed width so the
          right-side axis stays pixel-perfect across rows. */}
      <ul
        data-testid="matrix-single-grade-rows"
        className="divide-y"
      >
        {competences.map((comp) => {
          const levelId = editState[comp.id] ?? null;
          const isDirty = cellIsDirty(comp.id);
          const hueClass = levelHueClass(levelId, sortedLevels);
          const compSessions =
            activeSessionsMap?.get(
              activeAiSessionsKey("competence_indicators", comp.id),
            ) ?? [];
          const compIsLitUp = compSessions.length > 0;
          const coverageWarning = coverageGapMessage(t, comp);

          return (
            <li
              key={comp.id}
              data-testid={`matrix-row-${comp.id}`}
              className={cn(
                "flex items-center gap-3 px-4 py-2.5 transition-colors hover:bg-muted/30",
                compIsLitUp && "bg-primary/5",
              )}
            >
              {/* Left: competence link + AI session badge + coverage
                  warning. Min-w-0 + truncate so long titles do not
                  push the selector off the row. */}
              <div className="flex min-w-0 flex-1 items-center gap-2">
                <Link
                  href={`/competences/${comp.id}?from=matrix&specialization_id=${specId}`}
                  data-testid={`matrix-row-${comp.id}-competence-link`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex min-w-0 items-center gap-1 text-sm font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded"
                >
                  <span className="truncate">
                    {competenceTitles.get(comp.id) ?? comp.title}
                  </span>
                  <ExternalLink className="h-3 w-3 flex-shrink-0 opacity-60" />
                </Link>
                {compIsLitUp && onOpenActiveSession && (
                  <ActiveAiSessionBadge
                    sessions={compSessions}
                    onOpen={onOpenActiveSession}
                    testIdSuffix={`matrix-comp-${comp.id}`}
                  />
                )}
                {coverageWarning && (
                  <Link
                    href={`/competences/${comp.id}?from=matrix&specialization_id=${specId}`}
                    data-testid={`matrix-row-${comp.id}-coverage-warning`}
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label={coverageWarning}
                    title={coverageWarning}
                    className="text-amber-600 hover:text-amber-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded"
                  >
                    <AlertCircle className="h-4 w-4" />
                  </Link>
                )}
              </div>

              {/* Right: fixed-width colored level chip (180px) + 32×32
                  delete button. Width pinned so every selector + delete
                  column lines up across rows regardless of competence
                  title length. */}
              <div
                data-testid={`matrix-row-${comp.id}-level-chip`}
                data-level-hue={levelId ?? "none"}
                className={cn(
                  "inline-flex w-[180px] items-center rounded-md border px-1 py-0.5 transition",
                  hueClass,
                  isDirty &&
                    "underline decoration-orange-500 decoration-2 underline-offset-4",
                )}
              >
                <MatrixCell
                  competenceId={comp.id}
                  gradeId={grade.grade_id}
                  levelId={levelId}
                  skillLevels={sortedLevels}
                  isDirty={false}
                  unstyled
                  onChange={(next) => onLevelChange(comp.id, next)}
                  onShowIndicators={() => onShowIndicators(comp.id, levelId)}
                  disabled={saving}
                />
              </div>
              <button
                type="button"
                data-testid={`matrix-row-${comp.id}-btn-remove`}
                aria-label={t("removeCompetenceFromMatrix", {
                  competence: comp.title,
                })}
                title={t("removeCompetenceFromMatrixTitle")}
                className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition hover:bg-destructive/10 hover:text-destructive focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
                onClick={() => onRemoveCompetence(comp.id)}
                disabled={saving}
              >
                <X className="h-4 w-4" />
              </button>
            </li>
          );
        })}
      </ul>

      <ConfirmDialog
        open={confirmRemoveOpen}
        onOpenChange={setConfirmRemoveOpen}
        title={t("removeGradeConfirmTitle", {
          grade: gradeLabel ?? t("gradeFallback"),
        })}
        description={t("removeGradeConfirmBody")}
        confirmLabel={removing ? t("removing") : t("removeGradeTitle")}
        destructive
        onConfirm={handleConfirmedRemoveGrade}
        testId={`matrix-single-grade-remove-confirm-${grade.grade_id}`}
      />
    </div>
  );
}
