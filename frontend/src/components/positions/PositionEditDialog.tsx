"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { AlertTriangle, Check, Plus, X } from "lucide-react";
import { toast } from "sonner";

import { api } from "@/lib/api";
import {
  EMPTY_FORM_ERROR,
  parseFormError,
  type FormErrorState,
} from "@/lib/form-errors";
import { FieldError, FormErrorBanner } from "@/components/ui/form-error";
import { dictionaryItemLabel } from "@/lib/reference-labels";
import type {
  DictionaryItem,
  Division,
  Position,
  PositionLifecycleStatus,
} from "@/lib/types";
import { flattenTree } from "@/lib/utils";
import { POSITION_LIFECYCLE_LABEL_KEY } from "@/components/positions/PositionStatusBadge";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

const LIFECYCLE_OPTIONS: PositionLifecycleStatus[] = [
  "active",
  "on_hold",
  "frozen",
  "closed",
];

// HRP-57 §6.2: spec caps the override at 600 chars so it stays a sticky note,
// not a second source of truth.
const DESCRIPTION_LIMIT = 600;

interface SpecializationGrade {
  id: string;
  grade_id: string;
  grade_title: string;
  // HRP-479: origin grades localize via reference.dictionary.grade.*.
  grade_i18n_key?: string | null;
  matrix_status: "empty" | "configured";
  competence_count: number;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string;
}

interface FormState {
  title: string;
  description: string;
  specialization_id: string;
  grade_id: string;
  division_id: string;
  headcount: string;
  lifecycle_status: PositionLifecycleStatus;
}

const EMPTY_FORM: FormState = {
  title: "",
  description: "",
  specialization_id: "",
  grade_id: "",
  division_id: "",
  headcount: "",
  lifecycle_status: "active",
};

interface PositionEditDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** When provided the dialog runs in edit mode (PUT). Omit for create (POST). */
  position?: Position | null;
  onSaved: () => void;
}

function toFormState(pos: Position): FormState {
  return {
    title: pos.title,
    description: pos.description ?? "",
    specialization_id: pos.specialization_id ?? "",
    grade_id: pos.grade_id ?? "",
    division_id: pos.division_id ?? "",
    headcount: pos.headcount != null ? String(pos.headcount) : "",
    lifecycle_status: pos.lifecycle_status,
  };
}

function formatSalary(
  grade: SpecializationGrade,
  t: (key: string, values?: Record<string, string | number>) => string,
  locale: string,
): string | null {
  const { salary_min, salary_max, salary_currency } = grade;
  const fmt = (n: number) => n.toLocaleString(locale);
  if (salary_min != null && salary_max != null)
    return `${fmt(salary_min)} – ${fmt(salary_max)} ${salary_currency}`;
  if (salary_min != null)
    return t("salaryFrom", {
      amount: fmt(salary_min),
      currency: salary_currency,
    });
  if (salary_max != null)
    return t("salaryUpTo", {
      amount: fmt(salary_max),
      currency: salary_currency,
    });
  return null;
}

/**
 * Edit + create dialog for a Position. Fetches its own reference data on
 * first open. Implements HRP-57 §§ 6.4 / 6.5 (Spec → Grade cascade — Grade
 * options come from `/specializations/{id}/grades`, picking a new Spec
 * resets the Grade), §6.6 (matrix-status banner under the cascade), §6.7
 * (employee-protection warning when the operator changes the profile of an
 * existing position with assigned employees) and §5.1 (create flow: title
 * auto-defaults to `<Spec> <Grade>` while the user has not customized it).
 */
export function PositionEditDialog({
  open,
  onOpenChange,
  position,
  onSaved,
}: PositionEditDialogProps) {
  const t = useTranslations("company");
  const tc = useTranslations("common");
  const tRef = useTranslations("reference");
  const locale = useLocale();
  const isCreate = !position;
  const [form, setForm] = useState<FormState>(() =>
    position ? toFormState(position) : EMPTY_FORM,
  );
  // Tracks whether Title is currently the auto-filled "<Spec> <Grade>" value
  // or the operator has typed something. Only flips back to "auto" when the
  // operator explicitly clears the field. Edit-mode opens with `false` so the
  // existing title is never overwritten by Spec/Grade picks.
  const titleAutoFilled = useRef<boolean>(isCreate);
  const [saving, setSaving] = useState(false);
  const [specializations, setSpecializations] = useState<DictionaryItem[]>([]);
  const [divisions, setDivisions] = useState<Division[]>([]);
  const [gradesForSpec, setGradesForSpec] = useState<SpecializationGrade[]>([]);
  const [gradesLoading, setGradesLoading] = useState(false);
  const [refDataLoaded, setRefDataLoaded] = useState(false);
  // HRP-54: inline-create panels for Specialization / Grade. Operators who hit
  // the form without seeing the value they need shouldn't have to bounce to
  // the dictionaries page — same idea as `position-combobox`.
  const [specAddOpen, setSpecAddOpen] = useState(false);
  const [specAddTitle, setSpecAddTitle] = useState("");
  const [specAddBusy, setSpecAddBusy] = useState(false);
  const [gradeAddOpen, setGradeAddOpen] = useState(false);
  const [gradeAddTitle, setGradeAddTitle] = useState("");
  const [gradeAddBusy, setGradeAddBusy] = useState(false);

  const [saveError, setSaveError] = useState<FormErrorState>(EMPTY_FORM_ERROR);

  // Resync form when the dialog re-opens for a different position (or when
  // it switches between create and edit mode for the same parent surface).
  useEffect(() => {
    if (open) {
      setForm(position ? toFormState(position) : EMPTY_FORM);
      titleAutoFilled.current = !position;
      setSaveError(EMPTY_FORM_ERROR);
    }
  }, [open, position]);

  // Load specializations + divisions once on first open.
  useEffect(() => {
    if (!open || refDataLoaded) return;
    let cancelled = false;
    void (async () => {
      const [specRes, divRes] = await Promise.allSettled([
        api.get<DictionaryItem[]>("/dictionaries/specialization"),
        api.get<Division[]>("/divisions"),
      ]);
      if (cancelled) return;
      if (specRes.status === "fulfilled") setSpecializations(specRes.value);
      if (divRes.status === "fulfilled") setDivisions(divRes.value);
      setRefDataLoaded(true);
    })();
    return () => {
      cancelled = true;
    };
  }, [open, refDataLoaded]);

  // §6.5: Grade options are not the global grade dictionary — only those
  // attached to the chosen Specialization. Fetched on every spec change.
  // Latest-spec ref defeats the A→B→A race: a stale response only commits
  // when its captured spec id still matches the one the user is on now.
  const latestSpecRef = useRef<string>("");
  useEffect(() => {
    latestSpecRef.current = form.specialization_id;
    if (!open || !form.specialization_id) {
      setGradesForSpec([]);
      return;
    }
    const requestedSpec = form.specialization_id;
    setGradesForSpec([]);
    setGradesLoading(true);
    void (async () => {
      try {
        const data = await api.get<SpecializationGrade[]>(
          `/specializations/${requestedSpec}/grades`,
        );
        if (latestSpecRef.current !== requestedSpec) return;
        setGradesForSpec(data);
      } catch (err) {
        if (latestSpecRef.current !== requestedSpec) return;
        toast.error(
          err instanceof Error ? err.message : t("toastGradesLoadFailed"),
        );
        setGradesForSpec([]);
      } finally {
        if (latestSpecRef.current === requestedSpec) {
          setGradesLoading(false);
        }
      }
    })();
  }, [open, form.specialization_id, t]);

  const flatDivisions = useMemo(() => flattenTree(divisions), [divisions]);

  const selectedSpec = form.specialization_id
    ? specializations.find((s) => s.id === form.specialization_id) ?? null
    : null;
  const selectedGradeRow = form.grade_id
    ? gradesForSpec.find((g) => g.grade_id === form.grade_id) ?? null
    : null;

  // §5.1: Title default = "<Spec> <Grade>". Apply only while the field is
  // still in the auto-filled state — manual edits stick.
  useEffect(() => {
    if (!isCreate || !titleAutoFilled.current) return;
    if (!selectedSpec || !selectedGradeRow) return;
    const next = `${selectedSpec.title} ${selectedGradeRow.grade_title}`;
    setForm((prev) => (prev.title === next ? prev : { ...prev, title: next }));
  }, [isCreate, selectedSpec, selectedGradeRow]);

  // §6.4: changing Spec wipes the previously-selected Grade.
  const setSpecialization = useCallback((next: string) => {
    setForm((prev) =>
      prev.specialization_id === next
        ? prev
        : {
            ...prev,
            specialization_id: next,
            grade_id: "",
          },
    );
  }, []);

  async function createSpecialization() {
    const title = specAddTitle.trim();
    if (!title) {
      toast.error(t("errorEnterSpecializationName"));
      return;
    }
    setSpecAddBusy(true);
    try {
      const created = await api.post<DictionaryItem>(
        "/dictionaries/specialization",
        { title },
      );
      setSpecializations((prev) => [...prev, created]);
      setSpecialization(created.id);
      setSpecAddOpen(false);
      setSpecAddTitle("");
      toast.success(t("toastSpecializationAdded"));
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("toastSpecializationAddFailed"),
      );
    } finally {
      setSpecAddBusy(false);
    }
  }

  async function createGrade() {
    const title = gradeAddTitle.trim();
    if (!title) {
      toast.error(t("errorEnterGradeName"));
      return;
    }
    if (!form.specialization_id) {
      toast.error(t("pickSpecializationFirst"));
      return;
    }
    setGradeAddBusy(true);
    // Two-step flow: create grade in dictionary, then chain it to the
    // current specialization. If the chain POST fails, roll the dictionary
    // entry back so we don't leave the operator with an orphan grade that
    // shows up nowhere except as a duplicate next time they retry.
    try {
      const gradeItem = await api.post<DictionaryItem>(
        "/dictionaries/grade",
        { title },
      );
      try {
        await api.post("/grade-system/chains", {
          specialization_id: form.specialization_id,
          grade_id: gradeItem.id,
        });
      } catch (chainErr) {
        await api
          .delete(`/dictionaries/items/${gradeItem.id}`)
          .catch(() => undefined);
        throw chainErr;
      }
      const updated = await api.get<SpecializationGrade[]>(
        `/specializations/${form.specialization_id}/grades`,
      );
      setGradesForSpec(updated);
      setForm((prev) => ({ ...prev, grade_id: gradeItem.id }));
      setGradeAddOpen(false);
      setGradeAddTitle("");
      toast.success(t("toastGradeAdded"));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toastGradeAddFailed"));
    } finally {
      setGradeAddBusy(false);
    }
  }

  function setTitle(next: string) {
    setForm((prev) => ({ ...prev, title: next }));
    // Empty input re-arms the auto-fill so the operator can iterate Spec/Grade
    // picks and let the title follow.
    titleAutoFilled.current = next.trim() === "";
  }

  // §6.7 trigger: edit-mode only — profile (Spec or Grade) is being changed
  // AND the position already has people on it.
  const profileChanged =
    !!position &&
    ((form.specialization_id || null) !== (position.specialization_id ?? null) ||
      (form.grade_id || null) !== (position.grade_id ?? null));
  const showEmployeeImpactWarning =
    !!position && profileChanged && position.employee_count > 0;

  const matrixDeepLink =
    form.specialization_id && form.grade_id
      ? `/company/specializations/${form.specialization_id}/matrix?grade_id=${form.grade_id}`
      : null;

  const overLimit = form.description.length > DESCRIPTION_LIMIT;
  const salaryPreview = selectedGradeRow
    ? formatSalary(selectedGradeRow, t, locale)
    : null;

  async function handleSave() {
    if (!form.title.trim()) return;
    if (overLimit) {
      toast.error(t("errorDescriptionTooLong", { limit: DESCRIPTION_LIMIT }));
      return;
    }
    setSaving(true);
    setSaveError(EMPTY_FORM_ERROR);
    try {
      const payload = {
        title: form.title.trim(),
        description: form.description.trim() || null,
        specialization_id: form.specialization_id || null,
        grade_id: form.grade_id || null,
        division_id: form.division_id || null,
        headcount: form.headcount ? Number(form.headcount) : null,
        lifecycle_status: form.lifecycle_status,
      };
      if (position) {
        await api.put(`/positions/${position.id}`, payload);
        toast.success(t("toastPositionUpdated"));
      } else {
        await api.post("/positions", payload);
        toast.success(t("toastPositionCreated"));
      }
      onOpenChange(false);
      onSaved();
    } catch (err) {
      setSaveError(parseFormError(err, ["title", "headcount"]));
    } finally {
      setSaving(false);
    }
  }

  const gradeDisabled = !form.specialization_id;
  const dialogTitle = isCreate ? t("newPosition") : t("editPosition");
  const saveLabel = isCreate ? t("create") : t("save");

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        data-testid="position-edit-dialog"
        data-mode={isCreate ? "create" : "edit"}
        className="max-h-[85vh] overflow-y-auto"
      >
        <DialogHeader>
          <DialogTitle>{dialogTitle}</DialogTitle>
        </DialogHeader>

        <FormErrorBanner
          message={saveError.message}
          testId="position-edit-error"
        />

        <div className="space-y-4">
          <div className="space-y-2">
            <Label>{t("specialization")}</Label>
            <Select
              value={form.specialization_id}
              onValueChange={setSpecialization}
            >
              <SelectTrigger
                className="w-full"
                data-testid="position-edit-select-specialization"
              >
                <SelectValue placeholder={t("pickSpecialization")}>
                  {selectedSpec ? dictionaryItemLabel(tRef, selectedSpec) : undefined}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="">{t("none")}</SelectItem>
                {specializations.map((s) => (
                  <SelectItem key={s.id} value={s.id}>
                    {dictionaryItemLabel(tRef, s)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {specAddOpen ? (
              <div className="flex items-center gap-1">
                <Input
                  autoFocus
                  value={specAddTitle}
                  onChange={(e) => setSpecAddTitle(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void createSpecialization();
                    if (e.key === "Escape") {
                      setSpecAddOpen(false);
                      setSpecAddTitle("");
                    }
                  }}
                  placeholder={t("newSpecializationPlaceholder")}
                  disabled={specAddBusy}
                  data-testid="position-edit-input-new-specialization"
                />
                <Button
                  type="button"
                  size="icon-sm"
                  onClick={createSpecialization}
                  disabled={specAddBusy || !specAddTitle.trim()}
                  data-testid="position-edit-btn-save-new-specialization"
                  aria-label={t("saveSpecialization")}
                >
                  <Check className="h-4 w-4" />
                </Button>
                <Button
                  type="button"
                  size="icon-sm"
                  variant="ghost"
                  onClick={() => {
                    setSpecAddOpen(false);
                    setSpecAddTitle("");
                  }}
                  disabled={specAddBusy}
                  aria-label={tc("cancel")}
                >
                  <X className="h-4 w-4" />
                </Button>
              </div>
            ) : (
              <Button
                type="button"
                size="sm"
                variant="ghost"
                className="-ml-2 h-7 text-xs"
                onClick={() => setSpecAddOpen(true)}
                data-testid="position-edit-btn-add-specialization"
              >
                <Plus className="mr-1 h-3.5 w-3.5" />
                {t("addNewSpecialization")}
              </Button>
            )}
          </div>

          <div className="space-y-2">
            <Label>{t("grade")}</Label>
            <Select
              value={form.grade_id}
              onValueChange={(val) =>
                setForm((prev) => ({ ...prev, grade_id: val }))
              }
              disabled={gradeDisabled || gradesLoading}
            >
              <SelectTrigger
                className="w-full"
                data-testid="position-edit-select-grade"
              >
                <SelectValue
                  placeholder={
                    gradeDisabled
                      ? t("pickSpecializationFirst")
                      : gradesLoading
                        ? t("loadingEllipsis")
                        : gradesForSpec.length === 0
                          ? t("noGradesConfigured")
                          : t("pickGradePlaceholder")
                  }
                >
                  {selectedGradeRow
                    ? dictionaryItemLabel(tRef, {
                        type: "grade",
                        title: selectedGradeRow.grade_title,
                        i18n_key: selectedGradeRow.grade_i18n_key,
                      })
                    : undefined}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="">{t("none")}</SelectItem>
                {gradesForSpec.map((g) => (
                  <SelectItem key={g.grade_id} value={g.grade_id}>
                    {dictionaryItemLabel(tRef, {
                      type: "grade",
                      title: g.grade_title,
                      i18n_key: g.grade_i18n_key,
                    })}
                    {g.matrix_status === "empty" ? t("matrixEmptySuffix") : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {form.specialization_id &&
            !gradesLoading &&
            gradesForSpec.length === 0 ? (
              <p
                data-testid="position-edit-grades-empty"
                className="text-xs text-muted-foreground"
              >
                {t.rich("specHasNoGrades", {
                  link: (chunks) => (
                    <Link
                      href={`/company/specializations/${form.specialization_id}`}
                      className="underline underline-offset-2"
                    >
                      {chunks}
                    </Link>
                  ),
                })}
              </p>
            ) : null}
            {gradeAddOpen ? (
              <div className="flex items-center gap-1">
                <Input
                  autoFocus
                  value={gradeAddTitle}
                  onChange={(e) => setGradeAddTitle(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void createGrade();
                    if (e.key === "Escape") {
                      setGradeAddOpen(false);
                      setGradeAddTitle("");
                    }
                  }}
                  placeholder={t("newGradePlaceholder")}
                  disabled={gradeAddBusy}
                  data-testid="position-edit-input-new-grade"
                />
                <Button
                  type="button"
                  size="icon-sm"
                  onClick={createGrade}
                  disabled={gradeAddBusy || !gradeAddTitle.trim()}
                  data-testid="position-edit-btn-save-new-grade"
                  aria-label={t("saveGrade")}
                >
                  <Check className="h-4 w-4" />
                </Button>
                <Button
                  type="button"
                  size="icon-sm"
                  variant="ghost"
                  onClick={() => {
                    setGradeAddOpen(false);
                    setGradeAddTitle("");
                  }}
                  disabled={gradeAddBusy}
                  aria-label={tc("cancel")}
                >
                  <X className="h-4 w-4" />
                </Button>
              </div>
            ) : (
              form.specialization_id && (
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  className="-ml-2 h-7 text-xs"
                  onClick={() => setGradeAddOpen(true)}
                  data-testid="position-edit-btn-add-grade"
                >
                  <Plus className="mr-1 h-3.5 w-3.5" />
                  {t("addNewGrade")}
                </Button>
              )
            )}
          </div>

          {selectedGradeRow ? (
            selectedGradeRow.matrix_status === "configured" ? (
              <div
                data-testid="position-edit-matrix-ok"
                className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs dark:border-emerald-900 dark:bg-emerald-950"
              >
                <span className="font-medium text-emerald-900 dark:text-emerald-200">
                  {t("matrixConfiguredCheck")}
                </span>{" "}
                <span className="text-emerald-800 dark:text-emerald-300">
                  {t("matrixCompetenceCountSuffix", {
                    count: selectedGradeRow.competence_count,
                  })}
                </span>
                {salaryPreview ? (
                  <span className="text-emerald-800 dark:text-emerald-300">
                    {" "}
                    · {salaryPreview}
                  </span>
                ) : null}
              </div>
            ) : (
              <div
                data-testid="position-edit-matrix-missing"
                className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs dark:border-amber-800 dark:bg-amber-950"
              >
                <p className="font-medium text-amber-900 dark:text-amber-200">
                  {t("matrixNotConfiguredWarn")}
                </p>
                <p className="mt-1 text-amber-800 dark:text-amber-300">
                  {t("matrixMissingShortHint")}
                </p>
                {matrixDeepLink ? (
                  <Link
                    href={matrixDeepLink}
                    data-testid="position-edit-matrix-configure"
                    className="mt-1 inline-block font-medium text-amber-900 underline underline-offset-2 dark:text-amber-200"
                  >
                    {t("configureMatrixLink")}
                  </Link>
                ) : null}
              </div>
            )
          ) : null}

          {/* §5.1: salary preview lives next to the matrix banner so the
              operator sees inheritance even when the matrix is empty. */}
          {isCreate && salaryPreview ? (
            <div
              data-testid="position-edit-salary-preview"
              className="text-xs text-muted-foreground"
            >
              {t("salaryInheritsPreview", { salary: salaryPreview })}
            </div>
          ) : null}

          <div className="space-y-2">
            <Label>{t("titleRequired")}</Label>
            <Input
              data-testid="position-edit-input-title"
              value={form.title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={
                isCreate
                  ? t("titleAutoFilledPlaceholder")
                  : undefined
              }
            />
            <FieldError
              message={saveError.fields.title}
              testId="position-edit-error-title"
            />
          </div>

          <div className="space-y-2">
            <Label>{t("division")}</Label>
            <Select
              value={form.division_id}
              onValueChange={(val) =>
                setForm((prev) => ({ ...prev, division_id: val }))
              }
            >
              <SelectTrigger
                className="w-full"
                data-testid="position-edit-select-division"
              >
                <SelectValue placeholder={t("none")}>
                  {(() => {
                    if (!form.division_id) return undefined;
                    const d = flatDivisions.find(
                      (x) => x.id === form.division_id,
                    );
                    return d ? d.name : undefined;
                  })()}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="">{t("none")}</SelectItem>
                {flatDivisions.map((d) => (
                  <SelectItem key={d.id} value={d.id}>
                    {"—".repeat(d.depth)} {d.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label>{t("headcount")}</Label>
            <Input
              data-testid="position-edit-input-headcount"
              type="number"
              min={0}
              value={form.headcount}
              onChange={(e) =>
                setForm((prev) => ({ ...prev, headcount: e.target.value }))
              }
              placeholder={t("noLimit")}
            />
            <FieldError
              message={saveError.fields.headcount}
              testId="position-edit-error-headcount"
            />
          </div>

          <div className="space-y-2">
            <Label>{t("lifecycleStatus")}</Label>
            <Select
              value={form.lifecycle_status}
              onValueChange={(val) =>
                setForm((prev) => ({
                  ...prev,
                  lifecycle_status: val as PositionLifecycleStatus,
                }))
              }
            >
              <SelectTrigger
                className="w-full"
                data-testid="position-edit-select-status"
              >
                <SelectValue>
                  {t(POSITION_LIFECYCLE_LABEL_KEY[form.lifecycle_status])}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {LIFECYCLE_OPTIONS.map((status) => (
                  <SelectItem key={status} value={status}>
                    {t(POSITION_LIFECYCLE_LABEL_KEY[status])}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label>{t("descriptionOverride")}</Label>
            <Textarea
              data-testid="position-edit-input-description"
              value={form.description}
              onChange={(e) =>
                setForm((prev) => ({ ...prev, description: e.target.value }))
              }
              rows={3}
              placeholder={t("descriptionOverridePlaceholder")}
            />
            <p
              data-testid="position-edit-description-counter"
              className={`text-xs ${
                overLimit ? "text-destructive" : "text-muted-foreground"
              }`}
            >
              {form.description.length} / {DESCRIPTION_LIMIT}
            </p>
          </div>

          {showEmployeeImpactWarning && position ? (
            <div
              data-testid="position-edit-employee-impact-warning"
              className="flex gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs dark:border-amber-800 dark:bg-amber-950"
            >
              <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0 text-amber-700 dark:text-amber-300" />
              <div className="text-amber-900 dark:text-amber-200">
                <p className="font-medium">
                  {t("employeeImpactCount", {
                    count: position.employee_count,
                  })}
                </p>
                <p className="mt-1 text-amber-800 dark:text-amber-300">
                  {t("employeeImpactHint")}
                </p>
              </div>
            </div>
          ) : null}
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={saving}
          >
            {tc("cancel")}
          </Button>
          <Button
            data-testid="position-edit-btn-save"
            onClick={handleSave}
            disabled={saving || !form.title.trim() || overLimit}
          >
            {saving ? t("savingEllipsis") : saveLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
