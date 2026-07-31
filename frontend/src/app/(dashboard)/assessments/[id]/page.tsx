"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { EmployeeSummaryLine } from "@/components/employee/employee-summary-line";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/context/auth-context";
import { usePermissions } from "@/hooks/use-permissions";
import { useCompetenceTree } from "@/hooks/use-competence-tree";
import { inlineEditKeys, useInlineEdit } from "@/hooks/use-inline-edit";
import type { AnswerScaleDeleteResult, AnswerScaleDetail, AssessmentDetail, Competence, CompetenceDetail, CompetenceGroupTree, CPAComparisonResult, Employee, EmployeeList } from "@/lib/types";
import {
  answerScaleDescription,
  answerScaleLabel,
  assessmentStatusTitle,
  assessmentTypeTitle,
  scaleLevelLabel,
  scaleOptionDescription,
  scaleOptionLabel,
  skillLevelLabel,
} from "@/lib/reference-labels";
import { scaleOptionSuffix } from "@/lib/scale-option-label";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { DatePicker } from "@/components/ui/date-picker";
import { Label } from "@/components/ui/label";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { RadioGroup, RadioItem } from "@/components/ui/radio";
import {
  Sheet,
  SheetContent,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

import { toast } from "sonner";
import { ArrowLeft, ArrowRightLeft, Check, Info, MoreHorizontal, Pencil, Plus, Send, Sparkles, Star, X } from "lucide-react";

import { AssessmentDetailedResults } from "@/components/assessment/assessment-detailed-results";
import { AssessmentRecommendationCard } from "@/components/assessment/assessment-recommendation-card";
import { CriteriaSheet } from "@/components/assessment/criteria-sheet";
import { isPastDeadline, todayLocalISO } from "@/lib/deadline";
import { formatDate } from "@/lib/date-format";
import { CriteriaSummary } from "@/components/assessment/criteria-summary";
import { ScaleEditorSheet } from "@/components/assessment/scale-editor-sheet";
import { ScalePreviewDialog } from "@/components/assessment/scale-preview-dialog";

import {
  ASSESSMENT_STATUS_COLORS as statusColors,
  ASSESSMENT_STATUS_FLOW as statusFlow,
  ASSESSMENT_TERMINAL_STATUSES as TERMINAL_STATUSES,
} from "@/lib/assessment-status";
import { BADGE_COLOR } from "@/lib/badge-tones";

const roleColors: Record<string, string> = {
  self: BADGE_COLOR.blue,
  manager: BADGE_COLOR.purple,
  peer: BADGE_COLOR.cyan,
  subordinate: BADGE_COLOR.orange,
};

// HRP-190 / HRP-192: the Details action buttons read as verbs ("send",
// "cancel"); keys live in the `assessments` namespace, unknown codes fall
// back to the raw code with underscores turned into spaces.
const STATUS_ACTION_KEYS: Record<string, string> = {
  sent: "actionSend",
  cancelled: "actionCancel",
  on_review: "actionOnReview",
  done: "actionDone",
};

function flattenCompetences(groups: CompetenceGroupTree[]): Competence[] {
  const result: Competence[] = [];
  for (const g of groups) {
    result.push(...g.competences);
    if (g.children.length > 0) result.push(...flattenCompetences(g.children));
  }
  return result;
}

export default function AssessmentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const t = useTranslations("assessments");
  const tc = useTranslations("common");
  const tRef = useTranslations("reference");
  const { user: currentUser } = useAuth();
  const { canManage, roles } = usePermissions();
  // HRP-154: Platform admin sits outside `canManage` (which only covers
  // admin + manager), but the Detailed results block is meant to be
  // visible to them too — backend RBAC already enforces this; the gate
  // here just keeps the network call from firing for Employees.
  const canViewDetailedResults =
    canManage || roles.includes("platform_admin");
  // HRP-243: an Employee-only caller sees the Results card only when
  // they are the assessee (the `self` participant) AND the assessment is
  // Done. Peers / subordinates never see results for assessments they
  // merely participated in. The backend mirrors this — it returns an
  // empty `results` array — but we also gate render-side so the
  // condition is explicit in the UI and trivial to test.
  const isPrivileged = canManage || roles.includes("platform_admin");
  const [assessment, setAssessment] = useState<AssessmentDetail | null>(null);
  const [employee, setEmployee] = useState<Employee | null>(null);
  const { tree: competenceTree } = useCompetenceTree();
  const allCompetences = useMemo(
    () => flattenCompetences(competenceTree),
    [competenceTree],
  );
  const [answerScales, setAnswerScales] = useState<AnswerScaleDetail[]>([]);
  const [loading, setLoading] = useState(true);

  // Add participant
  const [partOpen, setPartOpen] = useState(false);
  const [partForm, setPartForm] = useState({ employee_id: "", role: "peer" });
  const [employees, setEmployees] = useState<Employee[]>([]);

  // Criteria sheet
  const [criteriaOpen, setCriteriaOpen] = useState(false);

  // Evaluation form (HRP-146: Sheet with auto-save + draft rehydrate)
  const [evalOpen, setEvalOpen] = useState(false);
  const [evalParticipantId, setEvalParticipantId] = useState("");
  const [evalIndicators, setEvalIndicators] = useState<{ id: string; title: string; competence: string }[]>([]);
  const [evalAnswers, setEvalAnswers] = useState<
    Record<string, { answer_option_id: string | null; comment: string }>
  >({});
  const [evalLoading, setEvalLoading] = useState(false);
  // Pending debounced comment saves keyed by indicator id; cleared on
  // close so a stale debounce can't smuggle the wrong text into the
  // wrong assessment.
  const commentSaveTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  // Indicators that failed validation on the last submit attempt (Bug #6).
  const [evalMissing, setEvalMissing] = useState<Set<string>>(new Set());

  // HRP-42: read-only preview of the questionnaire (criteria + scale → questions)
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewGroups, setPreviewGroups] = useState<
    {
      competence_id: string;
      competence_title: string;
      skill_level_title: string | null;
      indicators: { id: string; title: string; skill_level_title: string | null }[];
    }[]
  >([]);

  // Inline edit (Bug #11): title and deadline on a non-terminal assessment.
  // HRP-110: state shape comes from the shared `useInlineEdit` hook; save
  // logic stays on the page because the API and validation differ from
  // positions (`api.patch` vs `savePatch`, deadline past-guard, etc).
  const titleEdit = useInlineEdit<string>(() => "");
  const deadlineEdit = useInlineEdit<string>(() => "");

  // Calibration
  // HRP-185: per-competence Calibrate state removed — replaced by the
  // per-indicator Total picker inside Detailed results.

  // HRP-90: per-level results popup
  const [perLevelOpen, setPerLevelOpen] = useState(false);
  const [perLevelTitle, setPerLevelTitle] = useState<string>("");
  const [perLevelRows, setPerLevelRows] = useState<
    {
      skill_level_id: string;
      skill_level_title: string | null;
      skill_level_i18n_key?: string | null;
      sort_index: number;
      percent: number | null;
    }[]
  >([]);

  // Rating scale picker
  const [scaleOpen, setScaleOpen] = useState(false);
  const [scalePick, setScalePick] = useState<string>("");
  const [scaleEditorOpen, setScaleEditorOpen] = useState(false);
  const [scaleEditorMode, setScaleEditorMode] = useState<"create" | "edit">("create");
  const [scaleEditorInitial, setScaleEditorInitial] = useState<AnswerScaleDetail | null>(null);
  const [scalePreviewOpen, setScalePreviewOpen] = useState(false);
  const [scalePreviewId, setScalePreviewId] = useState<string | null>(null);
  const [scaleDeleteOpen, setScaleDeleteOpen] = useState(false);
  const [scaleDeleteId, setScaleDeleteId] = useState<string | null>(null);

  // CPA comparison
  const [cpaCompOpen, setCpaCompOpen] = useState(false);
  const [cpaCompId2, setCpaCompId2] = useState("");
  const [cpaComparison, setCpaComparison] = useState<CPAComparisonResult | null>(null);
  const [cpaCompLoading, setCpaCompLoading] = useState(false);

  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      const [detail, scales] = await Promise.all([
        api.get<AssessmentDetail>(`/assessments/${id}`),
        api.get<AnswerScaleDetail[]>("/answer-scales"),
      ]);
      setAssessment(detail);
      setAnswerScales(scales);
      // Load employee info
      try {
        const emp = await api.get<Employee>(`/employees/${detail.employee_id}`);
        setEmployee(emp);
      } catch {
        // ignore
      }
    } catch (err) {
      // HRP-40: 404 is the normal not-visible-to-caller case (Draft for employee,
      // out-of-scope detail) — render the placeholder, don't surface a toast.
      if (!(err instanceof ApiError && err.status === 404)) {
        toast.error(t("errorLoadAssessment"));
      }
    } finally {
      setLoading(false);
    }
  }, [id, t]);

  useEffect(() => {
    load();
  }, [load]);

  async function changeStatus(status: string) {
    // Bug #9: pre-check Draft → Sent so the user gets immediate feedback
    // instead of a 400 round-trip. Backend enforces the same rule.
    if (status === "sent" && assessment) {
      if (!assessment.criteria_type) {
        toast.error(t("errorCriteriaNotSelected"));
        return;
      }
      if (!assessment.scale_id) {
        toast.error(t("errorScaleNotSelected"));
        return;
      }
    }
    setSaving(true);
    try {
      await api.post(`/assessments/${id}/status`, { status_code: status });
      toast.success(t("toastStatusChanged", { status }));
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("errorStatusChangeFailed"));
    } finally {
      setSaving(false);
    }
  }

  async function saveTitle() {
    const next = titleEdit.draft.trim();
    if (!next) {
      toast.error(t("errorTitleEmpty"));
      return;
    }
    setSaving(true);
    try {
      await api.patch(`/assessments/${id}`, { title: next });
      titleEdit.close();
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("errorTitleUpdateFailed"));
    } finally {
      setSaving(false);
    }
  }

  async function saveDeadline() {
    // No-op if the operator opened the editor and saved without changing
    // anything — important for assessments whose existing deadline is
    // already in the past (the past-guard would otherwise block save).
    const original = assessment?.ended_at ? assessment.ended_at.slice(0, 10) : "";
    if (deadlineEdit.draft === original) {
      deadlineEdit.close();
      return;
    }
    if (isPastDeadline(deadlineEdit.draft)) {
      toast.error(t("errorDeadlineInPast"));
      return;
    }
    setSaving(true);
    try {
      // Treat the picked date as the user's local end-of-day so a deadline
      // chosen in UTC+3 doesn't roll forward to "tomorrow" on the server.
      // Empty input → explicit null clears the deadline (PATCH tri-state).
      let iso: string | null = null;
      if (deadlineEdit.draft) {
        const [y, m, d] = deadlineEdit.draft.split("-").map(Number);
        iso = new Date(y, m - 1, d, 23, 59, 59).toISOString();
      }
      await api.patch(`/assessments/${id}`, { ended_at: iso });
      deadlineEdit.close();
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("errorDeadlineUpdateFailed"));
    } finally {
      setSaving(false);
    }
  }

  async function addParticipant() {
    setSaving(true);
    try {
      await api.post(`/assessments/${id}/participants`, partForm);
      toast.success(t("toastParticipantAdded"));
      setPartOpen(false);
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("errorParticipantAddFailed"));
    } finally {
      setSaving(false);
    }
  }

  async function saveCriteria(payload: import("@/lib/types").CriteriaUpdate) {
    await api.put(`/assessments/${id}/criteria`, payload);
    toast.success(t("toastCriteriaSaved"));
    await load();
  }

  // Evaluation
  async function openEvaluation(participantId: string) {
    setEvalParticipantId(participantId);
    setEvalLoading(true);
    setEvalOpen(true);
    try {
      const indicators: { id: string; title: string; competence: string }[] = [];
      if (assessment) {
        // HRP-43: pass skill_level_id so the questionnaire only shows
        // indicators of the chosen level and every level below it. Falls back
        // to all indicators when a competence has no level (legacy criteria).
        const items = assessment.competences?.length
          ? assessment.competences.map((c) => ({
              id: c.competence_id,
              skill_level_id: c.skill_level_id ?? null,
            }))
          : assessment.competence_ids.map((id) => ({
              id,
              skill_level_id: null,
            }));
        for (const item of items) {
          const url = item.skill_level_id
            ? `/competences/${item.id}?skill_level_id=${item.skill_level_id}`
            : `/competences/${item.id}`;
          const detail = await api.get<CompetenceDetail>(url);
          for (const ind of detail.indicators) {
            indicators.push({ id: ind.id, title: ind.title, competence: detail.title });
          }
        }
      }
      setEvalIndicators(indicators);
      // HRP-146: rehydrate previously saved answers so the Sheet reopens
      // with the participant's current draft. ``/my-answers`` returns
      // whatever the caller has saved so far (empty list for fresh
      // assessments), keyed by indicator id.
      const baseAnswers = Object.fromEntries(
        indicators.map((i) => [
          i.id,
          { answer_option_id: null as string | null, comment: "" },
        ]),
      );
      try {
        const draft = await api.get<{
          participant_id: string | null;
          answers: {
            indicator_id: string;
            answer_option_id: string | null;
            score: number | null;
            comment: string | null;
          }[];
        }>(`/assessments/${id}/my-answers`);
        for (const row of draft.answers) {
          if (!baseAnswers[row.indicator_id]) continue;
          baseAnswers[row.indicator_id] = {
            answer_option_id: row.answer_option_id,
            comment: row.comment ?? "",
          };
        }
      } catch {
        // Non-fatal — the Sheet still opens with empty draft.
      }
      setEvalAnswers(baseAnswers);
    } catch {
      toast.error(t("errorLoadIndicators"));
      setEvalOpen(false);
    } finally {
      setEvalLoading(false);
    }
  }

  // HRP-146: upsert one answer row (silently — toast errors come only
  // from the final Submit). The backend now upserts on
  // (assessment, participant, indicator), so this is idempotent.
  const autosaveAnswer = useCallback(
    async (
      indicatorId: string,
      answer: { answer_option_id: string | null; comment: string },
      participantId: string,
    ) => {
      if (!answer.answer_option_id && !answer.comment) return;
      try {
        await api.post(`/assessments/${id}/answers`, {
          participant_id: participantId,
          indicator_id: indicatorId,
          answer_option_id: answer.answer_option_id,
          comment: answer.comment || null,
        });
      } catch (err) {
        // Surface only network-level failures; option flips are visible
        // immediately so the user can retry by re-selecting.
        if (err instanceof Error) {
          console.warn("Failed to autosave answer", err.message);
        }
      }
    },
    [id],
  );

  function selectAnswerOption(indicatorId: string, optionId: string) {
    if (!evalParticipantId) return;
    setEvalAnswers((prev) => {
      const next = {
        ...prev,
        [indicatorId]: {
          answer_option_id: optionId,
          comment: prev[indicatorId]?.comment ?? "",
        },
      };
      void autosaveAnswer(indicatorId, next[indicatorId], evalParticipantId);
      // Clear the "missing" flag for the indicator the user just answered.
      setEvalMissing((miss) => {
        if (!miss.has(indicatorId)) return miss;
        const m = new Set(miss);
        m.delete(indicatorId);
        return m;
      });
      return next;
    });
  }

  function updateAnswerComment(indicatorId: string, comment: string) {
    if (!evalParticipantId) return;
    setEvalAnswers((prev) => {
      const next = {
        ...prev,
        [indicatorId]: {
          answer_option_id: prev[indicatorId]?.answer_option_id ?? null,
          comment,
        },
      };
      const participantId = evalParticipantId;
      // Debounce comment saves so we don't hammer the backend with
      // every keystroke — but still save without requiring a Submit.
      if (commentSaveTimers.current[indicatorId]) {
        clearTimeout(commentSaveTimers.current[indicatorId]);
      }
      commentSaveTimers.current[indicatorId] = setTimeout(() => {
        void autosaveAnswer(indicatorId, next[indicatorId], participantId);
        delete commentSaveTimers.current[indicatorId];
      }, 600);
      return next;
    });
  }

  function flushPendingCommentSaves() {
    const timers = commentSaveTimers.current;
    for (const [indicatorId, timer] of Object.entries(timers)) {
      clearTimeout(timer);
      const answer = evalAnswers[indicatorId];
      if (answer && evalParticipantId) {
        void autosaveAnswer(indicatorId, answer, evalParticipantId);
      }
    }
    commentSaveTimers.current = {};
  }

  async function submitEvaluation() {
    // Bug #6: highlight unanswered indicators instead of silently
    // skipping them. With HRP-146 the answers are already autosaved
    // via the Sheet, so Submit just flushes pending comment debounces
    // and verifies every indicator carries a choice before closing.
    const missing = evalIndicators
      .filter((ind) => !evalAnswers[ind.id]?.answer_option_id)
      .map((ind) => ind.id);
    if (missing.length > 0) {
      setEvalMissing(new Set(missing));
      toast.error(t("errorAnswerAll"));
      return;
    }
    setEvalMissing(new Set());

    setSaving(true);
    try {
      flushPendingCommentSaves();
      // Final pass: re-upsert every answer to make sure debounced
      // comments and freshly-picked options are persisted before we
      // close the Sheet, even if the user clicked Submit faster than
      // a 600ms debounce.
      for (const [indicatorId, answer] of Object.entries(evalAnswers)) {
        await api.post(`/assessments/${id}/answers`, {
          participant_id: evalParticipantId,
          indicator_id: indicatorId,
          answer_option_id: answer.answer_option_id,
          comment: answer.comment || null,
        });
      }
      toast.success(t("toastAnswersSubmitted"));
      setEvalOpen(false);
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("errorSubmitFailed"));
    } finally {
      setSaving(false);
    }
  }

  async function openPreview() {
    if (!assessment) return;
    setPreviewLoading(true);
    setPreviewOpen(true);
    try {
      // HRP-42: same endpoint and skill-level filter as the participant
      // questionnaire (HRP-43) — preview must match what reviewers will see.
      const items = assessment.competences?.length
        ? assessment.competences.map((c) => ({
            competence_id: c.competence_id,
            competence_title: c.competence_title,
            skill_level_id: c.skill_level_id ?? null,
            skill_level_title: c.skill_level_title,
          }))
        : assessment.competence_ids.map((cid) => ({
            competence_id: cid,
            competence_title: "",
            skill_level_id: null as string | null,
            skill_level_title: null,
          }));
      const groups: typeof previewGroups = [];
      for (const item of items) {
        const url = item.skill_level_id
          ? `/competences/${item.competence_id}?skill_level_id=${item.skill_level_id}`
          : `/competences/${item.competence_id}`;
        const detail = await api.get<CompetenceDetail>(url);
        groups.push({
          competence_id: item.competence_id,
          competence_title: item.competence_title || detail.title,
          skill_level_title: item.skill_level_title,
          indicators: detail.indicators.map((ind) => ({
            id: ind.id,
            title: ind.title,
            skill_level_title: ind.skill_level_title,
          })),
        });
      }
      setPreviewGroups(groups);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("errorLoadPreview"));
      setPreviewOpen(false);
    } finally {
      setPreviewLoading(false);
    }
  }

  // HRP-185: per-competence calibration was removed in favour of the
  // per-indicator Total picker inside Detailed results. The helpers used
  // by the old Dialog (openCalibration / submitCalibration) are gone;
  // the Dialog itself stays in the JSX as dead state until the cleanup
  // catches up.

  function openScalePicker() {
    if (!assessment) return;
    setScalePick(assessment.scale_id ?? "");
    setScaleOpen(true);
  }

  async function saveScale() {
    setSaving(true);
    try {
      await api.put(`/assessments/${id}/scale`, {
        scale_id: scalePick || null,
      });
      toast.success(t("toastRatingScaleUpdated"));
      setScaleOpen(false);
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("errorScaleSaveFailed"));
    } finally {
      setSaving(false);
    }
  }

  function openScalePreview(scaleId: string) {
    setScalePreviewId(scaleId);
    setScalePreviewOpen(true);
  }

  function openScaleCreator() {
    setScaleEditorMode("create");
    setScaleEditorInitial(null);
    setScaleEditorOpen(true);
  }

  function openScaleEditor(scale: AnswerScaleDetail) {
    setScaleEditorMode("edit");
    setScaleEditorInitial(scale);
    setScaleEditorOpen(true);
  }

  async function reloadScales(): Promise<AnswerScaleDetail[]> {
    const scales = await api.get<AnswerScaleDetail[]>("/answer-scales");
    setAnswerScales(scales);
    return scales;
  }

  function handleScaleSaved(saved: AnswerScaleDetail) {
    setAnswerScales((prev) => {
      const idx = prev.findIndex((s) => s.id === saved.id);
      if (idx >= 0) {
        const copy = [...prev];
        copy[idx] = saved;
        return copy;
      }
      return [...prev, saved];
    });
    setScalePick(saved.id);
  }

  function requestScaleDelete(scaleId: string) {
    setScaleDeleteId(scaleId);
    setScaleDeleteOpen(true);
  }

  async function confirmScaleDelete() {
    if (!scaleDeleteId) return;
    try {
      const result = await api.delete<AnswerScaleDeleteResult>(
        `/answer-scales/${scaleDeleteId}`,
      );
      toast.success(
        result.reassigned_drafts > 0
          ? t("toastScaleDeletedReassigned", {
              count: result.reassigned_drafts,
            })
          : t("toastScaleDeleted"),
      );
      const fresh = await reloadScales();
      if (assessment?.scale_id === scaleDeleteId) {
        await load();
      }
      if (scalePick === scaleDeleteId) {
        setScalePick(fresh.find((s) => s.is_default)?.id ?? "");
      }
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("errorScaleDeleteFailed"),
      );
    } finally {
      setScaleDeleteId(null);
    }
  }

  async function fetchCpaComparison() {
    if (!assessment?.cpa_id || !cpaCompId2.trim()) return;
    setCpaCompLoading(true);
    try {
      const result = await api.get<CPAComparisonResult>(
        `/analytics/cpa-comparison?cpa_id_1=${assessment.cpa_id}&cpa_id_2=${cpaCompId2.trim()}`,
      );
      setCpaComparison(result);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("errorLoadComparison"));
    } finally {
      setCpaCompLoading(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">
        {tc("loading")}
      </div>
    );
  }

  if (!assessment) {
    return (
      <div className="space-y-4">
        <Button variant="ghost" size="sm" render={<Link href="/assessments" />}>
          <ArrowLeft className="mr-1 h-4 w-4" />
          {t("backToAssessments")}
        </Button>
        <div className="py-12 text-center text-muted-foreground">
          {t("assessmentNotFound")}
        </div>
      </div>
    );
  }

  const nextStatuses = statusFlow[assessment.status_code] || [];
  const isTerminal = TERMINAL_STATUSES.has(assessment.status_code);
  // Past-guard skips when the draft matches the already-saved deadline so an
  // operator can re-open the editor on a legacy past deadline without being
  // locked out of saving the *same* value back.
  const existingDeadlineDate = assessment.ended_at
    ? assessment.ended_at.slice(0, 10)
    : "";
  const deadlineDraftIsPast =
    deadlineEdit.draft !== existingDeadlineDate &&
    isPastDeadline(deadlineEdit.draft);
  // Criteria + scale are locked the moment the assessment leaves draft —
  // mirrors the backend's _assert_*_editable guards (HRP-36).
  const isDraft = assessment.status_code === "draft";
  // Children of a mass assessment inherit criteria/scale from their group
  // (Bug #2): individual edit must be hidden.
  const isGroupChild = !!assessment.group_id;
  const evaluateeUserId = employee?.user_id;
  const hasManagerParticipant = assessment.participants.some(
    (p) => p.role === "manager",
  );
  // For 180, allow manual Add only if the manager auto-assignment didn't fire
  // (e.g., the employee has no division manager). Self is always fully auto.
  const canAddParticipant =
    canManage &&
    !isTerminal &&
    assessment.type_code !== "self" &&
    (assessment.type_code !== "180" || !hasManagerParticipant);
  // After Sent, scale_id points to a snapshot that's not in the picker list,
  // so we read the scale embedded in the detail response (HRP-11).
  const scale =
    assessment.scale ?? answerScales.find((s) => s.id === assessment.scale_id);
  const myPendingParticipants = assessment.participants.filter(
    (p) => p.user_id === currentUser?.id && !p.is_completed,
  );
  const myFirstPending = myPendingParticipants[0];
  // HRP-104: Take this assessment is hidden in Draft — the assessment is not
  // running yet, so participants can't (and shouldn't) start answering.
  // Gates BOTH the main `Take this assessment` button below and the per-row
  // Evaluate action in the participant table, so the Draft block covers both.
  // HRP-185: also gated while a reviewer is calibrating Totals — submissions
  // are locked server-side, so we surface the lock in the UI instead of
  // letting users click a button that 409s.
  // HRP-329: a saved calibration keeps the lock — surveys never reopen.
  const calibrationLock =
    !!assessment.calibration_in_progress || !!assessment.has_calibrated_totals;
  // HRP-329 REDO: a calibration lock no longer HIDES the actions. Hiding
  // them left the user with no explanation for the missing button, so the
  // actions stay visible but disabled and a tooltip names the reason. The
  // structural reasons (draft / terminal / no criteria) still hide, since
  // there is nothing to explain — the assessment simply isn't running.
  const showEvaluateActions =
    !isTerminal && !isDraft && assessment.competence_ids.length > 0;
  // Two distinct states, and they are mutually exclusive: saving a
  // calibration clears `calibration_in_progress` and leaves the totals
  // behind, so "is calibrating" wins while the reviewer is still editing.
  const calibrationLockHint = assessment.calibration_in_progress
    ? t("calibrationLockCalibrating")
    : assessment.has_calibrated_totals
      ? t("calibrationLockCalibrated")
      : null;
  // HRP-104: Preview questions lives in Details (was in Rating scale). Visible
  // to admin/manager AND to participants — anyone who can already see the page
  // and has both criteria + scale picked.
  const canPreviewQuestions = !!assessment.criteria_type && !!scale;
  // HRP-243: Employee-only gate for the Results block. Privileged roles
  // see results in every status that the workflow exposes; an Employee
  // only sees results when they are the assessee AND the assessment is
  // Done.
  const isSelfParticipant = !!currentUser?.id && assessment.participants.some(
    (p) => p.role === "self" && p.user_id === currentUser.id,
  );
  const canViewResults =
    isPrivileged || (isSelfParticipant && assessment.status_code === "done");

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="icon-sm" render={<Link href="/assessments" />}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="flex-1">
          {titleEdit.editing ? (
            <div className="flex items-center gap-2">
              <Input
                data-testid="assessment-input-edit-title"
                value={titleEdit.draft}
                onChange={(e) => titleEdit.setDraft(e.target.value)}
                onKeyDown={inlineEditKeys({
                  onCommit: saveTitle,
                  onCancel: titleEdit.cancel,
                  disabled: saving,
                })}
                className="h-9 max-w-md text-base"
                autoFocus
                disabled={saving}
                maxLength={100}
              />
              <Button
                size="icon-sm"
                onClick={saveTitle}
                disabled={saving}
                data-testid="assessment-btn-save-title"
              >
                <Check className="h-4 w-4" />
              </Button>
              <Button
                size="icon-sm"
                variant="ghost"
                onClick={titleEdit.cancel}
                disabled={saving}
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
          ) : (
            <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
              <span>{assessment.title || tc("assessment")}</span>
              {canManage && !isTerminal && !assessment.group_id && (
                <Button
                  size="icon-sm"
                  variant="ghost"
                  data-testid="assessment-btn-edit-title"
                  onClick={() => titleEdit.start(assessment.title ?? "")}
                >
                  <Pencil className="h-4 w-4" />
                </Button>
              )}
            </h1>
          )}
          <p className="text-sm text-muted-foreground">
            {assessmentTypeTitle(tRef, assessment)}
          </p>
        </div>
        <Badge variant="secondary" className={statusColors[assessment.status_code] || ""}>
          {assessmentStatusTitle(tRef, assessment)}
        </Badge>
      </div>

      {/* Info card */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("details")}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4 text-sm md:grid-cols-3">
            <div>
              <p className="text-muted-foreground">{tc("employee")}</p>
              {employee ? (
                <>
                  <Link href={`/employees/${employee.id}`} className="font-medium text-primary hover:underline">
                    {employee.user_name || employee.user_email}
                  </Link>
                  {/* HRP-333: position + non-active status chip under the
                      name (shared EmployeeSummaryLine, name via link). */}
                  <EmployeeSummaryLine
                    employee={{
                      user_name: employee.user_name,
                      position_title: employee.position_title,
                      status: employee.status,
                    }}
                    hideName
                    data-testid="assessment-detail-employee-summary"
                  />
                </>
              ) : (
                <p className="text-sm text-muted-foreground">{assessment.employee_name || assessment.employee_id.slice(0, 8)}</p>
              )}
            </div>
            <div>
              <p className="text-muted-foreground">{t("fieldType")}</p>
              <p className="font-medium">{assessmentTypeTitle(tRef, assessment)}</p>
            </div>
            <div>
              <p className="text-muted-foreground">{t("status")}</p>
              <Badge variant="secondary" className={statusColors[assessment.status_code] || ""}>
                {assessmentStatusTitle(tRef, assessment)}
              </Badge>
            </div>
            <div>
              <p className="text-muted-foreground">{t("dateCreated")}</p>
              <p className="font-medium">{formatDate(assessment.created_at)}</p>
            </div>
            <div>
              {/* HRP-161: terminal assessments swap Deadline for the
                  closing date (Completed / Cancelled + yyyy-MM-dd from
                  ``finished_at``); active assessments keep the editable
                  Deadline but paint it red when the date has already
                  passed. */}
              <p className="text-muted-foreground">
                {assessment.status_code === "done"
                  ? t("dateCompleted")
                  : assessment.status_code === "cancelled"
                    ? t("dateCancelled")
                    : t("deadline")}
              </p>
              {isTerminal ? (
                <p
                  className="font-medium"
                  data-testid="assessment-terminal-date"
                >
                  {assessment.finished_at
                    ? formatDate(assessment.finished_at)
                    : "—"}
                </p>
              ) : deadlineEdit.editing ? (
                <div className="mt-1 flex items-center gap-1">
                  {/* HRP-335: shared DatePicker (HRP-152); commit/cancel
                      stay on the adjacent icon buttons. */}
                  <DatePicker
                    data-testid="assessment-input-edit-deadline"
                    value={deadlineEdit.draft}
                    min={todayLocalISO()}
                    onChange={deadlineEdit.setDraft}
                    onCancel={deadlineEdit.cancel}
                    autoFocus
                    className="w-44"
                    inputClassName="h-8 text-sm"
                    disabled={saving}
                  />
                  <Button
                    size="icon-sm"
                    onClick={saveDeadline}
                    disabled={saving || deadlineDraftIsPast}
                    data-testid="assessment-btn-save-deadline"
                  >
                    <Check className="h-4 w-4" />
                  </Button>
                  <Button
                    size="icon-sm"
                    variant="ghost"
                    onClick={deadlineEdit.cancel}
                    disabled={saving}
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </div>
              ) : (
                <div className="flex items-center gap-2">
                  <p
                    className={`font-medium${
                      assessment.ended_at &&
                      isPastDeadline(assessment.ended_at.slice(0, 10))
                        ? " text-destructive"
                        : ""
                    }`}
                    data-testid="assessment-deadline"
                  >
                    {assessment.ended_at
                      ? formatDate(assessment.ended_at)
                      : "—"}
                  </p>
                  {canManage && (
                    <Button
                      size="icon-sm"
                      variant="ghost"
                      data-testid="assessment-btn-edit-deadline"
                      onClick={() =>
                        deadlineEdit.start(
                          assessment.ended_at
                            ? assessment.ended_at.slice(0, 10)
                            : "",
                        )
                      }
                    >
                      <Pencil className="h-4 w-4" />
                    </Button>
                  )}
                </div>
              )}
            </div>
          </div>

          {canManage && nextStatuses.length > 0 && (
            <div className="mt-4 flex gap-2">
              {nextStatuses.map((s) => (
                <Button
                  key={s}
                  size="sm"
                  variant="outline"
                  onClick={() => changeStatus(s)}
                  disabled={saving}
                  data-testid={`assessment-btn-status-${s}`}
                >
                  <Send className="mr-1 h-4 w-4" />
                  {/* HRP-190: imperative `send` on Draft → Sent.
                      HRP-192: `cancel` on the cancelled action so the
                      button reads as a verb when In progress is gone
                      from Sent's nextStatuses. */}
                  {STATUS_ACTION_KEYS[s]
                    ? t(STATUS_ACTION_KEYS[s])
                    : s.replace("_", " ")}
                </Button>
              ))}
            </div>
          )}
          {showEvaluateActions && myFirstPending && (
            <div className="mt-4 flex gap-2">
              {calibrationLockHint ? (
                // A disabled button emits no pointer events, so the
                // tooltip trigger has to be the wrapping span.
                <Tooltip>
                  <TooltipTrigger
                    render={<span tabIndex={-1} className="inline-flex" />}
                  >
                    <Button size="sm" data-testid="assessment-take-cta" disabled>
                      <Pencil className="mr-1 h-4 w-4" />
                      {t("takeAssessment")}
                      {myPendingParticipants.length > 1 &&
                        ` (${myPendingParticipants.length})`}
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>{calibrationLockHint}</TooltipContent>
                </Tooltip>
              ) : (
                <Button
                  size="sm"
                  data-testid="assessment-take-cta"
                  onClick={() => openEvaluation(myFirstPending.id)}
                >
                  <Pencil className="mr-1 h-4 w-4" />
                  {t("takeAssessment")}
                  {myPendingParticipants.length > 1 && ` (${myPendingParticipants.length})`}
                </Button>
              )}
            </div>
          )}
          {canPreviewQuestions && (
            <div className="mt-4 flex gap-2">
              <Button
                size="sm"
                data-testid="assessment-btn-preview-questions"
                onClick={openPreview}
              >
                {t("previewQuestions")}
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Evaluation criteria */}
      <Card data-testid="assessment-criteria-card">
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle className="text-base">{t("evaluationCriteria")}</CardTitle>
          {canManage && isDraft && !isGroupChild && (
            <Button
              data-testid="assessment-criteria-btn-add"
              size="sm"
              variant="outline"
              onClick={() => setCriteriaOpen(true)}
            >
              <Pencil className="mr-1 h-4 w-4" />
              {assessment.criteria_type ? t("change") : t("select")}
            </Button>
          )}
        </CardHeader>
        <CardContent>
          <CriteriaSummary
            criteriaType={assessment.criteria_type}
            specializationTitle={assessment.specialization_title}
            gradeTitle={assessment.grade_title}
            specializationI18nKey={assessment.specialization_i18n_key}
            gradeI18nKey={assessment.grade_i18n_key}
            gradeId={assessment.grade_id}
            competences={assessment.competences ?? []}
          />
        </CardContent>
      </Card>

      {/* Rating scale */}
      <Card data-testid="assessment-scale-card">
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle className="text-base">{t("ratingScale")}</CardTitle>
          {canManage && isDraft && !isGroupChild && scale && (
            <Button
              data-testid="assessment-scale-btn-change"
              size="sm"
              variant="outline"
              onClick={openScalePicker}
            >
              <Pencil className="mr-1 h-4 w-4" />
              {t("change")}
            </Button>
          )}
        </CardHeader>
        <CardContent>
          {scale ? (
            <div className="space-y-2">
              <p className="text-sm font-medium">{answerScaleLabel(tRef, scale)}</p>
              {(() => {
                const description = answerScaleDescription(tRef, scale);
                return description ? (
                  <p className="text-xs text-muted-foreground">{description}</p>
                ) : null;
              })()}
              <div className="flex flex-wrap gap-2 pt-1">
                {[...scale.options]
                  .sort((a, b) => a.sort_index - b.sort_index)
                  .map((opt) => {
                    const suffix = scaleOptionSuffix(t, opt, {
                      showScore: canManage,
                    });
                    return (
                      <Badge
                        key={opt.id}
                        variant="outline"
                        title={scaleOptionDescription(tRef, opt) ?? undefined}
                      >
                        {scaleOptionLabel(tRef, opt)}
                        {suffix && (
                          <span className="ml-1 text-muted-foreground">{suffix}</span>
                        )}
                      </Badge>
                    );
                  })}
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center gap-3 py-4 text-center">
              <p className="text-sm text-muted-foreground">
                {t("noScaleAssessment")}
              </p>
              {canManage && isDraft && !isGroupChild && (
                <Button
                  data-testid="assessment-scale-btn-add"
                  size="sm"
                  onClick={openScalePicker}
                >
                  <Plus className="mr-1 h-4 w-4" />
                  {t("addScale")}
                </Button>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Participants */}
      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle className="text-base">{t("participants")}</CardTitle>
          {canAddParticipant && (
            <Button data-testid="assessment-participants-btn-add" size="sm" variant="outline" onClick={async () => {
              try {
                const data = await api.get<EmployeeList>("/employees?limit=100");
                setEmployees(data.items);
              } catch { /* ignore */ }
              setPartForm({ employee_id: "", role: "peer" });
              setPartOpen(true);
            }}>
              <Plus className="mr-1 h-4 w-4" />
              {t("add")}
            </Button>
          )}
        </CardHeader>
        <CardContent>
          {assessment.participants.length === 0 ? (
            <p className="py-4 text-center text-sm text-muted-foreground">
              {t("noParticipants")}
            </p>
          ) : (
            <div className="rounded-lg border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("colParticipant")}</TableHead>
                    <TableHead>{t("colRole")}</TableHead>
                    <TableHead>{t("colCompleted")}</TableHead>
                    <TableHead className="w-20" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {assessment.participants.map((p) => {
                    const isEvaluatee = !!evaluateeUserId && p.user_id === evaluateeUserId;
                    const isMine = !!currentUser?.id && p.user_id === currentUser.id;
                    const showEvaluate =
                      showEvaluateActions && !p.is_completed && isMine;
                    return (
                    <TableRow key={p.id} data-testid={`assessment-participant-${p.id}`}>
                      <TableCell className="text-sm">
                        <div className="flex flex-col gap-0.5">
                          <div className="flex items-center gap-2">
                            {p.can_view_profile && p.employee_id ? (
                              <Link
                                href={`/employees/${p.employee_id}`}
                                className="hover:underline"
                                data-testid={`assessment-participant-${p.id}-link`}
                              >
                                {p.user_name || p.user_id?.slice(0, 8) || "—"}
                              </Link>
                            ) : (
                              <span data-testid={`assessment-participant-${p.id}-name`}>
                                {p.user_name || p.user_id?.slice(0, 8) || "—"}
                              </span>
                            )}
                            {isEvaluatee && (
                              <Badge variant="outline" className="border-amber-300 text-amber-700" data-testid={`assessment-participant-${p.id}-evaluatee`}>
                                <Star className="mr-1 h-3 w-3" />
                                {t("evaluatee")}
                              </Badge>
                            )}
                          </div>
                          {/* HRP-333: position + non-active status chip
                              under the participant (externals have no
                              employee row, the line stays empty). */}
                          <EmployeeSummaryLine
                            employee={{
                              user_name: p.user_name,
                              position_title: p.position_title,
                              status: p.employee_status,
                            }}
                            hideName
                            data-testid={`assessment-participant-${p.id}-summary`}
                          />
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge variant="secondary" className={roleColors[p.role] || ""}>{p.role}</Badge>
                      </TableCell>
                      <TableCell>
                        <Badge variant={p.is_completed ? "default" : "outline"}>
                          {p.is_completed ? t("yes") : t("no")}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        {showEvaluate &&
                          (calibrationLockHint ? (
                            <Tooltip>
                              <TooltipTrigger
                                render={
                                  <span tabIndex={-1} className="inline-flex" />
                                }
                              >
                                <Button
                                  size="xs"
                                  variant="ghost"
                                  data-testid={`assessment-participant-${p.id}-evaluate`}
                                  disabled
                                >
                                  <Pencil className="mr-1 h-3 w-3" />
                                  {t("evaluate")}
                                </Button>
                              </TooltipTrigger>
                              <TooltipContent>
                                {calibrationLockHint}
                              </TooltipContent>
                            </Tooltip>
                          ) : (
                            <Button size="xs" variant="ghost" data-testid={`assessment-participant-${p.id}-evaluate`} onClick={() => openEvaluation(p.id)}>
                              <Pencil className="mr-1 h-3 w-3" />
                              {t("evaluate")}
                            </Button>
                          ))}
                      </TableCell>
                    </TableRow>
                  );})}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* HRP-170: Recommended grade chart unlocks at On Review and stays
          visible for Done and for Cancelled-from-on-review. The backend
          gates eligibility per assessment.criteria_type, so the presence
          of a payload is the source of truth here. */}
      {assessment.recommendation && (
        <AssessmentRecommendationCard recommendation={assessment.recommendation} />
      )}

      {/* Results */}
      {canViewResults && assessment.results.length > 0 && (
        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <div className="flex items-baseline gap-3">
              <CardTitle className="text-base">{t("results")}</CardTitle>
              {assessment.overall_percent !== null && (
                <span
                  className="text-lg font-semibold text-primary"
                  data-testid="assessment-results-overall-percent"
                >
                  {assessment.overall_percent}%
                </span>
              )}
            </div>
            {/* HRP-185: Calibrate lives in the Detailed results card now —
                the spec moves calibration onto per-indicator Totals. */}
          </CardHeader>
          <CardContent>
            <div className="rounded-lg border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("colCompetence")}</TableHead>
                    {/* HRP-185 REDO: a single Avg Score column that
                        reflects the calibrated value when present and
                        falls back to the raw average otherwise — the
                        previous split (Avg Score + Calibrated) duplicated
                        the same number once calibration ran. */}
                    <TableHead>{t("colAvgScore")}</TableHead>
                    <TableHead>{t("colPercent")}</TableHead>
                    <TableHead>{t("colLevel")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {assessment.results.map((r) => {
                    const comp = allCompetences.find((c) => c.id === r.competence_id);
                    const assessmentComp = assessment.competences.find(
                      (c) => c.competence_id === r.competence_id,
                    );
                    const requiredLevelTitle = assessmentComp?.skill_level_title
                      ? skillLevelLabel(tRef, {
                          title: assessmentComp.skill_level_title,
                          i18n_key: assessmentComp.skill_level_i18n_key,
                        })
                      : null;
                    const perLevelRowsForComp = r.per_level_results ?? [];
                    const compTitle = comp?.title || r.competence_id.slice(0, 8);
                    return (
                      <TableRow key={r.competence_id}>
                        <TableCell className="font-medium">
                          <div className="flex items-center gap-2">
                            <span>{compTitle}</span>
                            {requiredLevelTitle && (
                              <Badge
                                variant="outline"
                                className="font-normal"
                                data-testid={`assessment-results-row-${r.competence_id}-required-level`}
                              >
                                {requiredLevelTitle}
                              </Badge>
                            )}
                            {perLevelRowsForComp.length > 0 && (
                              <button
                                type="button"
                                onClick={() => {
                                  setPerLevelTitle(compTitle);
                                  setPerLevelRows(perLevelRowsForComp);
                                  setPerLevelOpen(true);
                                }}
                                className="text-muted-foreground hover:text-foreground"
                                aria-label={t("resultsByLevel")}
                                data-testid={`assessment-results-row-${r.competence_id}-per-level-btn`}
                              >
                                <Info className="h-4 w-4" />
                              </button>
                            )}
                          </div>
                        </TableCell>
                        <TableCell data-testid={`assessment-results-row-${r.competence_id}-avg-score`}>
                          {(r.calibrated_score ?? r.avg_score).toFixed(2)}
                        </TableCell>
                        <TableCell data-testid={`assessment-results-row-${r.competence_id}-percent`}>
                          {r.percent === null ? "—" : `${r.percent}%`}
                        </TableCell>
                        <TableCell data-testid={`assessment-results-row-${r.competence_id}-level`}>
                          {r.level ? (
                            <Badge variant="secondary" title={r.level.description ?? undefined}>
                              {scaleLevelLabel(tRef, r.level)}
                            </Badge>
                          ) : (
                            ""
                          )}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      )}

      {/* HRP-154: Detailed results — same visibility window as the
          Results card above (statuses on_review / done / cancelled-from-
          on-review), restricted to roles that can see calibrated data.
          HRP-185: the card also drives per-indicator Total calibration —
          it needs the scale snapshot, the in-progress flag, and a callback
          to refresh the parent after start / save / cancel. */}
      <AssessmentDetailedResults
        assessmentId={id}
        visible={canViewDetailedResults && assessment.results.length > 0}
        scale={scale ?? null}
        calibrationInProgress={calibrationLock}
        canManage={canManage && !isTerminal}
        onCalibrationChange={load}
      />

      {/* CPA Comparison */}
      {assessment.cpa_id && (
        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle className="text-base">{t("compareCpaRounds")}</CardTitle>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                setCpaComparison(null);
                setCpaCompId2("");
                setCpaCompOpen(true);
              }}
            >
              <ArrowRightLeft className="mr-1 h-4 w-4" />
              {t("compareWithAnotherCpa")}
            </Button>
          </CardHeader>
          <CardContent>
            {cpaComparison ? (
              <div className="space-y-3">
                <div className="flex gap-4 text-sm">
                  <div>
                    <span className="text-muted-foreground">{t("round1Label")} </span>
                    <span className="font-medium">{cpaComparison.round_1.title || cpaComparison.round_1.id.slice(0, 8)}</span>
                  </div>
                  <div>
                    <span className="text-muted-foreground">{t("round2Label")} </span>
                    <span className="font-medium">{cpaComparison.round_2.title || cpaComparison.round_2.id.slice(0, 8)}</span>
                  </div>
                </div>
                {cpaComparison.comparisons.length === 0 ? (
                  <p className="py-4 text-center text-sm text-muted-foreground">
                    {t("noOverlappingEmployees")}
                  </p>
                ) : (
                  <div className="rounded-lg border">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>{tc("employee")}</TableHead>
                          <TableHead>{t("colRound1Score")}</TableHead>
                          <TableHead>{t("colRound2Score")}</TableHead>
                          <TableHead>{t("colDelta")}</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {cpaComparison.comparisons.map((c) => (
                          <TableRow key={c.employee_id}>
                            <TableCell className="font-medium">{c.employee_name || c.employee_id.slice(0, 8)}</TableCell>
                            <TableCell>{c.round_1_score.toFixed(2)}</TableCell>
                            <TableCell>{c.round_2_score.toFixed(2)}</TableCell>
                            <TableCell>
                              <span className={c.delta > 0 ? "text-green-600 font-medium" : c.delta < 0 ? "text-red-600 font-medium" : "text-muted-foreground"}>
                                {c.delta > 0 ? "+" : ""}{c.delta.toFixed(2)}
                              </span>
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                )}
              </div>
            ) : (
              <p className="py-4 text-center text-sm text-muted-foreground">
                {t("cpaCompareHint")}
              </p>
            )}
          </CardContent>
        </Card>
      )}

      {/* CPA comparison dialog */}
      <Dialog open={cpaCompOpen} onOpenChange={setCpaCompOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("compareCpaRounds")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>{t("currentCpa")}</Label>
              <Input value={assessment.cpa_id || ""} disabled className="text-muted-foreground" />
            </div>
            <div className="space-y-2">
              <Label>{t("compareWithCpaId")}</Label>
              <Input
                placeholder={t("cpaIdPlaceholder")}
                value={cpaCompId2}
                onChange={(e) => setCpaCompId2(e.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCpaCompOpen(false)} disabled={cpaCompLoading}>
              {tc("cancel")}
            </Button>
            <Button
              onClick={async () => {
                await fetchCpaComparison();
                setCpaCompOpen(false);
              }}
              disabled={cpaCompLoading || !cpaCompId2.trim()}
            >
              {cpaCompLoading ? tc("loading") : t("compare")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Add participant dialog */}
      <Dialog open={partOpen} onOpenChange={setPartOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("addParticipant")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>{tc("employee")}</Label>
              <Select value={partForm.employee_id} onValueChange={(val) => setPartForm({ ...partForm, employee_id: val })}>
                <SelectTrigger className="w-full" data-testid="assessment-participant-select-employee">
                  <SelectValue placeholder={t("selectEmployee")}>
                    {(() => {
                      if (!partForm.employee_id) return undefined;
                      const emp = employees.find((e) => e.id === partForm.employee_id);
                      return emp ? (emp.user_name || emp.user_email || emp.id.slice(0, 8)) : undefined;
                    })()}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {(() => {
                    // HRP-18: hide employees already in this assessment
                    // (assessee + every existing participant) so the same human
                    // can't be added a second time in any role.
                    const takenUserIds = new Set(
                      assessment.participants.map((p) => p.user_id),
                    );
                    const available = employees.filter(
                      (e) => !takenUserIds.has(e.user_id),
                    );
                    if (available.length === 0) {
                      return (
                        <div
                          className="px-2 py-1.5 text-sm text-muted-foreground"
                          data-testid="assessment-participant-select-empty"
                        >
                          {t("everyoneParticipant")}
                        </div>
                      );
                    }
                    return available.map((emp) => (
                      <SelectItem key={emp.id} value={emp.id}>
                        {emp.user_name || emp.user_email || emp.id.slice(0, 8)}
                      </SelectItem>
                    ));
                  })()}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>{t("colRole")}</Label>
              <Select value={partForm.role} onValueChange={(val) => setPartForm({ ...partForm, role: val })}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {["manager", "peer", "subordinate"].map((r) => (
                    <SelectItem key={r} value={r}>{r}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPartOpen(false)} disabled={saving}>{tc("cancel")}</Button>
            <Button onClick={addParticipant} disabled={saving || !partForm.employee_id}>
              {saving ? t("adding") : t("add")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Criteria sheet */}
      <CriteriaSheet
        open={criteriaOpen}
        onOpenChange={setCriteriaOpen}
        readOnly={assessment.status_code !== "draft"}
        initial={{
          criteria_type: assessment.criteria_type,
          specialization_id: assessment.specialization_id,
          grade_id: assessment.grade_id,
          competences: assessment.competences ?? [],
          passing_score: assessment.passing_score,
        }}
        onSave={saveCriteria}
      />

      {/* HRP-146: Evaluation sheet — side panel with vertical answer
          options, autosave on every change, and draft rehydrate so a
          partially-answered survey can be reopened without losing
          progress. */}
      <Sheet
        open={evalOpen}
        onOpenChange={(o) => {
          setEvalOpen(o);
          if (!o) {
            // Save anything still sitting in a debounce window before
            // the Sheet unmounts so closing-then-reopening reflects the
            // most recent edits.
            flushPendingCommentSaves();
            setEvalMissing(new Set());
          }
        }}
      >
        <SheetContent
          className="max-w-xl sm:max-w-xl"
          data-testid="assessment-eval-sheet"
        >
          <SheetHeader>
            <SheetTitle>{t("takeAssessment")}</SheetTitle>
          </SheetHeader>
          {evalLoading ? (
            <div className="flex-1 py-8 text-center text-sm text-muted-foreground">
              {t("loadingIndicators")}
            </div>
          ) : (
            <div className="flex-1 space-y-5 overflow-y-auto pr-1">
              {(() => {
                const grouped = new Map<string, typeof evalIndicators>();
                for (const ind of evalIndicators) {
                  if (!grouped.has(ind.competence)) grouped.set(ind.competence, []);
                  grouped.get(ind.competence)!.push(ind);
                }
                return Array.from(grouped.entries()).map(([compName, inds]) => (
                  <div key={compName} className="space-y-3">
                    <p className="text-sm font-semibold">{compName}</p>
                    <div className="space-y-3">
                      {inds.map((ind) => {
                        const answer = evalAnswers[ind.id];
                        const isMissing = evalMissing.has(ind.id);
                        return (
                          <div
                            key={ind.id}
                            data-testid={`assessment-eval-indicator-${ind.id}`}
                            className={`rounded-md border p-3 ${
                              isMissing ? "border-destructive bg-destructive/5" : ""
                            }`}
                          >
                            <p className="mb-3 text-sm">{ind.title}</p>
                            {scale?.options ? (
                              <RadioGroup
                                value={answer?.answer_option_id ?? ""}
                                onValueChange={(value) =>
                                  selectAnswerOption(ind.id, value as string)
                                }
                                aria-label={t("answerForIndicator", {
                                  title: ind.title,
                                })}
                              >
                                {scale.options
                                  .slice()
                                  .sort((a, b) => a.sort_index - b.sort_index)
                                  .map((opt) => (
                                    <label
                                      key={opt.id}
                                      htmlFor={`eval-${ind.id}-${opt.id}`}
                                      className="flex cursor-pointer items-start gap-2 rounded-sm px-1 py-1 text-sm hover:bg-muted/40"
                                    >
                                      <RadioItem
                                        id={`eval-${ind.id}-${opt.id}`}
                                        value={opt.id}
                                        className="mt-0.5"
                                        data-testid={`assessment-eval-option-${ind.id}-${opt.id}`}
                                      />
                                      <span className="leading-snug">
                                        {scaleOptionLabel(tRef, opt)}
                                        {scaleOptionDescription(tRef, opt) && (
                                          <span className="ml-1 text-muted-foreground">
                                            — {scaleOptionDescription(tRef, opt)}
                                          </span>
                                        )}
                                      </span>
                                    </label>
                                  ))}
                              </RadioGroup>
                            ) : (
                              <Input
                                type="number"
                                placeholder={t("scorePlaceholder")}
                                className="w-24"
                                value={answer?.answer_option_id ?? ""}
                                onChange={(e) =>
                                  selectAnswerOption(ind.id, e.target.value)
                                }
                              />
                            )}
                            <div className="mt-3">
                              <Textarea
                                placeholder={t("commentPlaceholder")}
                                value={answer?.comment ?? ""}
                                onChange={(e) =>
                                  updateAnswerComment(ind.id, e.target.value)
                                }
                                onBlur={flushPendingCommentSaves}
                                className="min-h-[64px]"
                                data-testid={`assessment-eval-comment-${ind.id}`}
                              />
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ));
              })()}
            </div>
          )}
          <SheetFooter>
            <Button
              variant="outline"
              onClick={() => setEvalOpen(false)}
              disabled={saving}
            >
              {t("close")}
            </Button>
            <Button onClick={submitEvaluation} disabled={saving || evalLoading}>
              {saving ? t("submitting") : t("submitAnswers")}
            </Button>
          </SheetFooter>
        </SheetContent>
      </Sheet>

      {/* HRP-165: read-only Question preview opens as a side Sheet mirroring
          the take-assessment layout — disabled answer inputs, no comment
          field, only a Close action. */}
      <Sheet open={previewOpen} onOpenChange={setPreviewOpen}>
        <SheetContent
          className="max-w-xl sm:max-w-xl"
          data-testid="question-preview-sheet"
        >
          <SheetHeader>
            <SheetTitle>{t("questionPreview")}</SheetTitle>
          </SheetHeader>
          {previewLoading ? (
            <div className="flex-1 py-8 text-center text-sm text-muted-foreground">
              {t("loadingQuestions")}
            </div>
          ) : (
            // HRP-165 REDO: preview mirrors the take-assessment sheet, so
            // the standalone "Rating scale" banner that used to live above
            // the question list is intentionally omitted (per QA review on
            // 2026-06-10). The per-indicator skill-level badge is dropped
            // for the same reason.
            <div className="flex-1 space-y-5 overflow-y-auto pr-1">
              {previewGroups.length === 0 ? (
                <p className="rounded-md border border-dashed py-6 text-center text-sm text-muted-foreground">
                  {t("noQuestionsYet")}
                </p>
              ) : (
                previewGroups.map((g) => (
                  <div
                    key={g.competence_id}
                    className="space-y-3"
                    data-testid={`assessment-preview-group-${g.competence_id}`}
                  >
                    {/* HRP-165 REDO: align with HRP-146 take-assessment
                        layout — just the competence name, no skill-level
                        tagline on the group header. */}
                    <p className="text-sm font-semibold">{g.competence_title}</p>
                    {g.indicators.length === 0 ? (
                      <p className="rounded-md border border-dashed p-3 text-xs text-muted-foreground">
                        {t("noIndicatorsForLevel")}
                      </p>
                    ) : (
                      <div className="space-y-3">
                        {g.indicators.map((ind) => (
                          <div
                            key={ind.id}
                            data-testid={`assessment-preview-indicator-${ind.id}`}
                            className="rounded-md border p-3 opacity-90"
                          >
                            <div className="mb-3 flex items-start gap-2 text-sm">
                              <span className="flex-1">{ind.title}</span>
                            </div>
                            {scale?.options && scale.options.length > 0 && (
                              <RadioGroup
                                value=""
                                aria-label={t("previewAnswersFor", {
                                  title: ind.title,
                                })}
                              >
                                {scale.options
                                  .slice()
                                  .sort((a, b) => a.sort_index - b.sort_index)
                                  .map((opt) => (
                                    <label
                                      key={opt.id}
                                      className="flex cursor-not-allowed items-start gap-2 rounded-sm px-1 py-1 text-sm text-muted-foreground"
                                    >
                                      <RadioItem
                                        value={opt.id}
                                        disabled
                                        className="mt-0.5"
                                      />
                                      <span className="leading-snug">
                                        {scaleOptionLabel(tRef, opt)}
                                        {scaleOptionDescription(tRef, opt) && (
                                          <span className="ml-1 text-muted-foreground">
                                            — {scaleOptionDescription(tRef, opt)}
                                          </span>
                                        )}
                                      </span>
                                    </label>
                                  ))}
                              </RadioGroup>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>
          )}
          <SheetFooter>
            <Button
              variant="outline"
              data-testid="question-preview-close"
              onClick={() => setPreviewOpen(false)}
            >
              {t("close")}
            </Button>
          </SheetFooter>
        </SheetContent>
      </Sheet>

      {/* Rating scale picker dialog */}
      <Dialog open={scaleOpen} onOpenChange={setScaleOpen}>
        <DialogContent data-testid="assessment-scale-modal" className="sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>{t("ratingScale")}</DialogTitle>
          </DialogHeader>
          {answerScales.length === 0 ? (
            <p className="py-4 text-center text-sm text-muted-foreground">
              {t("noScalesAvailable")}
            </p>
          ) : (
            <RadioGroup
              value={scalePick}
              onValueChange={setScalePick}
              className="max-h-96 space-y-2 overflow-y-auto"
            >
              {[...answerScales]
                .sort((a, b) => {
                  if (a.is_default !== b.is_default) return a.is_default ? -1 : 1;
                  // Raw-title sort is safe: these lists exclude snapshots
                  // and tenant scales always have i18n_key NULL, so only
                  // the default scale localizes — and it sorts first via
                  // is_default above (HRP-479).
                  return a.title.localeCompare(b.title);
                })
                .map((s) => (
                  <div
                    key={s.id}
                    className="flex items-start gap-3 rounded-md border p-3 transition-colors hover:bg-accent/40"
                    data-testid={`assessment-scale-modal-item-${s.id}`}
                  >
                    <label className="flex flex-1 cursor-pointer items-start gap-3">
                      <RadioItem value={s.id} className="mt-1" />
                      <div className="flex-1">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium">
                            {s.is_default ? t("defaultAnswerScale") : s.title}
                          </span>
                          {s.is_default && (
                            <Badge variant="outline" className="border-primary/40 text-primary">
                              <Sparkles className="mr-1 h-3 w-3" />
                              {t("systemBadge")}
                            </Badge>
                          )}
                        </div>
                        {(() => {
                          const description = answerScaleDescription(tRef, s);
                          return description ? (
                            <p className="mt-0.5 text-xs text-muted-foreground">
                              {description}
                            </p>
                          ) : null;
                        })()}
                        <div className="mt-1.5 flex flex-wrap gap-1">
                          {[...s.options]
                            .sort((a, b) => a.sort_index - b.sort_index)
                            .map((opt) => (
                              <Badge key={opt.id} variant="secondary" className="text-xs">
                                {scaleOptionLabel(tRef, opt)}
                                {!opt.is_neutral && opt.weight !== null && (
                                  <span className="ml-1 text-muted-foreground">
                                    ({opt.weight})
                                  </span>
                                )}
                              </Badge>
                            ))}
                        </div>
                      </div>
                    </label>
                    <DropdownMenu>
                      <DropdownMenuTrigger
                        render={
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            data-testid={`assessment-scale-modal-item-${s.id}-menu`}
                          />
                        }
                      >
                        <MoreHorizontal className="h-4 w-4" />
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem
                          onClick={() => openScalePreview(s.id)}
                          data-testid={`assessment-scale-modal-item-${s.id}-menu-preview`}
                        >
                          {t("preview")}
                        </DropdownMenuItem>
                        {!s.is_default && (
                          <>
                            {canManage && (
                              <DropdownMenuItem
                                onClick={() => openScaleEditor(s)}
                                data-testid={`assessment-scale-modal-item-${s.id}-menu-edit`}
                              >
                                {t("edit")}
                              </DropdownMenuItem>
                            )}
                            {canManage && (
                              <DropdownMenuItem
                                variant="destructive"
                                onClick={() => requestScaleDelete(s.id)}
                                data-testid={`assessment-scale-modal-item-${s.id}-menu-delete`}
                              >
                                {tc("delete")}
                              </DropdownMenuItem>
                            )}
                          </>
                        )}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                ))}
            </RadioGroup>
          )}
          {canManage && (
            <Button
              variant="outline"
              size="sm"
              onClick={openScaleCreator}
              data-testid="assessment-scale-modal-btn-create"
            >
              <Plus className="mr-1 h-4 w-4" />
              {t("createScale")}
            </Button>
          )}
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setScaleOpen(false)}
              disabled={saving}
            >
              {tc("cancel")}
            </Button>
            <Button
              data-testid="assessment-scale-modal-btn-save"
              onClick={saveScale}
              disabled={saving || !scalePick || scalePick === (assessment.scale_id ?? "")}
            >
              {saving ? t("savingEllipsis") : t("save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* HRP-185: per-competence Calibrate Dialog removed — calibration
          now lives on per-indicator Totals inside Detailed results. */}

      {/* HRP-90: Per-level results popup */}
      <Dialog open={perLevelOpen} onOpenChange={setPerLevelOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {t("resultsByLevelTitle", { title: perLevelTitle })}
            </DialogTitle>
          </DialogHeader>
          <div className="rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("skillLevel")}</TableHead>
                  <TableHead>{t("colPercent")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {perLevelRows.map((row) => (
                  <TableRow key={row.skill_level_id} data-testid={`per-level-row-${row.skill_level_id}`}>
                    <TableCell>
                      {row.skill_level_title
                        ? skillLevelLabel(tRef, {
                            title: row.skill_level_title,
                            i18n_key: row.skill_level_i18n_key,
                          })
                        : "—"}
                    </TableCell>
                    <TableCell>{row.percent === null ? "—" : `${row.percent}%`}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPerLevelOpen(false)}>
              {t("close")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ScalePreviewDialog
        open={scalePreviewOpen}
        onOpenChange={setScalePreviewOpen}
        scaleId={scalePreviewId}
        initial={
          scalePreviewId
            ? answerScales.find((s) => s.id === scalePreviewId) ?? null
            : null
        }
      />

      <ScaleEditorSheet
        open={scaleEditorOpen}
        onOpenChange={setScaleEditorOpen}
        mode={scaleEditorMode}
        initial={scaleEditorInitial}
        onSaved={handleScaleSaved}
      />

      <ConfirmDialog
        open={scaleDeleteOpen}
        onOpenChange={setScaleDeleteOpen}
        title={t("deleteScaleConfirmTitle")}
        description={t("deleteScaleConfirmDescription")}
        confirmLabel={tc("delete")}
        destructive
        onConfirm={confirmScaleDelete}
        testId="scale-confirm-delete"
      />
    </div>
  );
}
