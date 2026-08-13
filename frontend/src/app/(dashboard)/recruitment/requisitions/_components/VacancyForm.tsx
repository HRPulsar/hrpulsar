"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { MultiSelectFilter } from "@/components/multi-select-filter";
import { HiringManagerSelect } from "@/components/recruitment/hiring-manager-select";
import { api } from "@/lib/api";
import {
  deriveSalaryFromBands,
  isSalaryEmpty,
  parseSalaryInput,
  sameSalary,
  validateSalaryRange,
} from "@/lib/vacancy-salary";
import type { SalaryBand, SalaryFormValues } from "@/lib/vacancy-salary";

// HRP-320: vacancy create form is anchored on the company library.
//   Position (single, optional)  → constrains Specializations
//   Specializations (multi, opt) → constrains Grades
//   Grades (multi, optional)     → seeds the competence matrix on save
//   Division (single, optional)  → from Company → Divisions
//
// The freeform Specialization / Grade / Division text inputs and the
// legacy "Library refs (optional)" block were superseded by these fields
// and have been retired.
export type VacancyFormValues = {
  title: string;
  position_id: string | null;
  specialization_ids: string[];
  grade_ids: string[];
  division_id: string | null;
  // HRP-360
  hiring_manager_id: string | null;
  location: string;
  employment_type: string;
  // HRP-440 — kept as strings while editing, like the Overview block.
  salary_min: string;
  salary_max: string;
  salary_currency: string;
  description: string;
  tasks_main: string;
  tasks_additional: string;
  tasks_kpi: string;
  // HRP-135 — manual textual inputs fed into the AI prompt.
  requirements: string;
  responsibilities: string;
  conditions: string;
};

export const emptyVacancyForm: VacancyFormValues = {
  title: "",
  position_id: null,
  specialization_ids: [],
  grade_ids: [],
  division_id: null,
  hiring_manager_id: null,
  location: "",
  employment_type: "",
  salary_min: "",
  salary_max: "",
  salary_currency: "",
  description: "",
  tasks_main: "",
  tasks_additional: "",
  tasks_kpi: "",
  requirements: "",
  responsibilities: "",
  conditions: "",
};

// HRP-476: labels live in the `recruitment` i18n namespace; this map only
// owns the API code → key relation.
const employmentTypes = [
  { value: "full_time", labelKey: "employmentTypeFullTime" },
  { value: "part_time", labelKey: "employmentTypePartTime" },
  { value: "contract", labelKey: "employmentTypeContract" },
  { value: "internship", labelKey: "employmentTypeInternship" },
  { value: "temporary", labelKey: "employmentTypeTemporary" },
  { value: "remote", labelKey: "employmentTypeRemote" },
];

type Props = {
  values: VacancyFormValues;
  onChange: (next: VacancyFormValues) => void;
  disabled?: boolean;
  testId?: string;
  footer: React.ReactNode;
  heading?: React.ReactNode;
};

interface PositionOption {
  id: string;
  title?: string;
  lifecycle_status?: string;
  is_active?: boolean;
  division_id?: string | null;
  specializations?: { id: string; title?: string | null }[];
  grades?: { id: string; title?: string | null }[];
}

interface DivisionOption {
  id: string;
  name?: string;
}

// HRP-440: the salary band configured on the specialization page.
interface SpecializationGradeRow {
  grade_id: string;
  salary_min?: number | null;
  salary_max?: number | null;
  salary_currency?: string | null;
}

export function VacancyForm({
  values,
  onChange,
  disabled,
  testId = "recruitment-vacancy-create-form",
  footer,
  heading,
}: Props) {
  const t = useTranslations("recruitment");

  function updateField<K extends keyof VacancyFormValues>(
    field: K,
    value: VacancyFormValues[K],
  ) {
    onChange({ ...values, [field]: value });
  }

  // The salary autofill below runs inside an async effect keyed on the
  // library selection only; these refs keep it writing against the live
  // form state instead of the values captured when the effect started.
  const valuesRef = useRef(values);
  const onChangeRef = useRef(onChange);
  useEffect(() => {
    valuesRef.current = values;
    onChangeRef.current = onChange;
  });

  const [positions, setPositions] = useState<PositionOption[]>([]);
  const [divisions, setDivisions] = useState<DivisionOption[]>([]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await api.get<{ items?: PositionOption[] } | PositionOption[]>(
          "/positions?limit=500",
        );
        if (cancelled) return;
        const items = Array.isArray(data) ? data : (data.items ?? []);
        setPositions(items);
      } catch {
        // ignore — selector stays empty, the form still saves without it
      }
    })();
    (async () => {
      try {
        const flatten = (list: unknown[]): DivisionOption[] => {
          const out: DivisionOption[] = [];
          for (const node of list) {
            if (!node || typeof node !== "object") continue;
            const n = node as { id?: string; name?: string; children?: unknown[] };
            if (n.id) out.push({ id: n.id, name: n.name });
            if (n.children && Array.isArray(n.children)) {
              out.push(...flatten(n.children));
            }
          }
          return out;
        };
        const data = await api.get<unknown[]>("/divisions");
        if (cancelled) return;
        setDivisions(flatten(Array.isArray(data) ? data : []));
      } catch {
        // ignore
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // HRP-320: only Active positions land in the picker per spec.
  const activePositions = useMemo(
    () =>
      positions.filter(
        (p) =>
          (p.lifecycle_status ? p.lifecycle_status === "active" : true) &&
          (typeof p.is_active === "boolean" ? p.is_active : true),
      ),
    [positions],
  );

  const selectedPosition = useMemo(
    () =>
      values.position_id
        ? activePositions.find((p) => p.id === values.position_id) ??
          positions.find((p) => p.id === values.position_id) ??
          null
        : null,
    [activePositions, positions, values.position_id],
  );

  const specializationOptions = useMemo(
    () =>
      (selectedPosition?.specializations ?? []).map((s) => ({
        value: s.id,
        label: s.title || s.id,
      })),
    [selectedPosition],
  );
  const gradeOptions = useMemo(
    () =>
      (selectedPosition?.grades ?? []).map((g) => ({
        value: g.id,
        label: g.title || g.id,
      })),
    [selectedPosition],
  );

  const positionOptions = activePositions.map((p) => ({
    value: p.id,
    label: p.title || p.id,
  }));
  const divisionOptions = divisions.map((d) => ({
    value: d.id,
    label: d.name || d.id,
  }));

  function handlePositionChange(nextRaw: string) {
    const next = nextRaw || null;
    if (next === values.position_id) return;
    const target = next
      ? activePositions.find((p) => p.id === next) ?? null
      : null;
    onChange({
      ...values,
      position_id: next,
      // Spec / grade picks belong to the previous Position — drop them.
      specialization_ids: [],
      grade_ids: [],
      // Position carries a default Division; keep an explicit pick over it.
      division_id: values.division_id ?? target?.division_id ?? null,
    });
  }

  function handleSpecializationsChange(nextIds: string[]) {
    // Grades are constrained by the chosen Specializations; dropping a
    // Specialization invalidates grades that only existed for it. Since
    // PositionRead currently exposes grades as a flat list (not per-spec),
    // we conservatively wipe the selection whenever specs shrink — once
    // PositionRead grows per-spec grade pools we can prune surgically.
    onChange({
      ...values,
      specialization_ids: nextIds,
      grade_ids: nextIds.length === 0 ? [] : values.grade_ids,
    });
  }

  // HRP-440 Task 2: a Specialization × Grade pair may carry a salary band
  // on the specialization page. Picking such a pair prefills the range —
  // but only while the recruiter has not typed their own numbers, so an
  // autofill can never overwrite a deliberate override.
  const autofilledSalary = useRef<SalaryFormValues | null>(null);
  const specKey = values.specialization_ids.join(",");
  const gradeKey = values.grade_ids.join(",");

  useEffect(() => {
    const specIds = specKey ? specKey.split(",") : [];
    const gradeIds = new Set(gradeKey ? gradeKey.split(",") : []);
    if (specIds.length === 0 || gradeIds.size === 0) return;

    let cancelled = false;
    (async () => {
      const bands: SalaryBand[] = [];
      for (const specId of specIds) {
        try {
          const rows = await api.get<SpecializationGradeRow[]>(
            `/specializations/${specId}/grades`,
          );
          for (const row of rows) {
            if (!gradeIds.has(row.grade_id)) continue;
            bands.push({
              salary_min: row.salary_min ?? null,
              salary_max: row.salary_max ?? null,
              salary_currency: row.salary_currency ?? null,
            });
          }
        } catch {
          // A specialization we cannot read simply contributes no band.
        }
      }
      if (cancelled) return;
      const derived = deriveSalaryFromBands(bands);
      if (!derived) return;
      const current = valuesRef.current;
      const currentSalary = {
        salary_min: current.salary_min,
        salary_max: current.salary_max,
        salary_currency: current.salary_currency,
      };
      const untouched =
        isSalaryEmpty(currentSalary) ||
        (autofilledSalary.current !== null &&
          sameSalary(currentSalary, autofilledSalary.current));
      if (!untouched) return;
      autofilledSalary.current = derived;
      onChangeRef.current({ ...current, ...derived });
    })();
    return () => {
      cancelled = true;
    };
  }, [specKey, gradeKey]);

  const salaryError = validateSalaryRange({
    salary_min: values.salary_min,
    salary_max: values.salary_max,
    salary_currency: values.salary_currency,
  });

  const specsDisabled = !values.position_id;
  const specsPlaceholder = specsDisabled
    ? t("vacancySelectPositionFirst")
    : t("selectPlaceholder");
  const gradesDisabled =
    !values.position_id || values.specialization_ids.length === 0;
  const gradesPlaceholder = !values.position_id
    ? t("vacancySelectPositionFirst")
    : values.specialization_ids.length === 0
      ? t("vacancySelectSpecializationsFirst")
      : t("selectPlaceholder");

  return (
    <div data-testid={testId} className="space-y-6">
      {heading}
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-5 lg:col-span-2">
          <div className="space-y-2">
            <Label htmlFor="title">{t("vacancyFieldTitle")}</Label>
            <Input
              id="title"
              data-testid="recruitment-vacancy-input-title"
              placeholder={t("vacancyTitlePlaceholder")}
              value={values.title}
              disabled={disabled}
              onChange={(e) => updateField("title", e.target.value)}
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="position">{t("columnPosition")}</Label>
              <Select
                value={values.position_id ?? ""}
                onValueChange={handlePositionChange}
                disabled={disabled}
              >
                <SelectTrigger
                  id="position"
                  data-testid="recruitment-vacancy-select-position"
                >
                  <SelectValue placeholder={t("selectPlaceholder")}>
                    {selectedPosition?.title ?? t("selectPlaceholder")}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {positionOptions.length === 0 ? (
                    <div className="px-2 py-1 text-xs text-muted-foreground">
                      {t("vacancyNoActivePositions")}
                    </div>
                  ) : (
                    positionOptions.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>
                        {opt.label}
                      </SelectItem>
                    ))
                  )}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="division">{t("columnDivision")}</Label>
              <Select
                value={values.division_id ?? ""}
                onValueChange={(val: string) =>
                  updateField("division_id", val || null)
                }
                disabled={disabled}
              >
                <SelectTrigger
                  id="division"
                  data-testid="recruitment-vacancy-select-division"
                >
                  <SelectValue placeholder={t("selectPlaceholder")}>
                    {divisions.find((d) => d.id === values.division_id)?.name ??
                      t("selectPlaceholder")}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {divisionOptions.length === 0 ? (
                    <div className="px-2 py-1 text-xs text-muted-foreground">
                      {t("vacancyNoDivisions")}
                    </div>
                  ) : (
                    divisionOptions.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>
                        {opt.label}
                      </SelectItem>
                    ))
                  )}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="hiring_manager">
                {t("vacancyFieldHiringManager")}
              </Label>
              <HiringManagerSelect
                id="hiring_manager"
                testId="recruitment-vacancy-select-hiring-manager"
                value={values.hiring_manager_id}
                onChange={(next) => updateField("hiring_manager_id", next)}
                disabled={disabled}
              />
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label>{t("vacancyFieldSpecializations")}</Label>
              <MultiSelectFilter
                options={specializationOptions}
                value={values.specialization_ids}
                onChange={handleSpecializationsChange}
                placeholder={specsPlaceholder}
                disabled={disabled || specsDisabled}
                data-testid="recruitment-vacancy-select-specializations"
              />
            </div>
            <div className="space-y-2">
              <Label>{t("vacancyFieldGrades")}</Label>
              <MultiSelectFilter
                options={gradeOptions}
                value={values.grade_ids}
                onChange={(next) => updateField("grade_ids", next)}
                placeholder={gradesPlaceholder}
                disabled={disabled || gradesDisabled}
                data-testid="recruitment-vacancy-select-grades"
              />
            </div>
          </div>

          {/* HRP-440: the same salary contract the Overview block edits. */}
          <div className="space-y-2">
            <Label htmlFor="salary_min">{t("vacancyFieldSalaryRange")}</Label>
            <div className="flex items-center gap-2">
              <Input
                id="salary_min"
                type="number"
                min={0}
                data-testid="recruitment-vacancy-input-salary-min"
                placeholder={t("vacancySalaryMinPlaceholder")}
                value={values.salary_min}
                disabled={disabled}
                onChange={(e) => updateField("salary_min", e.target.value)}
              />
              <span className="text-muted-foreground">–</span>
              <Input
                type="number"
                min={0}
                data-testid="recruitment-vacancy-input-salary-max"
                placeholder={t("vacancySalaryMaxPlaceholder")}
                value={values.salary_max}
                disabled={disabled}
                onChange={(e) => updateField("salary_max", e.target.value)}
              />
              <Input
                className="w-24"
                data-testid="recruitment-vacancy-input-salary-currency"
                placeholder={t("vacancySalaryCurrencyPlaceholder")}
                value={values.salary_currency}
                disabled={disabled}
                onChange={(e) => updateField("salary_currency", e.target.value)}
              />
            </div>
            {salaryError && (
              <p
                className="text-xs text-destructive"
                data-testid="recruitment-vacancy-salary-error"
              >
                {t(salaryError)}
              </p>
            )}
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="location">{t("candidateFieldLocation")}</Label>
              <Input
                id="location"
                data-testid="recruitment-vacancy-input-location"
                placeholder={t("vacancyLocationPlaceholder")}
                value={values.location}
                disabled={disabled}
                onChange={(e) => updateField("location", e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="employment_type">
                {t("vacancyFieldEmploymentType")}
              </Label>
              <Select
                value={values.employment_type}
                onValueChange={(val: string) =>
                  updateField("employment_type", val)
                }
                disabled={disabled}
              >
                <SelectTrigger
                  id="employment_type"
                  data-testid="recruitment-vacancy-select-employment"
                >
                  <SelectValue placeholder={t("vacancySelectType")}>
                    {(() => {
                      const picked = employmentTypes.find(
                        (opt) => opt.value === values.employment_type,
                      );
                      return picked
                        ? t(picked.labelKey)
                        : t("vacancySelectType");
                    })()}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {employmentTypes.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {t(opt.labelKey)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="description">{t("vacancyFieldDescription")}</Label>
            <Textarea
              id="description"
              data-testid="recruitment-vacancy-input-description"
              placeholder={t("vacancyDescriptionPlaceholder")}
              value={values.description}
              disabled={disabled}
              onChange={(e) => updateField("description", e.target.value)}
              rows={5}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="requirements">
              {t("vacancyFieldRequirements")}
            </Label>
            <Textarea
              id="requirements"
              data-testid="recruitment-vacancy-input-requirements"
              placeholder={t("vacancyRequirementsPlaceholder")}
              value={values.requirements}
              disabled={disabled}
              onChange={(e) => updateField("requirements", e.target.value)}
              rows={4}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="responsibilities">
              {t("vacancyFieldResponsibilities")}
            </Label>
            <Textarea
              id="responsibilities"
              data-testid="recruitment-vacancy-input-responsibilities"
              placeholder={t("vacancyResponsibilitiesPlaceholder")}
              value={values.responsibilities}
              disabled={disabled}
              onChange={(e) => updateField("responsibilities", e.target.value)}
              rows={4}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="conditions">{t("vacancyFieldConditions")}</Label>
            <Textarea
              id="conditions"
              data-testid="recruitment-vacancy-input-conditions"
              placeholder={t("vacancyConditionsPlaceholder")}
              value={values.conditions}
              disabled={disabled}
              onChange={(e) => updateField("conditions", e.target.value)}
              rows={3}
            />
          </div>
        </div>

        <div className="space-y-4 rounded-lg bg-muted/50 p-5">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            {t("vacancyTasksHeading")}
          </h2>

          <div className="space-y-2">
            <Label htmlFor="tasks_main">{t("vacancyFieldTasksMain")}</Label>
            <Textarea
              id="tasks_main"
              data-testid="recruitment-vacancy-input-tasks-main"
              placeholder={t("vacancyTasksMainPlaceholder")}
              value={values.tasks_main}
              disabled={disabled}
              onChange={(e) => updateField("tasks_main", e.target.value)}
              rows={4}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="tasks_additional">
              {t("vacancyFieldTasksAdditional")}
            </Label>
            <Textarea
              id="tasks_additional"
              data-testid="recruitment-vacancy-input-tasks-additional"
              placeholder={t("vacancyTasksAdditionalPlaceholder")}
              value={values.tasks_additional}
              disabled={disabled}
              onChange={(e) => updateField("tasks_additional", e.target.value)}
              rows={4}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="tasks_kpi">{t("vacancyFieldTasksKpi")}</Label>
            <Textarea
              id="tasks_kpi"
              data-testid="recruitment-vacancy-input-tasks-kpi"
              placeholder={t("vacancyTasksKpiPlaceholder")}
              value={values.tasks_kpi}
              disabled={disabled}
              onChange={(e) => updateField("tasks_kpi", e.target.value)}
              rows={4}
            />
          </div>
        </div>
      </div>

      <div className="flex items-center justify-end gap-3 border-t pt-4">
        {footer}
      </div>
    </div>
  );
}

export function vacancyFormToPayload(
  values: VacancyFormValues,
): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    title: values.title.trim(),
    description: values.description.trim() || null,
    location: values.location.trim() || null,
    employment_type: values.employment_type || null,
    tasks_main: values.tasks_main.trim() ? { text: values.tasks_main.trim() } : null,
    tasks_additional: values.tasks_additional.trim()
      ? { text: values.tasks_additional.trim() }
      : null,
    tasks_kpi: values.tasks_kpi.trim() ? { text: values.tasks_kpi.trim() } : null,
    requirements: values.requirements.trim() || null,
    responsibilities: values.responsibilities.trim() || null,
    conditions: values.conditions.trim() || null,
    position_id: values.position_id,
    specialization_ids: values.specialization_ids,
    grade_ids: values.grade_ids,
    division_id: values.division_id,
    hiring_manager_id: values.hiring_manager_id,
    // HRP-440
    salary_min: parseSalaryInput(values.salary_min),
    salary_max: parseSalaryInput(values.salary_max),
    salary_currency: values.salary_currency.trim() || null,
  };
  // HRP-320 Task 2: forward Specializations × Grades so the backend can
  // seed Competences & indicators from the matching matrices. The new form
  // intentionally maps every chosen Specialization against every chosen
  // Grade — the spec calls out a target where each Specialization carries
  // its own Grade subset, but PositionRead does not yet expose that pool,
  // so cartesian wiring matches what the user actually selected.
  if (values.specialization_ids.length || values.position_id) {
    payload.library_refs = {
      position_ids: values.position_id ? [values.position_id] : [],
      specialization_grade_pairs: values.specialization_ids.map((specId) => ({
        specialization_id: specId,
        grade_ids: values.grade_ids,
      })),
      division_ids: values.division_id ? [values.division_id] : [],
    };
  }
  return payload;
}

export function vacancyToFormValues(
  vacancy: Record<string, unknown>,
): VacancyFormValues {
  const numberText = (value: unknown) =>
    typeof value === "number" ? String(value) : "";
  const taskText = (key: string) => {
    const value = vacancy[key];
    if (
      value &&
      typeof value === "object" &&
      "text" in value &&
      typeof (value as { text: unknown }).text === "string"
    ) {
      return (value as { text: string }).text;
    }
    return "";
  };
  const specs = Array.isArray(vacancy.specializations)
    ? (vacancy.specializations as { id?: string }[])
    : [];
  const grades = Array.isArray(vacancy.grades)
    ? (vacancy.grades as { id?: string }[])
    : [];
  return {
    title: (vacancy.title as string | undefined) ?? "",
    position_id: (vacancy.position_id as string | undefined) ?? null,
    specialization_ids: specs
      .map((s) => s.id)
      .filter((id): id is string => typeof id === "string"),
    grade_ids: grades
      .map((g) => g.id)
      .filter((id): id is string => typeof id === "string"),
    division_id: (vacancy.division_id as string | undefined) ?? null,
    hiring_manager_id:
      (vacancy.hiring_manager_id as string | undefined) ?? null,
    location: (vacancy.location as string | undefined) ?? "",
    employment_type: (vacancy.employment_type as string | undefined) ?? "",
    salary_min: numberText(vacancy.salary_min),
    salary_max: numberText(vacancy.salary_max),
    salary_currency: (vacancy.salary_currency as string | undefined) ?? "",
    description: (vacancy.description as string | undefined) ?? "",
    tasks_main: taskText("tasks_main"),
    tasks_additional: taskText("tasks_additional"),
    tasks_kpi: taskText("tasks_kpi"),
    requirements: (vacancy.requirements as string | undefined) ?? "",
    responsibilities: (vacancy.responsibilities as string | undefined) ?? "",
    conditions: (vacancy.conditions as string | undefined) ?? "",
  };
}
