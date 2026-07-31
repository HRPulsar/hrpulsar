"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { Paperclip, Trash2 } from "lucide-react";
import { ApiError, api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { MatrixContextPicker } from "@/components/competence-generation/MatrixContextPicker";
import {
  specializationAiApi,
  type MatrixGenerateInput,
} from "@/lib/api/specialization-ai";
import type { CompetenceGenerationSession } from "@/lib/api/competence-generation";
import { dictionaryItemLabel } from "@/lib/reference-labels";
import type { DictionaryItem } from "@/lib/types";
import {
  isActiveSessionConflict,
  type ActiveSessionRef,
} from "@/lib/active-ai-session-route";
import { ActiveSessionConflictDialog } from "@/components/competence-generation/ActiveSessionConflictDialog";

const ACCEPT = ".pdf,.docx,.xlsx,.xls,.rtf,.txt";
const DRAFT_KEY_PREFIX = "hrpulsar:ai-generate-draft:";

// HRP-97 extension: draft brief persisted in localStorage so that
// refreshing the page / closing and reopening the form / coming back
// after a cancelled session restores the last typed brief. Mirrors the
// "refinement fields expanded with the latest data" requirement that
// the original ticket implemented for the indicator RefinementPanel —
// here we apply the same UX to the matrix brief. Wipe triggers (Clear
// draft button, session cancel, session apply) are surfaced via the
// `clearAIGenerateDraft` helper so callers can purge state at the right
// moments without reaching into the form's internals.
interface DraftPayload {
  responsibilities: string;
  dailyTasks: string;
  weeklyTasks: string;
  kpi: string;
  requirementsText: string;
  selectedGradeIds: string[];
}

function draftStorageKey(key: string): string {
  return `${DRAFT_KEY_PREFIX}${key}`;
}

function loadDraft(key: string): DraftPayload | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(draftStorageKey(key));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<DraftPayload>;
    return {
      responsibilities: parsed.responsibilities ?? "",
      dailyTasks: parsed.dailyTasks ?? "",
      weeklyTasks: parsed.weeklyTasks ?? "",
      kpi: parsed.kpi ?? "",
      requirementsText: parsed.requirementsText ?? "",
      selectedGradeIds: Array.isArray(parsed.selectedGradeIds)
        ? parsed.selectedGradeIds
        : [],
    };
  } catch {
    return null;
  }
}

function saveDraft(key: string, payload: DraftPayload): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(draftStorageKey(key), JSON.stringify(payload));
  } catch {
    // Storage full / disabled — silently drop; brief stays in-memory.
  }
}

export function clearAIGenerateDraft(key: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(draftStorageKey(key));
  } catch {
    // best-effort
  }
}

interface Props {
  /** Target specialization. Optional when launching from a Position — the
   *  backend resolves it from `position.specialization_id`. */
  specId?: string;
  /** HRP-33: when provided, the matrix is scoped to this Position (apply
   *  collapses the result under one group named after the position). */
  positionId?: string;
  /** Grade IDs already attached to the specialization (or to the position's
   *  spec). Used to pre-select the multi-select so the user doesn't have to
   *  pick them again on refine flows. */
  initialGradeIds?: string[];
  /** Grade IDs that MUST stay selected — e.g. the position's own grade in
   *  the Position AI flow. Rendered as disabled checked entries to make
   *  intent obvious. */
  requiredGradeIds?: string[];
  testIdPrefix?: string;
  /** HRP-97 extension: when provided, the form persists its text inputs
   *  and grade selection to `localStorage` under this key so it can be
   *  restored on remount / refresh. Files cannot be serialised and stay
   *  in-memory only. Callers should pass a stable id (spec or position)
   *  and invoke `clearAIGenerateDraft(draftKey)` after Apply / Cancel
   *  to wipe the persisted brief. */
  draftKey?: string;
  /** HRP-119 AC2: when the matrix already has competences, surface the
   *  "Generate indicators for existing competences" checkbox so the user
   *  can ask the LLM to extend every existing competence with extra
   *  indicators in the same response. Hidden when the matrix is empty. */
  hasExistingCompetences?: boolean;
  onSessionCreated: (session: CompetenceGenerationSession) => void;
  disabled?: boolean;
}

export function AIGenerateForm({
  specId,
  positionId,
  initialGradeIds = [],
  requiredGradeIds = [],
  testIdPrefix = "ai-generate",
  draftKey,
  hasExistingCompetences = false,
  onSessionCreated,
  disabled,
}: Props) {
  const t = useTranslations("company");
  const tRef = useTranslations("reference");
  // Read the persisted draft once on mount so the initial useState values
  // carry the user's last brief. Subsequent updates flow through the
  // setter + the save effect below.
  const initialDraft = useMemo(
    () => (draftKey ? loadDraft(draftKey) : null),
    [draftKey],
  );

  const [responsibilities, setResponsibilities] = useState(
    initialDraft?.responsibilities ?? "",
  );
  const [dailyTasks, setDailyTasks] = useState(initialDraft?.dailyTasks ?? "");
  const [weeklyTasks, setWeeklyTasks] = useState(
    initialDraft?.weeklyTasks ?? "",
  );
  const [kpi, setKpi] = useState(initialDraft?.kpi ?? "");
  const [requirementsText, setRequirementsText] = useState(
    initialDraft?.requirementsText ?? "",
  );
  const [files, setFiles] = useState<File[]>([]);
  // HRP-119 AC2: opt-in flag; only visible when the matrix has competences.
  const [indicatorsForExisting, setIndicatorsForExisting] = useState(false);
  // HRP-159: preflight context picker — excludes set + free-form refinement.
  const [contextExcludes, setContextExcludes] = useState<Set<string>>(
    () => new Set(),
  );
  const [refinementPrompt, setRefinementPrompt] = useState("");
  const [submitting, setSubmitting] = useState(false);
  // HRP-168: surface a visible decision modal when the API returns 409
  // active_session_exists. The previous silent `window.location.href`
  // redirect made it look like nothing happened — a reported regression
  // where the page just "refreshed" on Start.
  const [conflictSession, setConflictSession] = useState<ActiveSessionRef | null>(
    null,
  );
  const fileInputRef = useRef<HTMLInputElement>(null);

  // HRP-57 P4 / P5: grades multi-select. Required for the brief — the
  // backend pre-creates pairs before the LLM runs so the matrix lands
  // against a real career ladder even on an otherwise empty spec.
  const [gradePool, setGradePool] = useState<DictionaryItem[]>([]);
  const [gradesLoading, setGradesLoading] = useState(false);
  const [selectedGradeIds, setSelectedGradeIds] = useState<string[]>(() => [
    ...new Set([
      ...requiredGradeIds,
      ...(initialDraft?.selectedGradeIds ?? initialGradeIds),
    ]),
  ]);

  // HRP-97 extension: persist the brief on every change. Throttling via
  // a microtask isn't necessary — localStorage writes are cheap and
  // typing-rate writes are well within budget; the effect fires after
  // React batches the render so we never write mid-input.
  useEffect(() => {
    if (!draftKey) return;
    saveDraft(draftKey, {
      responsibilities,
      dailyTasks,
      weeklyTasks,
      kpi,
      requirementsText,
      selectedGradeIds,
    });
  }, [
    draftKey,
    responsibilities,
    dailyTasks,
    weeklyTasks,
    kpi,
    requirementsText,
    selectedGradeIds,
  ]);
  // Keep selection synced when the parent first hydrates the props (page
  // mount races with the form rendering empty). When a draft was loaded
  // we trust its grade selection and only merge in `requiredGradeIds`
  // (they're mandatory for the current flow and the user can't untick
  // them anyway).
  const hasDraft = initialDraft !== null;
  useEffect(() => {
    setSelectedGradeIds((prev) => {
      const merged = new Set(prev);
      for (const id of requiredGradeIds) merged.add(id);
      if (!hasDraft) {
        for (const id of initialGradeIds) merged.add(id);
      }
      const next = Array.from(merged);
      const prevSet = new Set(prev);
      const same =
        next.length === prev.length && next.every((id) => prevSet.has(id));
      return same ? prev : next;
    });
  }, [hasDraft, initialGradeIds, requiredGradeIds]);

  function clearDraft() {
    if (draftKey) clearAIGenerateDraft(draftKey);
    setResponsibilities("");
    setDailyTasks("");
    setWeeklyTasks("");
    setKpi("");
    setRequirementsText("");
    setFiles([]);
    setSelectedGradeIds([...new Set(requiredGradeIds)]);
    setContextExcludes(new Set());
    setRefinementPrompt("");
  }

  const hasBriefContent =
    responsibilities.trim().length > 0 ||
    dailyTasks.trim().length > 0 ||
    weeklyTasks.trim().length > 0 ||
    kpi.trim().length > 0 ||
    requirementsText.trim().length > 0 ||
    files.length > 0 ||
    selectedGradeIds.filter((id) => !requiredGradeIds.includes(id)).length > 0 ||
    contextExcludes.size > 0 ||
    refinementPrompt.trim().length > 0;

  useEffect(() => {
    let cancelled = false;
    setGradesLoading(true);
    api
      .get<DictionaryItem[]>("/dictionaries/grade")
      .then((items) => {
        if (cancelled) return;
        setGradePool(
          items
            .filter((g) => g.is_active)
            .sort(
              (a, b) =>
                // Raw-title tie-break: sort_index is the real order; ties
                // only occur between tenant rows, whose labels render
                // verbatim anyway (HRP-479).
                a.sort_index - b.sort_index || a.title.localeCompare(b.title),
            ),
        );
      })
      .catch((err) => {
        if (!cancelled) {
          toast.error(
            err instanceof Error ? err.message : t("toastGradesLoadFailed"),
          );
        }
      })
      .finally(() => {
        if (!cancelled) setGradesLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [t]);

  const requiredSet = useMemo(
    () => new Set(requiredGradeIds),
    [requiredGradeIds],
  );

  function toggleGrade(id: string) {
    if (requiredSet.has(id)) return;
    setSelectedGradeIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  }

  function addFiles(list: FileList | null) {
    if (!list) return;
    const next = [...files];
    for (const f of Array.from(list)) {
      if (next.find((x) => x.name === f.name && x.size === f.size)) continue;
      next.push(f);
    }
    setFiles(next);
  }

  function removeFile(idx: number) {
    setFiles(files.filter((_, i) => i !== idx));
  }

  async function submitGeneration() {
    if (submitting) return;
    if (selectedGradeIds.length === 0) {
      toast.error(t("errorPickGrade"));
      return;
    }
    setSubmitting(true);
    try {
      const input: MatrixGenerateInput = {
        target_id: specId,
        position_id: positionId,
        grade_ids: selectedGradeIds,
        responsibilities: responsibilities.trim() || undefined,
        daily_tasks: dailyTasks.trim() || undefined,
        weekly_tasks: weeklyTasks.trim() || undefined,
        kpi: kpi.trim() || undefined,
        requirements_text: requirementsText.trim() || undefined,
        indicators_for_existing:
          hasExistingCompetences && indicatorsForExisting ? true : undefined,
        context_excludes:
          contextExcludes.size > 0 ? Array.from(contextExcludes) : undefined,
        refinement_prompt: refinementPrompt.trim() || undefined,
        files,
      };
      const session = await specializationAiApi.start(input);
      onSessionCreated(session);
      toast.success(t("toastGenerationStarted"));
    } catch (err) {
      // HRP-168: a 409 with `error_code === "active_session_exists"` used
      // to silently `window.location.href` the user away, which read as
      // "the page just refreshed and Start did nothing." Show a visible
      // dialog instead so the user can either jump to the live session
      // or cancel it and retry.
      if (err instanceof ApiError && err.status === 409) {
        const detail = err.detail;
        if (isActiveSessionConflict(detail) && detail.session) {
          setConflictSession(detail.session);
          return;
        }
      }
      toast.error(
        err instanceof Error ? err.message : t("toastGenerationStartFailed"),
      );
    } finally {
      setSubmitting(false);
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    await submitGeneration();
  }

  return (
    <>
    <ActiveSessionConflictDialog
      session={conflictSession}
      onClose={() => setConflictSession(null)}
      onRetry={() => {
        setConflictSession(null);
        void submitGeneration();
      }}
    />
    <form
      onSubmit={handleSubmit}
      data-testid={`${testIdPrefix}-form`}
      className="space-y-4 rounded-md border bg-background p-4"
    >
      <div className="space-y-2">
        <label className="text-sm font-medium">
          {t("grades")} <span className="text-destructive">*</span>
        </label>
        <p className="text-xs text-muted-foreground">{t("gradesFormHint")}</p>
        {gradesLoading && gradePool.length === 0 ? (
          <p className="text-xs text-muted-foreground">{t("loadingGrades")}</p>
        ) : gradePool.length === 0 ? (
          <p
            data-testid={`${testIdPrefix}-grades-empty`}
            className="rounded border bg-muted/30 px-3 py-2 text-xs text-muted-foreground"
          >
            {t("noGradesForAi")}
          </p>
        ) : (
          <div
            data-testid={`${testIdPrefix}-grades-list`}
            className="flex flex-wrap gap-2"
          >
            {gradePool.map((g) => {
              const checked = selectedGradeIds.includes(g.id);
              const isRequired = requiredSet.has(g.id);
              return (
                <label
                  key={g.id}
                  data-testid={`${testIdPrefix}-grade-${g.id}`}
                  className={
                    "flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs " +
                    (checked
                      ? "border-primary bg-primary/10 text-foreground"
                      : "border-input bg-background text-muted-foreground hover:text-foreground")
                  }
                >
                  <Checkbox
                    checked={checked}
                    disabled={isRequired}
                    onCheckedChange={() => toggleGrade(g.id)}
                  />
                  <span>
                    {dictionaryItemLabel(tRef, g)}
                    {isRequired ? t("gradeRequiredSuffix") : ""}
                  </span>
                </label>
              );
            })}
          </div>
        )}
        <p
          data-testid={`${testIdPrefix}-grades-count`}
          className="text-xs text-muted-foreground"
        >
          {t("selectedCount", { count: selectedGradeIds.length })}
        </p>
      </div>

      {hasExistingCompetences && (
        <label
          data-testid={`${testIdPrefix}-indicators-for-existing`}
          className="flex items-start gap-2 rounded-md border bg-muted/30 px-3 py-2"
        >
          <Checkbox
            checked={indicatorsForExisting}
            onCheckedChange={(v) => setIndicatorsForExisting(Boolean(v))}
            className="mt-0.5"
          />
          <span className="text-sm">
            <span className="font-medium">
              {t("indicatorsForExisting")}
            </span>
            <span className="block text-xs text-muted-foreground">
              {t("indicatorsForExistingHint")}
            </span>
          </span>
        </label>
      )}

      {specId && (
        <MatrixContextPicker
          targetId={specId}
          excludes={contextExcludes}
          onChange={setContextExcludes}
        />
      )}

      <div className="space-y-1">
        <label
          htmlFor={`${testIdPrefix}-refinement-prompt`}
          className="text-sm font-medium"
        >
          {t("refinementOptional")}
        </label>
        <p className="text-xs text-muted-foreground">{t("refinementHint")}</p>
        <textarea
          id={`${testIdPrefix}-refinement-prompt`}
          value={refinementPrompt}
          onChange={(e) => setRefinementPrompt(e.target.value)}
          rows={3}
          data-testid={`${testIdPrefix}-refinement-prompt`}
          className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
        />
      </div>

      <Field
        label={t("responsibilities")}
        testId={`${testIdPrefix}-responsibilities`}
        value={responsibilities}
        onChange={setResponsibilities}
      />
      <Field
        label={t("dailyTasks")}
        testId={`${testIdPrefix}-daily-tasks`}
        value={dailyTasks}
        onChange={setDailyTasks}
      />
      <Field
        label={t("weeklyTasks")}
        testId={`${testIdPrefix}-weekly-tasks`}
        value={weeklyTasks}
        onChange={setWeeklyTasks}
      />
      <Field
        label={t("kpi")}
        testId={`${testIdPrefix}-kpi`}
        value={kpi}
        onChange={setKpi}
      />
      <Field
        label={t("formalRequirements")}
        testId={`${testIdPrefix}-requirements-text`}
        value={requirementsText}
        onChange={setRequirementsText}
      />

      <div className="space-y-2">
        <label className="text-sm font-medium">{t("referenceFiles")}</label>
        <p className="text-xs text-muted-foreground">
          {t("referenceFilesHint")}
        </p>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept={ACCEPT}
          data-testid={`${testIdPrefix}-file-input`}
          onChange={(e) => {
            addFiles(e.target.files);
            if (fileInputRef.current) fileInputRef.current.value = "";
          }}
          className="sr-only"
        />
        <div className="flex items-center gap-3">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => fileInputRef.current?.click()}
            data-testid={`${testIdPrefix}-file-pick`}
          >
            <Paperclip className="mr-2 h-4 w-4" />
            {t("chooseFiles")}
          </Button>
          <span
            className="text-xs text-muted-foreground"
            data-testid={`${testIdPrefix}-file-count`}
          >
            {files.length === 0
              ? t("noFilesChosen")
              : t("filesSelected", { count: files.length })}
          </span>
        </div>
        {files.length > 0 && (
          <ul
            data-testid={`${testIdPrefix}-file-list`}
            className="space-y-1 text-sm"
          >
            {files.map((f, idx) => (
              <li
                key={`${f.name}-${idx}`}
                className="flex items-center justify-between rounded border bg-muted px-2 py-1"
              >
                <span>
                  {f.name}{" "}
                  <span className="text-xs text-muted-foreground">
                    ({(f.size / 1024).toFixed(1)} KB)
                  </span>
                </span>
                <button
                  type="button"
                  onClick={() => removeFile(idx)}
                  className="text-xs text-destructive hover:underline"
                  data-testid={`${testIdPrefix}-remove-file-${idx}`}
                >
                  {t("remove")}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="flex items-center justify-end gap-2">
        {hasBriefContent && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={clearDraft}
            disabled={submitting}
            data-testid={`${testIdPrefix}-clear-draft`}
          >
            <Trash2 className="mr-1 h-4 w-4" />
            {t("clearDraft")}
          </Button>
        )}
        <button
          type="submit"
          disabled={submitting || disabled || selectedGradeIds.length === 0}
          data-testid={`${testIdPrefix}-submit`}
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          {submitting ? t("starting") : t("startAiGeneration")}
        </button>
      </div>
    </form>
    </>
  );
}

function Field({
  label,
  testId,
  value,
  onChange,
}: {
  label: string;
  testId: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="space-y-1">
      <label className="text-sm font-medium">{label}</label>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={3}
        data-testid={testId}
        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
      />
    </div>
  );
}
