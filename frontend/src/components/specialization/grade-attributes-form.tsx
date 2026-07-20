"use client";

import { useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { SpecializationGrade } from "@/lib/api/specializations";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

type Props = {
  grade: SpecializationGrade;
  specId?: string;
  onSaved?: (next: SpecializationGrade) => void;
};

export function GradeAttributesForm({ grade, specId, onSaved }: Props) {
  const [description, setDescription] = useState(grade.description ?? "");
  const [requirements, setRequirements] = useState(grade.requirements ?? "");
  const [salaryMin, setSalaryMin] = useState(
    grade.salary_min == null ? "" : String(grade.salary_min),
  );
  const [salaryMax, setSalaryMax] = useState(
    grade.salary_max == null ? "" : String(grade.salary_max),
  );
  const [salaryCurrency, setSalaryCurrency] = useState(
    grade.salary_currency || "RUB",
  );
  const [saving, setSaving] = useState(false);

  async function handleSave() {
    setSaving(true);
    try {
      const payload: Record<string, unknown> = {
        description: description || null,
        requirements: requirements || null,
        salary_min: salaryMin === "" ? null : Number(salaryMin),
        salary_max: salaryMax === "" ? null : Number(salaryMax),
        salary_currency: salaryCurrency.toUpperCase(),
      };
      const next = await api.put<SpecializationGrade>(
        `/grade-system/chains/${grade.id}`,
        payload,
      );
      toast.success("Saved");
      onSaved?.(next);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      data-testid={`specialization-grade-form-${grade.id}`}
      className="space-y-4 rounded-lg border p-4"
    >
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold">
          {grade.grade_title}
          {/* HRP-288: chain still references a grade that has been
              deactivated — surface the Inactive chip so the reviewer
              sees the state at a glance. */}
          {!grade.grade_is_active && (
            <span
              data-testid={`specialization-grade-form-${grade.id}-inactive`}
              className="ml-2 inline-flex items-center rounded-full bg-muted px-2 py-0.5 align-middle text-xs font-medium text-muted-foreground"
            >
              Inactive
            </span>
          )}
        </h3>
        <span className="text-xs text-muted-foreground">
          {grade.matrix_status === "configured"
            ? `${grade.competence_count} competences in matrix`
            : "Matrix not configured"}
        </span>
      </div>

      <div className="space-y-2">
        <Label htmlFor={`desc-${grade.id}`}>Description</Label>
        <Textarea
          id={`desc-${grade.id}`}
          data-testid={`specialization-grade-form-${grade.id}-description`}
          rows={3}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="What this grade looks like at this specialization"
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor={`req-${grade.id}`}>Requirements</Label>
        <Textarea
          id={`req-${grade.id}`}
          data-testid={`specialization-grade-form-${grade.id}-requirements`}
          rows={4}
          value={requirements}
          onChange={(e) => setRequirements(e.target.value)}
          placeholder="Skills, experience, mandatory tooling, certifications..."
        />
      </div>

      <div className="grid grid-cols-3 gap-3">
        <div className="space-y-2">
          <Label htmlFor={`smin-${grade.id}`}>Salary, min</Label>
          <Input
            id={`smin-${grade.id}`}
            data-testid={`specialization-grade-form-${grade.id}-salary-min`}
            type="number"
            min={0}
            value={salaryMin}
            onChange={(e) => setSalaryMin(e.target.value)}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor={`smax-${grade.id}`}>Salary, max</Label>
          <Input
            id={`smax-${grade.id}`}
            data-testid={`specialization-grade-form-${grade.id}-salary-max`}
            type="number"
            min={0}
            value={salaryMax}
            onChange={(e) => setSalaryMax(e.target.value)}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor={`scur-${grade.id}`}>Currency</Label>
          <Input
            id={`scur-${grade.id}`}
            data-testid={`specialization-grade-form-${grade.id}-salary-currency`}
            maxLength={3}
            value={salaryCurrency}
            onChange={(e) =>
              setSalaryCurrency(e.target.value.toUpperCase().slice(0, 3))
            }
          />
        </div>
      </div>

      <div className="flex justify-between">
        {specId ? (
          <Link
            href={`/company/specializations/${specId}/matrix?grade_id=${grade.grade_id}`}
            data-testid={`specialization-grade-form-${grade.id}-link-matrix`}
            className="text-sm text-primary hover:underline"
          >
            Edit matrix →
          </Link>
        ) : (
          <span />
        )}
        <Button
          data-testid={`specialization-grade-form-${grade.id}-btn-save`}
          size="sm"
          onClick={handleSave}
          disabled={saving}
        >
          {saving ? "Saving..." : "Save"}
        </Button>
      </div>
    </div>
  );
}
