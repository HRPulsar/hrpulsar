"use client";

import { useState } from "react";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { CircleDollarSign, GripVertical, X } from "lucide-react";
import { toast } from "sonner";

import {
  specializationsApi,
  type SpecializationGrade,
} from "@/lib/api/specializations";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";

type Props = {
  specId: string;
  grade: SpecializationGrade;
  highlighted: boolean;
  onGradeUpdated: (next: SpecializationGrade) => void;
  onGradeRemoved: (gradeId: string) => void;
};

/** Header cell of one matrix column: drag handle, grade title, salary
 * pill and a destructive remove icon. The column itself becomes a sortable
 * item via `useSortable`; horizontal reorder is wired by the parent's DndContext.
 */
export function GradeHeaderCell({
  specId,
  grade,
  highlighted,
  onGradeUpdated,
  onGradeRemoved,
}: Props) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: grade.grade_id });

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

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.6 : 1,
  };

  async function handleSaveSalary() {
    const min = salaryMin.trim() === "" ? null : Number(salaryMin);
    const max = salaryMax.trim() === "" ? null : Number(salaryMax);
    if (min != null && Number.isNaN(min)) {
      toast.error("salary_min must be a number");
      return;
    }
    if (max != null && Number.isNaN(max)) {
      toast.error("salary_max must be a number");
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
      toast.success("Salary updated");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save salary");
    } finally {
      setSavingSalary(false);
    }
  }

  async function handleConfirmedRemove() {
    setRemoving(true);
    try {
      await specializationsApi.deleteGrade(specId, grade.grade_id);
      onGradeRemoved(grade.grade_id);
      toast.success(`Removed ${grade.grade_title ?? "grade"}`);
    } catch (err) {
      // ConfirmDialog awaits this callback then closes itself; let the
      // toast carry the failure and swallow the error so the dialog
      // shutdown path still runs (otherwise `removing` stays true).
      toast.error(err instanceof Error ? err.message : "Failed to remove grade");
    } finally {
      setRemoving(false);
    }
  }

  const hasSalary = grade.salary_min != null || grade.salary_max != null;
  const salaryLabel = hasSalary
    ? `${grade.salary_min ?? "?"} – ${grade.salary_max ?? "?"} ${grade.salary_currency}`
    : "Add salary";

  return (
    <th
      ref={setNodeRef}
      style={style}
      data-testid={`matrix-th-grade-${grade.grade_id}`}
      data-dragging={isDragging ? "true" : undefined}
      className={
        "min-w-[12rem] border-b border-r last:border-r-0 px-3 py-2 align-top font-medium" +
        (highlighted ? " bg-primary/10" : " bg-muted/40")
      }
    >
      <div className="flex items-start gap-1.5">
        <button
          type="button"
          {...attributes}
          {...listeners}
          data-testid={`matrix-grade-drag-${grade.grade_id}`}
          aria-label={`Reorder ${grade.grade_title ?? "grade"}`}
          className="mt-0.5 cursor-grab touch-none rounded text-muted-foreground hover:bg-muted hover:text-foreground active:cursor-grabbing"
        >
          <GripVertical className="h-4 w-4" />
        </button>
        <div className="min-w-0 flex-1 space-y-1.5">
          <div
            className="truncate text-sm font-semibold tracking-tight"
            title={grade.grade_title ?? undefined}
          >
            {grade.grade_title ?? "—"}
            {/* HRP-288: surface the dictionary deactivation in the
                matrix header too, so the matrix mirrors the spec page. */}
            {grade.grade_is_active === false && (
              <span
                data-testid={`matrix-grade-inactive-${grade.grade_id}`}
                className="ml-1.5 inline-flex items-center rounded-full bg-muted px-1.5 py-0.5 align-middle text-[10px] font-medium text-muted-foreground"
              >
                Inactive
              </span>
            )}
          </div>
          {editingSalary ? (
            <div
              data-testid={`matrix-grade-salary-edit-${grade.grade_id}`}
              className="space-y-1.5"
            >
              <div className="flex gap-1">
                <Input
                  data-testid={`matrix-grade-salary-min-${grade.grade_id}`}
                  type="number"
                  min={0}
                  value={salaryMin}
                  onChange={(e) => setSalaryMin(e.target.value)}
                  placeholder="min"
                  className="h-7 px-1.5 text-xs"
                />
                <Input
                  data-testid={`matrix-grade-salary-max-${grade.grade_id}`}
                  type="number"
                  min={0}
                  value={salaryMax}
                  onChange={(e) => setSalaryMax(e.target.value)}
                  placeholder="max"
                  className="h-7 px-1.5 text-xs"
                />
              </div>
              <div className="flex gap-1">
                <Button
                  data-testid={`matrix-grade-salary-save-${grade.grade_id}`}
                  size="sm"
                  onClick={handleSaveSalary}
                  disabled={savingSalary}
                  className="h-6 px-2 text-[0.7rem]"
                >
                  {savingSalary ? "…" : "Save"}
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
                  className="h-6 px-2 text-[0.7rem]"
                >
                  Cancel
                </Button>
              </div>
            </div>
          ) : (
            <button
              type="button"
              data-testid={`matrix-grade-salary-${grade.grade_id}`}
              onClick={() => setEditingSalary(true)}
              // Salary and Remove used to render as bare text runs on
              // adjacent lines, smashing into one "salaryRemove" token at
              // narrow widths. The bordered pill + leading icon give the
              // operator a clear hit target boundary.
              className={
                "inline-flex max-w-full items-center gap-1 rounded-md border px-1.5 py-0.5 text-[0.7rem] transition " +
                (hasSalary
                  ? "border-border bg-background text-foreground hover:border-primary/40"
                  : "border-dashed border-muted-foreground/40 text-muted-foreground hover:border-primary hover:text-primary")
              }
            >
              <CircleDollarSign className="h-3 w-3 shrink-0" />
              <span className="truncate">{salaryLabel}</span>
            </button>
          )}
        </div>
        {/* Destructive icon button stays outside the title/salary stack so
            the boundary between "edit this column" and "drop this column"
            is visually unambiguous; confirm flow uses ConfirmDialog so the
            operator can read the consequences before clicking. */}
        <button
          type="button"
          data-testid={`matrix-grade-remove-${grade.grade_id}`}
          onClick={() => setConfirmRemoveOpen(true)}
          disabled={removing}
          aria-label={`Remove ${grade.grade_title ?? "grade"}`}
          title="Remove grade"
          className="mt-0.5 rounded p-0.5 text-muted-foreground transition hover:bg-destructive/10 hover:text-destructive disabled:opacity-50"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      <ConfirmDialog
        open={confirmRemoveOpen}
        onOpenChange={setConfirmRemoveOpen}
        title={`Remove ${grade.grade_title ?? "grade"}?`}
        description={
          "All matrix levels saved against this grade will be lost. " +
          "This cannot be undone."
        }
        confirmLabel={removing ? "Removing…" : "Remove grade"}
        destructive
        onConfirm={handleConfirmedRemove}
        testId={`matrix-grade-remove-confirm-${grade.grade_id}`}
      />
    </th>
  );
}
