"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { ApiError, api } from "@/lib/api";
import { getDefaultSalaryCurrency } from "@/lib/currency";
import {
  parseSalaryInput,
  validateSalaryRange,
} from "@/lib/vacancy-salary";
import type { Vacancy } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { ChevronDown, ChevronUp, ExternalLink, Pencil } from "lucide-react";
import { toast } from "sonner";

import { trimLongText } from "@/lib/long-text";

// HRP-319: max-height ≈ 20 lines of textarea content. 1.5rem ≈ a single text line
// with the default leading, so 30rem caps the textarea at ~20 rows before the
// internal scrollbar kicks in.
const LONG_TEXTAREA_MAX_HEIGHT = "30rem";

// HRP-476: labels live in the `recruitment` i18n namespace; this map only
// owns the API code → key relation (mirrors VacancyForm).
const employmentTypes = [
  { value: "full_time", labelKey: "employmentTypeFullTime" },
  { value: "part_time", labelKey: "employmentTypePartTime" },
  { value: "contract", labelKey: "employmentTypeContract" },
  { value: "internship", labelKey: "employmentTypeInternship" },
  { value: "temporary", labelKey: "employmentTypeTemporary" },
  { value: "remote", labelKey: "employmentTypeRemote" },
];

interface PositionOption {
  id: string;
  title: string;
  division_id?: string | null;
  specializations?: { id: string; title?: string | null }[];
  grades?: { id: string; title?: string | null }[];
}

interface DivisionOption {
  id: string;
  name?: string | null;
}

interface OverviewFormValues {
  position_id: string | null;
  specialization_ids: string[];
  grade_ids: string[];
  division_id: string | null;
  // HRP-360
  hiring_manager_id: string | null;
  location: string;
  employment_type: string;
  salary_min: string;
  salary_max: string;
  salary_currency: string;
  description: string;
  // HRP-239: align the Overview section with the create / edit form so
  // recruiters see the exact same fields in the same order.
  requirements: string;
  responsibilities: string;
  conditions: string;
  tasks_main: string;
  tasks_additional: string;
  tasks_kpi: string;
}

function extractTaskText(value: Record<string, unknown> | null | undefined): string {
  if (!value) return "";
  if (typeof value === "object" && "text" in value && typeof value.text === "string") {
    return value.text;
  }
  // Avoid leaking JSON sigils into the UI — fall back to an empty string
  // when the field carries an opaque payload.
  return "";
}

function vacancyToOverviewForm(vacancy: Vacancy): OverviewFormValues {
  return {
    position_id: vacancy.position_id ?? null,
    specialization_ids: (vacancy.specializations ?? []).map((s) => s.id),
    grade_ids: (vacancy.grades ?? []).map((g) => g.id),
    division_id: vacancy.division_id ?? null,
    hiring_manager_id: vacancy.hiring_manager_id ?? null,
    location: vacancy.location ?? "",
    employment_type: vacancy.employment_type ?? "",
    salary_min: vacancy.salary_min != null ? String(vacancy.salary_min) : "",
    salary_max: vacancy.salary_max != null ? String(vacancy.salary_max) : "",
    salary_currency: vacancy.salary_currency ?? "",
    description: vacancy.description ?? "",
    requirements: vacancy.requirements ?? "",
    responsibilities: vacancy.responsibilities ?? "",
    conditions: vacancy.conditions ?? "",
    tasks_main: extractTaskText(vacancy.tasks_main),
    tasks_additional: extractTaskText(vacancy.tasks_additional),
    tasks_kpi: extractTaskText(vacancy.tasks_kpi),
  };
}

function overviewFormToPatch(
  initial: OverviewFormValues,
  current: OverviewFormValues,
): Record<string, unknown> {
  const patch: Record<string, unknown> = {};
  if (current.position_id !== initial.position_id) {
    patch.position_id = current.position_id;
  }
  if (
    JSON.stringify(current.specialization_ids) !==
    JSON.stringify(initial.specialization_ids)
  ) {
    patch.specialization_ids = current.specialization_ids;
  }
  if (JSON.stringify(current.grade_ids) !== JSON.stringify(initial.grade_ids)) {
    patch.grade_ids = current.grade_ids;
  }
  if (current.division_id !== initial.division_id) {
    patch.division_id = current.division_id;
  }
  if (current.hiring_manager_id !== initial.hiring_manager_id) {
    patch.hiring_manager_id = current.hiring_manager_id;
  }
  if (current.location !== initial.location) {
    patch.location = current.location || null;
  }
  if (current.employment_type !== initial.employment_type) {
    patch.employment_type = current.employment_type || null;
  }
  // HRP-440: shared with the Create / Edit form so a blank or malformed
  // number resolves to NULL identically on both surfaces.
  const salaryMin = parseSalaryInput(current.salary_min);
  const initialMin = parseSalaryInput(initial.salary_min);
  if (salaryMin !== initialMin) patch.salary_min = salaryMin;
  const salaryMax = parseSalaryInput(current.salary_max);
  const initialMax = parseSalaryInput(initial.salary_max);
  if (salaryMax !== initialMax) patch.salary_max = salaryMax;
  if (current.salary_currency !== initial.salary_currency) {
    patch.salary_currency = current.salary_currency || null;
  }
  if (current.description !== initial.description) {
    patch.description = current.description || null;
  }
  if (current.requirements !== initial.requirements) {
    patch.requirements = current.requirements || null;
  }
  if (current.responsibilities !== initial.responsibilities) {
    patch.responsibilities = current.responsibilities || null;
  }
  if (current.conditions !== initial.conditions) {
    patch.conditions = current.conditions || null;
  }
  if (current.tasks_main !== initial.tasks_main) {
    patch.tasks_main = current.tasks_main ? { text: current.tasks_main } : null;
  }
  if (current.tasks_additional !== initial.tasks_additional) {
    patch.tasks_additional = current.tasks_additional
      ? { text: current.tasks_additional }
      : null;
  }
  if (current.tasks_kpi !== initial.tasks_kpi) {
    patch.tasks_kpi = current.tasks_kpi ? { text: current.tasks_kpi } : null;
  }
  return patch;
}

interface VacancyOverviewSectionProps {
  vacancy: Vacancy;
  etag: string | null;
  canEdit: boolean;
  onSaved: (next: Vacancy, etag: string | null) => void;
}

export function VacancyOverviewSection({
  vacancy,
  etag,
  canEdit,
  onSaved,
}: VacancyOverviewSectionProps) {
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const initial = useMemo(() => vacancyToOverviewForm(vacancy), [vacancy]);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<OverviewFormValues>(initial);
  const [saving, setSaving] = useState(false);
  const [positions, setPositions] = useState<PositionOption[]>([]);
  const [divisions, setDivisions] = useState<DivisionOption[]>([]);
  const [pendingPositionChange, setPendingPositionChange] = useState<
    string | null
  >(null);

  useEffect(() => {
    setForm(initial);
  }, [initial]);

  useEffect(() => {
    if (!editing) return;
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
        // ignore — selector will stay empty and the form still saves
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
  }, [editing]);

  const selectedPosition = useMemo(
    () => positions.find((p) => p.id === form.position_id) ?? null,
    [positions, form.position_id],
  );

  const positionSpecOptions = useMemo(
    () =>
      (selectedPosition?.specializations ?? []).map((s) => ({
        value: s.id,
        label: s.title || s.id,
      })),
    [selectedPosition],
  );
  const positionGradeOptions = useMemo(
    () =>
      (selectedPosition?.grades ?? []).map((g) => ({
        value: g.id,
        label: g.title || g.id,
      })),
    [selectedPosition],
  );

  function applyPositionSwitch(nextId: string | null) {
    const target = nextId
      ? positions.find((p) => p.id === nextId) ?? null
      : null;
    setForm((prev) => {
      const newSpec = target?.specializations?.map((s) => s.id) ?? [];
      const newGrade = target?.grades?.map((g) => g.id) ?? [];
      return {
        ...prev,
        position_id: nextId,
        specialization_ids: newSpec,
        grade_ids: newGrade,
        division_id: target?.division_id ?? prev.division_id,
      };
    });
  }

  function handlePositionChange(next: string) {
    const nextId = next || null;
    if (nextId === form.position_id) return;
    const hadSelection =
      form.specialization_ids.length > 0 || form.grade_ids.length > 0;
    if (hadSelection) {
      setPendingPositionChange(next);
      return;
    }
    applyPositionSwitch(nextId);
  }

  function setField<K extends keyof OverviewFormValues>(
    key: K,
    value: OverviewFormValues[K],
  ) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  const isDirty = JSON.stringify(form) !== JSON.stringify(initial);

  function handleCancel() {
    if (isDirty && !window.confirm(t("vacancyOverviewDiscardConfirm"))) {
      return;
    }
    setForm(initial);
    setEditing(false);
  }

  async function handleSave() {
    if (!isDirty) return;
    // HRP-440: same guard as the Create / Edit form.
    const salaryError = validateSalaryRange(form);
    if (salaryError) {
      toast.error(t(salaryError));
      return;
    }
    setSaving(true);
    try {
      const payload = overviewFormToPatch(initial, form);
      const { data: updated, headers } = await api.sendWithMeta<Vacancy>(
        `/recruitment/vacancies/${vacancy.id}`,
        "PATCH",
        payload,
        etag ? { headers: { "If-Match": etag } } : undefined,
      );
      toast.success(t("vacancyOverviewToastSaved"));
      onSaved(updated, headers.get("ETag"));
      setEditing(false);
    } catch (err) {
      if (err instanceof ApiError && err.status === 412) {
        toast.error(t("vacancyConflictRetry"));
      } else {
        toast.error(
          err instanceof Error ? err.message : t("vacancyUpdateFailed"),
        );
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card data-testid="vacancy-section-overview" id="overview">
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <CardTitle>{t("vacancyTabOverview")}</CardTitle>
        {canEdit && !editing && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => setEditing(true)}
            data-testid="vacancy-section-overview-edit-btn"
          >
            <Pencil className="mr-1 size-4" />
            {t("actionEdit")}
          </Button>
        )}
        {editing && (
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={handleCancel}
              disabled={saving}
              data-testid="vacancy-section-overview-cancel-btn"
            >
              {tc("cancel")}
            </Button>
            <Button
              size="sm"
              onClick={handleSave}
              disabled={saving || !isDirty}
              data-testid="vacancy-section-overview-save-btn"
            >
              {saving ? t("actionSaving") : t("save")}
            </Button>
          </div>
        )}
      </CardHeader>
      <CardContent className="space-y-6">
        {editing ? (
          <OverviewEditGrid
            form={form}
            setField={setField}
            positions={positions}
            divisions={divisions}
            hiringManagerFallback={vacancy.hiring_manager_name ?? null}
            positionSpecOptions={positionSpecOptions}
            positionGradeOptions={positionGradeOptions}
            disabled={saving}
            onPositionChange={handlePositionChange}
          />
        ) : (
          <OverviewViewGrid
            vacancy={vacancy}
            description={form.description}
            requirements={form.requirements}
            responsibilities={form.responsibilities}
            conditions={form.conditions}
            tasksMain={form.tasks_main}
            tasksAdditional={form.tasks_additional}
            tasksKpi={form.tasks_kpi}
          />
        )}
      </CardContent>

      <ConfirmDialog
        open={pendingPositionChange !== null}
        onOpenChange={(open) => {
          if (!open) setPendingPositionChange(null);
        }}
        title={t("vacancyPositionChangeTitle")}
        description={t("vacancyPositionChangeDescription")}
        confirmLabel={t("vacancyPositionChangeConfirm")}
        onConfirm={() => {
          const target = pendingPositionChange ?? null;
          setPendingPositionChange(null);
          applyPositionSwitch(target || null);
        }}
        testId="vacancy-position-confirm-reset-modal"
      />
    </Card>
  );
}

interface OverviewViewGridProps {
  vacancy: Vacancy;
  description: string;
  requirements: string;
  responsibilities: string;
  conditions: string;
  tasksMain: string;
  tasksAdditional: string;
  tasksKpi: string;
}

function OverviewViewGrid({
  vacancy,
  description,
  requirements,
  responsibilities,
  conditions,
  tasksMain,
  tasksAdditional,
  tasksKpi,
}: OverviewViewGridProps) {
  const t = useTranslations("recruitment");
  const specsLabel = (vacancy.specializations ?? [])
    .map((s) => s.title || s.id)
    .join(", ");
  const gradesLabel = (vacancy.grades ?? [])
    .map((g) => g.title || g.id)
    .join(", ");
  const salaryLabel = formatSalary(t, vacancy);

  return (
    <div className="space-y-6">
      <div className="grid gap-x-6 gap-y-4 sm:grid-cols-3">
        <FieldRow label={t("columnPosition")}>
          {vacancy.position_id ? (
            <Link
              href={`/company/positions/${vacancy.position_id}`}
              className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
              data-testid="vacancy-field-position-link"
            >
              {vacancy.position_title || vacancy.position_id}
              <ExternalLink className="size-3" />
            </Link>
          ) : (
            <EmptyValue />
          )}
        </FieldRow>
        <FieldRow label={t("vacancyFieldSalary")}>
          {salaryLabel ? <span className="text-sm">{salaryLabel}</span> : <EmptyValue />}
        </FieldRow>
        <FieldRow label={t("columnDivision")}>
          {vacancy.division_name ? (
            <span className="text-sm">{vacancy.division_name}</span>
          ) : (
            <EmptyValue />
          )}
        </FieldRow>
        <FieldRow label={t("vacancyFieldSpecializations")}>
          {specsLabel ? <span className="text-sm">{specsLabel}</span> : <EmptyValue />}
        </FieldRow>
        <FieldRow label={t("vacancyFieldEmploymentType")}>
          {vacancy.employment_type ? (
            <span className="text-sm capitalize">
              {vacancy.employment_type.replace("_", " ")}
            </span>
          ) : (
            <EmptyValue />
          )}
        </FieldRow>
        <FieldRow label={t("candidateFieldLocation")}>
          {vacancy.location ? (
            <span className="text-sm">{vacancy.location}</span>
          ) : (
            <EmptyValue />
          )}
        </FieldRow>
        <FieldRow label={t("vacancyFieldGrades")}>
          {gradesLabel ? <span className="text-sm">{gradesLabel}</span> : <EmptyValue />}
        </FieldRow>
        <FieldRow label={t("vacancyFieldHiringManager")}>
          {vacancy.hiring_manager_name ? (
            <span className="text-sm" data-testid="vacancy-field-hiring-manager">
              {vacancy.hiring_manager_name}
            </span>
          ) : (
            <EmptyValue />
          )}
        </FieldRow>
      </div>

      <LongTextField
        testId="vacancy-field-description"
        title={t("vacancyFieldDescription")}
        text={description}
      />

      <div className="grid gap-4 sm:grid-cols-3">
        <LongTextBlock
          testId="vacancy-field-requirements"
          title={t("vacancyFieldRequirements")}
          text={requirements}
        />
        <LongTextBlock
          testId="vacancy-field-responsibilities"
          title={t("vacancyFieldResponsibilities")}
          text={responsibilities}
        />
        <LongTextBlock
          testId="vacancy-field-conditions"
          title={t("vacancyFieldConditions")}
          text={conditions}
        />
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <LongTextBlock
          testId="vacancy-field-main-tasks"
          title={t("vacancyFieldTasksMain")}
          text={tasksMain}
        />
        <LongTextBlock
          testId="vacancy-field-additional-tasks"
          title={t("vacancyFieldTasksAdditional")}
          text={tasksAdditional}
        />
        <LongTextBlock
          testId="vacancy-field-kpi"
          title={t("vacancyFieldKpi")}
          text={tasksKpi}
        />
      </div>
    </div>
  );
}

function LongTextField({
  testId,
  title,
  text,
}: {
  testId: string;
  title: string;
  text: string;
}) {
  const t = useTranslations("recruitment");
  const [expanded, setExpanded] = useState(false);
  const { visible, isLong: long } = trimLongText(text, expanded);
  return (
    <div data-testid={testId} className="space-y-2">
      <h3 className="text-sm font-semibold">{title}</h3>
      {text ? (
        <>
          <p className="whitespace-pre-wrap text-sm text-muted-foreground leading-relaxed">
            {visible}
          </p>
          {long && (
            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              aria-expanded={expanded}
              className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
              data-testid={`${testId}-toggle`}
            >
              {expanded ? (
                <>
                  {t("vacancyShowLess")} <ChevronUp className="size-4" />
                </>
              ) : (
                <>
                  {t("vacancyShowMore")} <ChevronDown className="size-4" />
                </>
              )}
            </button>
          )}
        </>
      ) : (
        <EmptyValue />
      )}
    </div>
  );
}

// HRP-476: the open-ended forms carry a translatable prefix, so the helper
// takes the `recruitment` translator as its first argument.
function formatSalary(
  t: (key: string, values?: Record<string, string>) => string,
  vacancy: Vacancy,
): string {
  const cur = vacancy.salary_currency ? ` ${vacancy.salary_currency}` : "";
  if (vacancy.salary_min != null && vacancy.salary_max != null) {
    return `${vacancy.salary_min}–${vacancy.salary_max}${cur}`;
  }
  if (vacancy.salary_min != null) {
    return t("vacancySalaryFrom", { amount: `${vacancy.salary_min}${cur}` });
  }
  if (vacancy.salary_max != null) {
    return t("vacancySalaryUpTo", { amount: `${vacancy.salary_max}${cur}` });
  }
  return "";
}

function FieldRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <div>{children}</div>
    </div>
  );
}

function EmptyValue() {
  return <span className="text-sm italic text-muted-foreground/70">—</span>;
}

function LongTextBlock({
  testId,
  title,
  text,
}: {
  testId: string;
  title: string;
  text: string;
}) {
  const t = useTranslations("recruitment");
  const [expanded, setExpanded] = useState(false);
  const { visible, isLong: long } = trimLongText(text, expanded);
  return (
    <div className="rounded-md bg-muted/50 p-3" data-testid={testId}>
      <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide">{title}</h4>
      {text ? (
        <>
          <p className="whitespace-pre-wrap text-sm text-muted-foreground">{visible}</p>
          {long && (
            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              aria-expanded={expanded}
              className="mt-2 inline-flex items-center gap-1 text-sm text-primary hover:underline"
              data-testid={`${testId}-toggle`}
            >
              {expanded ? (
                <>
                  {t("vacancyShowLess")} <ChevronUp className="size-4" />
                </>
              ) : (
                <>
                  {t("vacancyShowMore")} <ChevronDown className="size-4" />
                </>
              )}
            </button>
          )}
        </>
      ) : (
        <EmptyValue />
      )}
    </div>
  );
}

interface OverviewEditGridProps {
  form: OverviewFormValues;
  setField: <K extends keyof OverviewFormValues>(
    key: K,
    value: OverviewFormValues[K],
  ) => void;
  positions: PositionOption[];
  divisions: DivisionOption[];
  hiringManagerFallback: string | null;
  positionSpecOptions: { value: string; label: string }[];
  positionGradeOptions: { value: string; label: string }[];
  disabled: boolean;
  onPositionChange: (next: string) => void;
}

function OverviewEditGrid({
  form,
  setField,
  positions,
  divisions,
  hiringManagerFallback,
  positionSpecOptions,
  positionGradeOptions,
  disabled,
  onPositionChange,
}: OverviewEditGridProps) {
  const t = useTranslations("recruitment");
  const specDisabled = !form.position_id || positionSpecOptions.length === 0;
  const gradeDisabled = !form.position_id || positionGradeOptions.length === 0;
  return (
    <div className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-3">
        <div className="space-y-1">
          <Label htmlFor="position-select">{t("columnPosition")}</Label>
          <Select
            value={form.position_id ?? ""}
            onValueChange={(val) => onPositionChange(val)}
            disabled={disabled}
          >
            <SelectTrigger
              id="position-select"
              data-testid="vacancy-field-position-select"
            >
              <SelectValue placeholder={t("vacancySelectPosition")}>
                {form.position_id
                  ? (positions.find((p) => p.id === form.position_id)?.title ??
                    t("vacancySelectPosition"))
                  : t("vacancySelectPosition")}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              {positions.map((p) => (
                <SelectItem key={p.id} value={p.id}>
                  {p.title}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <Label>{t("vacancyFieldSalaryRange")}</Label>
          <div className="flex items-center gap-2">
            <Input
              type="number"
              value={form.salary_min}
              onChange={(e) => setField("salary_min", e.target.value)}
              placeholder={t("vacancySalaryMinPlaceholder")}
              disabled={disabled}
              data-testid="vacancy-field-salary"
            />
            <span className="text-muted-foreground">–</span>
            <Input
              type="number"
              value={form.salary_max}
              onChange={(e) => setField("salary_max", e.target.value)}
              placeholder={t("vacancySalaryMaxPlaceholder")}
              disabled={disabled}
            />
            <Input
              className="w-20"
              value={form.salary_currency}
              onChange={(e) => setField("salary_currency", e.target.value)}
              // HRP-439: hint the installation's currency, not a literal.
              placeholder={getDefaultSalaryCurrency()}
              disabled={disabled}
            />
          </div>
        </div>
        <div className="space-y-1">
          <Label htmlFor="division-select">{t("columnDivision")}</Label>
          <Select
            value={form.division_id ?? ""}
            onValueChange={(val) => setField("division_id", val || null)}
            disabled={disabled}
          >
            <SelectTrigger id="division-select" data-testid="vacancy-field-division">
              <SelectValue placeholder={t("vacancySelectDivision")}>
                {form.division_id
                  ? (divisions.find((d) => d.id === form.division_id)?.name ??
                    form.division_id)
                  : t("vacancySelectDivision")}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              {divisions.map((d) => (
                <SelectItem key={d.id} value={d.id}>
                  {d.name || d.id}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-1">
          <Label>{t("vacancyFieldSpecializations")}</Label>
          <MultiSelectFilter
            options={positionSpecOptions}
            value={form.specialization_ids}
            onChange={(next) => setField("specialization_ids", next)}
            placeholder={
              specDisabled
                ? t("vacancySelectPositionFirst")
                : t("vacancyPickSpecializations")
            }
            disabled={disabled || specDisabled}
            data-testid="vacancy-field-specializations-multiselect"
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="employment-select">
            {t("vacancyFieldEmploymentType")}
          </Label>
          <Select
            value={form.employment_type}
            onValueChange={(val) => setField("employment_type", val)}
            disabled={disabled}
          >
            <SelectTrigger
              id="employment-select"
              data-testid="vacancy-field-employment-type"
            >
              <SelectValue placeholder={t("vacancySelectType")}>
                {(() => {
                  const picked = employmentTypes.find(
                    (opt) => opt.value === form.employment_type,
                  );
                  return picked ? t(picked.labelKey) : t("vacancySelectType");
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
        <div className="space-y-1">
          <Label htmlFor="location-input">{t("candidateFieldLocation")}</Label>
          <Input
            id="location-input"
            value={form.location}
            onChange={(e) => setField("location", e.target.value)}
            placeholder={t("candidateFieldLocation")}
            disabled={disabled}
            data-testid="vacancy-field-location"
          />
        </div>

        <div className="space-y-1">
          <Label>{t("vacancyFieldGrades")}</Label>
          <MultiSelectFilter
            options={positionGradeOptions}
            value={form.grade_ids}
            onChange={(next) => setField("grade_ids", next)}
            placeholder={
              gradeDisabled
                ? t("vacancySelectPositionFirst")
                : t("vacancyPickGrades")
            }
            disabled={disabled || gradeDisabled}
            data-testid="vacancy-field-grades-multiselect"
          />
        </div>

        <div className="space-y-1">
          <Label htmlFor="hiring-manager-select">
            {t("vacancyFieldHiringManager")}
          </Label>
          <HiringManagerSelect
            id="hiring-manager-select"
            testId="vacancy-field-hiring-manager-select"
            value={form.hiring_manager_id}
            onChange={(next) => setField("hiring_manager_id", next)}
            disabled={disabled}
            fallbackLabel={hiringManagerFallback}
          />
        </div>
      </div>

      <div className="space-y-1">
        <Label htmlFor="description-input">{t("vacancyFieldDescription")}</Label>
        <Textarea
          id="description-input"
          value={form.description}
          onChange={(e) => setField("description", e.target.value)}
          rows={6}
          disabled={disabled}
          style={{ maxHeight: LONG_TEXTAREA_MAX_HEIGHT }}
          className="overflow-y-auto"
        />
      </div>

      <div className="space-y-1">
        <Label htmlFor="requirements-input">
          {t("vacancyFieldRequirements")}
        </Label>
        <Textarea
          id="requirements-input"
          value={form.requirements}
          onChange={(e) => setField("requirements", e.target.value)}
          rows={6}
          disabled={disabled}
          style={{ maxHeight: LONG_TEXTAREA_MAX_HEIGHT }}
          className="overflow-y-auto"
          data-testid="vacancy-field-requirements-input"
        />
      </div>

      <div className="space-y-1">
        <Label htmlFor="responsibilities-input">
          {t("vacancyFieldResponsibilities")}
        </Label>
        <Textarea
          id="responsibilities-input"
          value={form.responsibilities}
          onChange={(e) => setField("responsibilities", e.target.value)}
          rows={6}
          disabled={disabled}
          style={{ maxHeight: LONG_TEXTAREA_MAX_HEIGHT }}
          className="overflow-y-auto"
          data-testid="vacancy-field-responsibilities-input"
        />
      </div>

      <div className="space-y-1">
        <Label htmlFor="conditions-input">{t("vacancyFieldConditions")}</Label>
        <Textarea
          id="conditions-input"
          value={form.conditions}
          onChange={(e) => setField("conditions", e.target.value)}
          rows={6}
          disabled={disabled}
          style={{ maxHeight: LONG_TEXTAREA_MAX_HEIGHT }}
          className="overflow-y-auto"
          data-testid="vacancy-field-conditions-input"
        />
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <div className="space-y-1">
          <Label htmlFor="tasks-main-input">{t("vacancyFieldTasksMain")}</Label>
          <Textarea
            id="tasks-main-input"
            value={form.tasks_main}
            onChange={(e) => setField("tasks_main", e.target.value)}
            rows={6}
            disabled={disabled}
            style={{ maxHeight: LONG_TEXTAREA_MAX_HEIGHT }}
            className="overflow-y-auto"
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="tasks-additional-input">
            {t("vacancyFieldTasksAdditional")}
          </Label>
          <Textarea
            id="tasks-additional-input"
            value={form.tasks_additional}
            onChange={(e) => setField("tasks_additional", e.target.value)}
            rows={6}
            disabled={disabled}
            style={{ maxHeight: LONG_TEXTAREA_MAX_HEIGHT }}
            className="overflow-y-auto"
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="tasks-kpi-input">{t("vacancyFieldKpi")}</Label>
          <Textarea
            id="tasks-kpi-input"
            value={form.tasks_kpi}
            onChange={(e) => setField("tasks_kpi", e.target.value)}
            rows={6}
            disabled={disabled}
            style={{ maxHeight: LONG_TEXTAREA_MAX_HEIGHT }}
            className="overflow-y-auto"
          />
        </div>
      </div>
    </div>
  );
}
