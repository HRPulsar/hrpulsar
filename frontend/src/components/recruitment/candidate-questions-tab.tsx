"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { api, taskErrorKey } from "@/lib/api";
import type {
  CandidateQuestion,
  CompetenceItem,
  VacancyProfile,
} from "@/lib/types";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ChevronDown, Download, FileQuestion, Plus, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { QuestionCard } from "./question-card";
import { QuestionDetailSheet } from "./question-detail-sheet";
import { QuestionsExportDialog } from "./questions-export-dialog";

interface ProfileWithCompetences extends VacancyProfile {
  profile_data: { competences?: (CompetenceItem & { id?: string })[] } & Record<
    string,
    unknown
  >;
}

interface CandidateQuestionsTabProps {
  candidateId: string;
  candidateName?: string;
  /** Initial vacancy. If omitted, the user picks one from the candidate's history. */
  vacancyOptions: { id: string; title: string }[];
  initialVacancyId?: string;
}

interface CompetenceMeta {
  id: string;
  name: string;
}

const ASKED_KEY = (candidateId: string, vacancyId: string) =>
  `recruitment.asked.${candidateId}.${vacancyId}`;

function loadAskedSet(candidateId: string, vacancyId: string): Set<string> {
  if (typeof window === "undefined") return new Set();
  try {
    const raw = window.localStorage.getItem(ASKED_KEY(candidateId, vacancyId));
    if (!raw) return new Set();
    const arr = JSON.parse(raw) as string[];
    return new Set(arr);
  } catch {
    return new Set();
  }
}

function saveAskedSet(
  candidateId: string,
  vacancyId: string,
  asked: Set<string>,
) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      ASKED_KEY(candidateId, vacancyId),
      JSON.stringify(Array.from(asked)),
    );
  } catch {
    /* ignore quota errors */
  }
}

export function CandidateQuestionsTab({
  candidateId,
  candidateName,
  vacancyOptions,
  initialVacancyId,
}: CandidateQuestionsTabProps) {
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const [vacancyId, setVacancyId] = useState<string | undefined>(
    initialVacancyId || vacancyOptions[0]?.id,
  );
  const [questions, setQuestions] = useState<CandidateQuestion[]>([]);
  const [competences, setCompetences] = useState<CompetenceMeta[]>([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [editing, setEditing] = useState<Partial<CandidateQuestion> | null>(
    null,
  );
  const [sheetOpen, setSheetOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [askedIds, setAskedIds] = useState<Set<string>>(new Set());
  const [pendingDelete, setPendingDelete] = useState<CandidateQuestion | null>(
    null,
  );

  const competenceLookup = useMemo(() => {
    const map = new Map<string, string>();
    for (const c of competences) {
      map.set(c.id, c.name);
    }
    return map;
  }, [competences]);

  const loadQuestions = useCallback(async () => {
    if (!vacancyId) return;
    setLoading(true);
    try {
      const params = new URLSearchParams({ vacancy_id: vacancyId });
      const data = await api.get<CandidateQuestion[]>(
        `/recruitment/candidates/${candidateId}/questions?${params}`,
      );
      setQuestions(data);
    } catch {
      setQuestions([]);
    } finally {
      setLoading(false);
    }
  }, [candidateId, vacancyId]);

  const loadProfile = useCallback(async () => {
    if (!vacancyId) {
      setCompetences([]);
      return;
    }
    try {
      const profile = await api.get<ProfileWithCompetences | { profile: null }>(
        `/recruitment/vacancies/${vacancyId}/profile`,
      );
      if ("profile" in profile && profile.profile === null) {
        setCompetences([]);
        return;
      }
      const items = (profile as ProfileWithCompetences).profile_data
        ?.competences;
      if (Array.isArray(items)) {
        setCompetences(
          items
            .map((c) => ({
              id: (c as { id?: string }).id || c.name,
              name: c.name,
            }))
            .filter((c) => Boolean(c.id)),
        );
      } else {
        setCompetences([]);
      }
    } catch {
      setCompetences([]);
    }
  }, [vacancyId]);

  useEffect(() => {
    loadQuestions();
    loadProfile();
  }, [loadQuestions, loadProfile]);

  useEffect(() => {
    if (vacancyId) {
      setAskedIds(loadAskedSet(candidateId, vacancyId));
    }
  }, [candidateId, vacancyId]);

  const grouped = useMemo(() => {
    const map = new Map<string, CandidateQuestion[]>();
    for (const q of questions) {
      const key = q.competence_id || "__general__";
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(q);
    }
    return map;
  }, [questions]);

  const mustQuestions = useMemo(
    () => questions.filter((q) => q.priority === "must"),
    [questions],
  );

  function toggleAsked(question: CandidateQuestion, asked: boolean) {
    if (!vacancyId) return;
    setAskedIds((prev) => {
      const next = new Set(prev);
      if (asked) next.add(question.id);
      else next.delete(question.id);
      saveAskedSet(candidateId, vacancyId, next);
      return next;
    });
  }

  async function handleGenerate() {
    if (!vacancyId) return;
    setGenerating(true);
    try {
      await api.postAndWait(
        `/recruitment/candidates/${candidateId}/vacancies/${vacancyId}/generate-questions`,
        undefined,
        { timeoutMs: 120_000 },
      );
      await loadQuestions();
      toast.success(t("candidateQuestionsToastGenerated"));
    } catch (err) {
      // HRP-512: a task failure with no worker message carries a stable
      // code instead of English text — render it from the catalog.
      const taskKey = taskErrorKey(err);
      const message = taskKey
        ? tc(taskKey)
        : err && typeof err === "object" && "message" in err
          ? String((err as { message: unknown }).message)
          : t("candidateQuestionsGenerateFailed");
      toast.error(message);
    } finally {
      setGenerating(false);
    }
  }

  function startNew() {
    setEditing({ candidate_id: candidateId, vacancy_id: vacancyId });
    setSheetOpen(true);
  }

  function startEdit(question: CandidateQuestion) {
    setEditing(question);
    setSheetOpen(true);
  }

  async function handleSaveQuestion(data: Partial<CandidateQuestion>) {
    if (!vacancyId) return;
    setSaving(true);
    try {
      if (data.id) {
        const updated = await api.put<CandidateQuestion>(
          `/recruitment/questions/${data.id}`,
          {
            question_text: data.question_text,
            good_answer: data.good_answer,
            acceptable_answer: data.acceptable_answer,
            poor_answer: data.poor_answer,
            resume_fragment: data.resume_fragment || null,
            purpose: data.purpose,
            priority: data.priority,
            competence_id: data.competence_id || null,
          },
        );
        setQuestions((prev) =>
          prev.map((q) => (q.id === updated.id ? updated : q)),
        );
        toast.success(t("candidateQuestionsToastSaved"));
      } else {
        const created = await api.post<CandidateQuestion>(
          `/recruitment/candidates/${candidateId}/vacancies/${vacancyId}/questions`,
          {
            question_text: data.question_text,
            good_answer: data.good_answer || "",
            acceptable_answer: data.acceptable_answer || "",
            poor_answer: data.poor_answer || "",
            resume_fragment: data.resume_fragment || null,
            purpose: data.purpose || "clarification",
            priority: data.priority || "should",
            competence_id: data.competence_id || null,
          },
        );
        setQuestions((prev) => [...prev, created]);
        toast.success(t("candidateQuestionsToastAdded"));
      }
      setSheetOpen(false);
    } catch (err) {
      const message =
        err && typeof err === "object" && "message" in err
          ? String((err as { message: unknown }).message)
          : t("candidateQuestionsSaveFailed");
      toast.error(message);
    } finally {
      setSaving(false);
    }
  }

  function requestDelete(question: CandidateQuestion) {
    setPendingDelete(question);
  }

  async function confirmDelete() {
    const question = pendingDelete;
    if (!question) return;
    setSaving(true);
    try {
      await api.delete(`/recruitment/questions/${question.id}`);
      setQuestions((prev) => prev.filter((q) => q.id !== question.id));
      toast.success(t("candidateQuestionsToastDeleted"));
      setSheetOpen(false);
      setPendingDelete(null);
    } catch (err) {
      const message =
        err && typeof err === "object" && "message" in err
          ? String((err as { message: unknown }).message)
          : t("candidateQuestionsDeleteFailed");
      toast.error(message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div data-testid="candidate-questions-tab" className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          {vacancyOptions.length > 1 ? (
            <Select value={vacancyId} onValueChange={setVacancyId}>
              <SelectTrigger
                className="w-64"
                data-testid="questions-vacancy-select"
              >
                <SelectValue placeholder={t("candidateQuestionsSelectVacancy")}>
                  {(value) =>
                    vacancyOptions.find((v) => v.id === value)?.title ??
                    t("candidateQuestionsSelectVacancy")
                  }
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {vacancyOptions.map((v) => (
                  <SelectItem key={v.id} value={v.id}>
                    {v.title}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : (
            vacancyOptions[0] && (
              <span className="text-sm text-muted-foreground">
                {vacancyOptions[0].title}
              </span>
            )
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={!vacancyId || generating}
            onClick={handleGenerate}
            data-testid="questions-btn-regenerate"
          >
            <Sparkles className="mr-1 size-4" />
            {generating
              ? t("candidateQuestionsQueued")
              : t("vacancyCompetencesGenerate")}
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={!vacancyId}
            onClick={startNew}
            data-testid="questions-btn-add"
          >
            <Plus className="mr-1 size-4" />
            {t("llmAddButton")}
          </Button>
          <Button
            size="sm"
            disabled={!vacancyId || questions.length === 0}
            onClick={() => setExportOpen(true)}
            data-testid="questions-btn-export"
          >
            <Download className="mr-1 size-4" />
            {t("candidateQuestionsExportPdf")}
          </Button>
        </div>
      </div>

      {mustQuestions.length > 0 && (
        <section
          className="rounded-lg border border-[var(--rec-red-flag)]/30 bg-[color-mix(in_oklch,var(--rec-red-flag)_8%,transparent)] p-3"
          data-testid="questions-mandatory-checklist"
        >
          <h3 className="mb-2 flex items-center justify-between text-sm font-medium">
            {t("candidateQuestionsMandatoryTitle")}
            <span className="text-xs text-muted-foreground">
              {t("candidateQuestionsAskedCount", {
                asked: String(askedIds.size),
                total: String(mustQuestions.length),
              })}
            </span>
          </h3>
          <div className="space-y-2">
            {mustQuestions.map((q) => (
              <QuestionCard
                key={q.id}
                question={q}
                competenceName={
                  q.competence_id
                    ? competenceLookup.get(q.competence_id)
                    : undefined
                }
                compact
                asked={askedIds.has(q.id)}
                onAskedToggle={toggleAsked}
              />
            ))}
          </div>
        </section>
      )}

      {loading ? (
        <p className="text-sm text-muted-foreground">
          {t("candidateQuestionsLoading")}
        </p>
      ) : questions.length === 0 ? (
        <div className="rounded-lg border border-dashed p-12 text-center text-muted-foreground">
          <FileQuestion className="mx-auto mb-3 size-10 opacity-40" />
          <p className="text-sm font-medium">{t("candidateQuestionsEmpty")}</p>
          <p className="mt-1 text-xs">{t("candidateQuestionsEmptyHint")}</p>
        </div>
      ) : (
        <div className="space-y-3">
          {Array.from(grouped.entries()).map(([key, qs]) => {
            const groupName =
              key === "__general__"
                ? t("candidateQuestionsGroupGeneral")
                : competenceLookup.get(key) ||
                  t("candidateQuestionsGroupFallback");
            return (
              <details
                key={key}
                open
                className="rounded-lg border bg-card transition-colors"
              >
                <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-3 py-2 text-sm font-medium">
                  <span>{groupName}</span>
                  <span className="flex items-center gap-2 text-xs text-muted-foreground">
                    {qs.length}
                    <ChevronDown className="size-4 transition-transform [details[open]_&]:rotate-180" />
                  </span>
                </summary>
                <div className="space-y-2 border-t p-3">
                  {qs.map((q) => (
                    <QuestionCard
                      key={q.id}
                      question={q}
                      competenceName={groupName}
                      onEdit={startEdit}
                      onDelete={requestDelete}
                    />
                  ))}
                </div>
              </details>
            );
          })}
        </div>
      )}

      <QuestionDetailSheet
        open={sheetOpen}
        onOpenChange={setSheetOpen}
        question={editing}
        saving={saving}
        onSave={handleSaveQuestion}
        onDelete={requestDelete}
      />

      {vacancyId && (
        <QuestionsExportDialog
          open={exportOpen}
          onOpenChange={setExportOpen}
          candidateId={candidateId}
          vacancyId={vacancyId}
          candidateName={candidateName}
          vacancyTitle={vacancyOptions.find((v) => v.id === vacancyId)?.title}
        />
      )}

      <ConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(o) => !o && setPendingDelete(null)}
        title={t("candidateQuestionsDeleteTitle")}
        description={t("candidateQuestionsDeleteDescription")}
        confirmLabel={tc("delete")}
        cancelLabel={tc("cancel")}
        destructive
        onConfirm={confirmDelete}
        testId="question-delete-confirm"
      />
    </div>
  );
}
