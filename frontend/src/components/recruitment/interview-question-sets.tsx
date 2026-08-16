"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import {
  Bot,
  Check,
  ChevronDown,
  Download,
  FileQuestion,
  Lightbulb,
  Loader2,
  PencilLine,
  Pin,
  Plus,
  RefreshCw,
  Sparkles,
  Target,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useCreditGate } from "@/hooks/use-cost-confirmation";
import { BADGE_COLOR } from "@/lib/badge-tones";
import { questionSetGenerationModeLabel } from "@/lib/recruitment-types";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { CompetenceItem } from "@/lib/types";
import { inlineEditKeys, useInlineEdit } from "@/hooks/use-inline-edit";
import { AddFromCompetencyDialog } from "./add-from-competency-dialog";
import type { NewQuestionPayload } from "./question-payload";

import {
  GOAL_LABEL_KEYS,
  PRIORITY_LABEL_KEYS,
  type QuestionGoal,
  type QuestionPriority,
  type QuestionSource,
} from "@/lib/question-enums";
import {
  type AssessmentRoundRow,
  buildNewSetBody,
  interviewLabel,
  type NewSetSelection,
  setSourceInterviewIds,
  type TranscribedInterviewRow,
  transcribedInterviews,
} from "@/lib/new-question-set";
import { NewQuestionSetDialog } from "./new-question-set-dialog";
import { formatDate } from "@/lib/date-format";

// HRP-485 task 2: the ticket pins the custom-question form bounds.
const QUESTION_TEXT_MIN = 10;
const QUESTION_TEXT_MAX = 500;
const RESUME_ANCHOR_MAX = 60;

type GenerationMode = "initial" | "regenerated" | "dynamic_next" | "manual";
type SetType = "pre_interview" | "interview_round" | "final";
type SetStatus = "ready" | "generating" | "failed" | "sample";

interface QuestionRow {
  id: string | null;
  question_set_id: string | null;
  text: string;
  goal: QuestionGoal;
  priority: QuestionPriority;
  competence_id: string | null;
  resume_anchor_jsonb: { quote?: string; section?: string | null } | null;
  expected_answer_indicators: string[];
  follow_ups: string[];
  rationale: string | null;
  source: QuestionSource;
  source_blind_spot_id: string | null;
  sort_order: number;
  status: "active" | "removed";
  covered_at: string | null;
  covered_by: string | null;
  covered_method: "manual" | "auto_from_transcript" | null;
  version: number;
}

interface QuestionSet {
  id: string | null;
  candidate_vacancy_id: string | null;
  round_id: string | null;
  /** HRP-444: assessment round this set prepares, if any. */
  assessment_round_id: string | null;
  set_type: SetType;
  name: string;
  status: SetStatus;
  generation_mode: GenerationMode;
  source_round_ids: string[] | null;
  coverage_note: string | null;
  archived_at: string | null;
  version: number;
  created_at: string | null;
  questions: QuestionRow[];
}

interface VacancyOption {
  id: string;
  title: string;
  candidate_vacancy_id: string;
  has_parsed_resume?: boolean;
}

interface Props {
  candidateId: string;
  vacancyOptions: VacancyOption[];
  initialVacancyId?: string;
  /** HRP-460: set id from the notification deep link, if any. */
  initialQuestionSetId?: string;
}

const GENERATE_ACTION = "recruitment.generate_question_set";

// HRP-476: module-scope maps hold i18n keys in the ``recruitment``
// namespace; every consumer resolves them with its own ``t``.
const SOURCE_META: Record<
  QuestionSource,
  { labelKey: string; icon: typeof Bot; tint: string }
> = {
  ai_generated: {
    labelKey: "questionSetsSourceAi",
    icon: Bot,
    tint: "text-sky-600",
  },
  manual: {
    labelKey: "questionSetsSourceManual",
    icon: Pin,
    tint: "text-amber-600",
  },
  from_competency_indicator: {
    labelKey: "questionSetsSourceIndicator",
    icon: Target,
    tint: "text-violet-600",
  },
  from_blind_spot: {
    labelKey: "questionSetsSourceBlindSpot",
    icon: Lightbulb,
    tint: "text-rose-600",
  },
};

const PRIORITY_BADGE: Record<QuestionPriority, string> = {
  must_ask: BADGE_COLOR.rose,
  should_ask: BADGE_COLOR.amber,
  nice_to_ask: BADGE_COLOR.emerald,
};

function activeQuestions(set: QuestionSet): QuestionRow[] {
  return set.questions.filter((q) => q.status === "active");
}

export function InterviewQuestionSets({
  candidateId,
  vacancyOptions,
  initialVacancyId,
  initialQuestionSetId,
}: Props) {
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const [vacancyId, setVacancyId] = useState<string | undefined>(
    initialVacancyId || vacancyOptions[0]?.id,
  );
  const [sets, setSets] = useState<QuestionSet[]>([]);
  const [activeSetId, setActiveSetId] = useState<string | null>(null);
  // HRP-460: the notification deep link names one set to open. It is
  // consumed once — the query param is never cleared from the URL, so
  // re-reading it on every load pinned the user to that tab for good.
  const pendingDeepLinkSet = useRef<string | null>(
    initialQuestionSetId ?? null,
  );
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const {
    isSaas,
    cost: generateCost,
    balance: creditBalance,
    insufficient,
    refresh: refreshBalance,
  } = useCreditGate(GENERATE_ACTION);
  const [sample, setSample] = useState<QuestionSet | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [competencyOpen, setCompetencyOpen] = useState(false);
  // HRP-485 / HRP-503: the vacancy profile backs both the competency
  // picker and the competence name shown on each question.
  const [competences, setCompetences] = useState<CompetenceItem[]>([]);
  const [exportOpen, setExportOpen] = useState(false);
  const [regenerateConfirm, setRegenerateConfirm] = useState(false);
  const [deleteId, setDeleteId] = useState<string | null>(null);
  // Transcribed interviews for this candidate-vacancy: what a next-round
  // set can be built on. HRP-444 keeps the whole row rather than the id —
  // the New set dialog has to name each interview, and the set header has
  // to say which transcripts a set was built on.
  const [transcribed, setTranscribed] = useState<TranscribedInterviewRow[]>([]);
  // HRP-444: assessment rounds (Manager assessments block) a new set can
  // be bound to.
  const [rounds, setRounds] = useState<AssessmentRoundRow[]>([]);
  const [newSetOpen, setNewSetOpen] = useState(false);

  const currentVacancy = useMemo(
    () => vacancyOptions.find((v) => v.id === vacancyId),
    [vacancyOptions, vacancyId],
  );

  useEffect(() => {
    const cvId = currentVacancy?.candidate_vacancy_id;
    if (!cvId) {
      setTranscribed([]);
      setRounds([]);
      return;
    }
    let cancelled = false;
    api
      .get<TranscribedInterviewRow[]>(
        `/recruitment/candidate-vacancies/${cvId}/interviews`,
      )
      .then((rows) => {
        if (cancelled) return;
        setTranscribed(transcribedInterviews(rows));
      })
      .catch(() => {
        if (!cancelled) setTranscribed([]);
      });
    // HRP-444: rounds decide what a new set can be bound to. A failure
    // here only costs the "existing round" options — the dialog can
    // still open the next round itself.
    api
      .get<AssessmentRoundRow[]>(
        `/v1/candidate-vacancies/${cvId}/assessment-rounds`,
      )
      .then((rows) => {
        if (!cancelled) setRounds(Array.isArray(rows) ? rows : []);
      })
      .catch(() => {
        if (!cancelled) setRounds([]);
      });
    return () => {
      cancelled = true;
    };
  }, [currentVacancy?.candidate_vacancy_id]);

  useEffect(() => {
    if (!vacancyId) {
      setCompetences([]);
      return;
    }
    let cancelled = false;
    api
      .get<{
        profile_data?: { competences?: CompetenceItem[] };
      }>(`/recruitment/vacancies/${vacancyId}/profile`)
      .then((profile) => {
        if (cancelled) return;
        const items = profile?.profile_data?.competences;
        setCompetences(Array.isArray(items) ? items : []);
      })
      .catch(() => {
        if (!cancelled) setCompetences([]);
      });
    return () => {
      cancelled = true;
    };
  }, [vacancyId]);

  // HRP-503: questions store a normalized competence UUID; the profile
  // is the only place the human-readable name lives. AI profiles key
  // competences by slug, so index both forms.
  const competenceNames = useMemo(() => {
    const m = new Map<string, string>();
    for (const c of competences) {
      if (c.id) m.set(String(c.id), c.name);
    }
    return m;
  }, [competences]);

  const loadSets = useCallback(async () => {
    if (!vacancyId) {
      setSets([]);
      return;
    }
    setLoading(true);
    try {
      const params = new URLSearchParams({ vacancy_id: vacancyId });
      const data = await api.get<QuestionSet[]>(
        `/v1/candidates/${candidateId}/question-sets?${params}`,
      );
      const ours = data.filter((s) => s.archived_at === null);
      setSets(ours);
      // A deep link wins once; after that the user's tab clicks do.
      const deepLink = pendingDeepLinkSet.current;
      if (deepLink && ours.some((s) => s.id === deepLink)) {
        pendingDeepLinkSet.current = null;
        setActiveSetId(deepLink);
        return;
      }
      // Functional update on purpose: reading `activeSetId` here would put
      // it in this callback's deps, and the effect below would then refetch
      // the whole list (loading flash included) on every tab click.
      setActiveSetId((prev) =>
        ours.some((s) => s.id === prev) ? prev : (ours[0]?.id ?? null),
      );
    } catch {
      setSets([]);
      setActiveSetId(null);
    } finally {
      setLoading(false);
    }
  }, [candidateId, vacancyId]);

  useEffect(() => {
    loadSets();
  }, [loadSets]);

  const currentSet =
    sample ?? sets.find((s) => s.id === activeSetId) ?? null;

  const interviewLabels = useMemo(() => {
    const m = new Map<string, string>();
    for (const iv of transcribed) {
      m.set(iv.id, interviewLabel(iv, t, formatDate));
    }
    return m;
  }, [transcribed, t]);

  // HRP-444: "Generated {date} by AI · Based on resume + transcripts of
  // Interview 1". Hand-built and sample sets have no generation story to
  // tell, so they get no subtitle.
  const setSubtitle = useMemo(() => {
    if (!currentSet || currentSet.status === "sample") return null;
    if (currentSet.generation_mode === "manual" || !currentSet.created_at) {
      return null;
    }
    const date = formatDate(currentSet.created_at);
    const names = setSourceInterviewIds(currentSet)
      .map((id) => interviewLabels.get(id))
      .filter((n): n is string => Boolean(n));
    if (!names.length) return t("questionSetsGeneratedSubtitle", { date });
    return t("questionSetsGeneratedSubtitleFrom", {
      date,
      rounds: names.join(", "),
    });
  }, [currentSet, interviewLabels, t]);

  // Which round a derived question follows from — the same transcripts
  // the set header names.
  const followsFromLabel = useMemo(() => {
    if (!currentSet) return undefined;
    const names = setSourceInterviewIds(currentSet)
      .map((id) => interviewLabels.get(id))
      .filter((n): n is string => Boolean(n));
    return names.length ? names.join(", ") : undefined;
  }, [currentSet, interviewLabels]);

  // Credit copy only renders on SaaS builds where billing is active; the
  // number is server-priced so it stays in sync with backend/ee/credits.yaml.
  const creditSuffix =
    isSaas && generateCost !== null
      ? t("questionSetsCreditSuffix", { cost: generateCost })
      : "";

  async function handleSample() {
    try {
      const s = await api.get<QuestionSet>("/v1/question-sets/sample");
      setSample(s);
      toast.message(t("questionSetsToastSampleMode"));
    } catch {
      toast.error(t("questionSetsSampleLoadFailed"));
    }
  }

  async function runGeneration(body: Record<string, unknown>): Promise<boolean> {
    const cvId = currentVacancy?.candidate_vacancy_id;
    if (!cvId) return false;
    setGenerating(true);
    try {
      const created = await api.post<QuestionSet>(
        `/v1/candidate-vacancies/${cvId}/question-sets`,
        body,
      );
      setSample(null);
      setSets((prev) => {
        const filtered = prev.filter((s) => s.id !== created.id);
        return [created, ...filtered];
      });
      setActiveSetId(created.id);
      toast.success(t("questionSetsToastReady"));
      refreshBalance();
      return true;
    } catch (err) {
      const msg =
        err && typeof err === "object" && "message" in err
          ? String((err as { message: unknown }).message)
          : t("questionSetsGenerateFailed");
      toast.error(msg);
      return false;
    } finally {
      setGenerating(false);
    }
  }

  async function handleGenerate(mode: GenerationMode) {
    const body: Record<string, unknown> = { mode, set_type: "pre_interview" };
    if (mode === "regenerated" && currentSet?.id) {
      body.target_set_id = currentSet.id;
    }
    await runGeneration(body);
  }

  // HRP-444: the New set dialog has already resolved the round and the
  // transcript, so this only ships the choice and re-reads the rounds —
  // one of them may have just been opened by the server.
  async function handleGenerateNext(selection: NewSetSelection) {
    const cvId = currentVacancy?.candidate_vacancy_id;
    const ok = await runGeneration(buildNewSetBody(selection));
    if (!ok) return;
    setNewSetOpen(false);
    if (!cvId) return;
    try {
      const rows = await api.get<AssessmentRoundRow[]>(
        `/v1/candidate-vacancies/${cvId}/assessment-rounds`,
      );
      setRounds(Array.isArray(rows) ? rows : []);
    } catch {
      // Non-fatal: the set is generated either way.
    }
  }

  async function postQuestions(payloads: NewQuestionPayload[]) {
    if (!currentSet?.id || !payloads.length) return;
    const setId = currentSet.id;
    try {
      // Sequential on purpose: sort_order is derived server-side from
      // the current max, so parallel posts would collide on it.
      const created: QuestionRow[] = [];
      for (const payload of payloads) {
        created.push(
          await api.post<QuestionRow>(
            `/v1/question-sets/${setId}/questions`,
            payload,
          ),
        );
      }
      setSets((prev) =>
        prev.map((s) =>
          s.id === setId ? { ...s, questions: [...s.questions, ...created] } : s,
        ),
      );
      toast.success(
        t("questionSetsToastAddedCount", { count: created.length }),
      );
      setAddOpen(false);
      setCompetencyOpen(false);
    } catch (err) {
      const msg =
        err && typeof err === "object" && "message" in err
          ? String((err as { message: unknown }).message)
          : t("questionSetsAddFailed");
      toast.error(msg);
    }
  }

  async function handleToggleCovered(q: QuestionRow) {
    if (!q.id) return;
    const nextCovered = !q.covered_at;
    try {
      const updated = await api.patch<QuestionRow>(`/v1/questions/${q.id}`, {
        covered: nextCovered,
      });
      setSets((prev) =>
        prev.map((s) =>
          s.id === q.question_set_id
            ? {
                ...s,
                questions: s.questions.map((it) =>
                  it.id === q.id ? updated : it,
                ),
              }
            : s,
        ),
      );
    } catch {
      toast.error(t("questionSetsUpdateFailed"));
    }
  }

  async function handleEdit(q: QuestionRow, patch: Partial<QuestionRow>) {
    if (!q.id) return;
    try {
      const updated = await api.patch<QuestionRow>(`/v1/questions/${q.id}`, patch);
      setSets((prev) =>
        prev.map((s) =>
          s.id === q.question_set_id
            ? {
                ...s,
                questions: s.questions.map((it) =>
                  it.id === q.id ? updated : it,
                ),
              }
            : s,
        ),
      );
    } catch {
      toast.error(t("questionSetsSaveFailed"));
    }
  }

  async function confirmDelete() {
    if (!deleteId) return;
    try {
      await api.delete(`/v1/questions/${deleteId}`);
      setSets((prev) =>
        prev.map((s) => ({
          ...s,
          questions: s.questions.map((q) =>
            q.id === deleteId ? { ...q, status: "removed" as const } : q,
          ),
        })),
      );
      toast.success(t("questionSetsToastDeleted"));
    } catch {
      toast.error(t("questionSetsDeleteFailed"));
    } finally {
      setDeleteId(null);
    }
  }

  const resumeMissing = currentVacancy?.has_parsed_resume === false;

  return (
    <section
      id="interview-questions"
      data-testid="recruitment-interview-questions-section"
      className="space-y-3"
    >
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Sparkles className="h-5 w-5 text-sky-600" />
          <h2 className="text-lg font-semibold">{t("questionSetsTitle")}</h2>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {vacancyOptions.length > 1 && (
            <Select value={vacancyId} onValueChange={setVacancyId}>
              <SelectTrigger
                className="w-64"
                data-testid="recruitment-interview-questions-vacancy-select"
              >
                <SelectValue placeholder={t("questionSetsSelectVacancy")}>
                  {(value) =>
                    vacancyOptions.find((v) => v.id === value)?.title ??
                    t("questionSetsSelectVacancy")
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
          )}
        </div>
      </header>

      {sets.length > 0 && !sample && (
        <div
          role="tablist"
          aria-label={t("questionSetsTablistAria")}
          className="flex flex-wrap items-center gap-1 border-b"
          data-testid="recruitment-interview-questions-tabbar"
        >
          {sets.map((s) => (
            <button
              key={s.id || s.name}
              type="button"
              role="tab"
              aria-selected={activeSetId === s.id}
              onClick={() => setActiveSetId(s.id)}
              data-testid={`recruitment-interview-questions-tab-${s.id}`}
              className={`-mb-px border-b-2 px-3 py-2 text-sm transition ${
                activeSetId === s.id
                  ? "border-sky-500 text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              {s.name}
              <span className="ml-1 text-xs text-muted-foreground">
                ({activeQuestions(s).length})
              </span>
            </button>
          ))}
          {/* HRP-444: a second set is never another from-scratch
              pre-interview set — the dialog resolves which round it is
              for and which transcript it builds on. */}
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setNewSetOpen(true)}
            disabled={generating || resumeMissing || insufficient}
            data-testid="recruitment-interview-questions-new-set-btn"
          >
            {generating ? (
              <Loader2 className="mr-1 h-4 w-4 animate-spin" />
            ) : (
              <Plus className="mr-1 h-4 w-4" />
            )}
            {generating ? t("questionSetsGenerating") : t("questionSetsNewSet")}
          </Button>
        </div>
      )}

      {loading ? (
        <p className="text-sm text-muted-foreground">{t("loading")}</p>
      ) : !sets.length && !sample ? (
        <EmptyState
          resumeMissing={Boolean(resumeMissing)}
          insufficient={insufficient}
          generating={generating}
          balance={creditBalance}
          cost={generateCost}
          showCredits={isSaas}
          onGenerate={() => handleGenerate("initial")}
          onSample={handleSample}
        />
      ) : currentSet ? (
        <Card>
          <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
            <div className="space-y-1">
              <CardTitle className="flex items-center gap-2 text-base">
                {currentSet.name}
                <Badge
                  variant="outline"
                  className="text-xs uppercase tracking-wide"
                  data-testid="recruitment-interview-questions-mode-badge"
                >
                  {questionSetGenerationModeLabel(
                    t,
                    currentSet.generation_mode,
                  )}
                </Badge>
                {currentSet.status === "sample" && (
                  <Badge variant="secondary">
                    {t("questionSetsSampleBadge")}
                  </Badge>
                )}
              </CardTitle>
              {/* HRP-444: say when the set was made and what it was
                  made from, so a round set is distinguishable from the
                  pre-interview one at a glance. */}
              {setSubtitle && (
                <p
                  className="text-xs text-muted-foreground"
                  data-testid="recruitment-interview-questions-set-subtitle"
                >
                  {setSubtitle}
                </p>
              )}
              {currentSet.coverage_note && (
                <p
                  className="text-xs text-muted-foreground"
                  data-testid="recruitment-interview-questions-coverage-note"
                >
                  {currentSet.coverage_note}
                </p>
              )}
            </div>
            <div className="flex items-center gap-2">
              {currentSet.status !== "sample" && (
                <>
                  {/* HRP-485 task 1: split button — the primary half
                      opens the custom-question dialog, the caret offers
                      both entry points explicitly. */}
                  <span className="inline-flex">
                    <Button
                      variant="outline"
                      size="sm"
                      className="rounded-r-none"
                      onClick={() => setAddOpen(true)}
                      data-testid="recruitment-interview-questions-add-btn"
                    >
                      <Plus className="mr-1 h-4 w-4" />
                      {t("questionSetsAdd")}
                    </Button>
                    <DropdownMenu>
                      <DropdownMenuTrigger
                        data-testid="recruitment-interview-questions-add-menu-btn"
                        aria-label={t("questionSetsAddMenuAria")}
                        render={
                          <Button
                            variant="outline"
                            size="sm"
                            className="rounded-l-none border-l-0 px-2"
                          />
                        }
                      >
                        <ChevronDown className="h-4 w-4" />
                      </DropdownMenuTrigger>
                      <DropdownMenuContent
                        align="end"
                        data-testid="recruitment-interview-questions-add-menu"
                      >
                        <DropdownMenuItem
                          onClick={() => setAddOpen(true)}
                          data-testid="recruitment-interview-questions-add-custom-item"
                        >
                          {t("questionSetsAddMenuCustom")}
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          onClick={() => setCompetencyOpen(true)}
                          data-testid="recruitment-interview-questions-add-competency-item"
                        >
                          {t("questionSetsAddMenuFromCompetency")}
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </span>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setRegenerateConfirm(true)}
                    disabled={generating || insufficient}
                    data-testid="recruitment-interview-questions-regenerate-btn"
                  >
                    <RefreshCw className="mr-1 h-4 w-4" />
                    {t("questionSetsRegenerate")}
                    {creditSuffix}
                  </Button>
                  {/* HRP-484 task 2: export covers the current set only,
                      so the action belongs to the set card, not the
                      section header. */}
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setExportOpen(true)}
                    data-testid="recruitment-interview-questions-export-btn"
                  >
                    <Download className="mr-1 h-4 w-4" />
                    {t("questionSetsExportPdf")}
                  </Button>
                </>
              )}
            </div>
          </CardHeader>
          <CardContent className="space-y-2">
            {activeQuestions(currentSet).length === 0 ? (
              <p className="text-sm text-muted-foreground">
                {t("questionSetsSetEmpty")}
              </p>
            ) : (
              activeQuestions(currentSet).map((q) => (
                <QuestionItem
                  key={q.id || `${q.sort_order}-${q.text.slice(0, 8)}`}
                  question={q}
                  readOnly={currentSet.status === "sample"}
                  competenceName={
                    q.competence_id
                      ? competenceNames.get(String(q.competence_id))
                      : undefined
                  }
                  competences={competences}
                  followsFrom={
                    q.source === "from_blind_spot" ? followsFromLabel : undefined
                  }
                  onToggleCovered={() => handleToggleCovered(q)}
                  onEdit={(patch) => handleEdit(q, patch)}
                  onDelete={() => q.id && setDeleteId(q.id)}
                />
              ))
            )}
          </CardContent>
        </Card>
      ) : null}

      <NewQuestionSetDialog
        open={newSetOpen}
        onOpenChange={setNewSetOpen}
        rounds={rounds}
        interviews={transcribed}
        sets={sets}
        generating={generating}
        costSuffix={creditSuffix}
        onSubmit={handleGenerateNext}
      />

      <AddQuestionDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        onSubmit={(payload) => postQuestions([payload])}
      />

      <AddFromCompetencyDialog
        open={competencyOpen}
        onOpenChange={setCompetencyOpen}
        competences={competences}
        onSubmit={postQuestions}
      />

      <ExportDialog
        open={exportOpen}
        onOpenChange={setExportOpen}
        setId={currentSet?.id || null}
        setName={currentSet?.name || "set"}
      />

      <ConfirmDialog
        open={regenerateConfirm}
        onOpenChange={(o) => !o && setRegenerateConfirm(false)}
        title={t("questionSetsRegenerateTitle")}
        description={
          isSaas && generateCost !== null
            ? t("questionSetsRegenerateDescriptionCost", {
                cost: generateCost,
              })
            : t("questionSetsRegenerateDescription")
        }
        confirmLabel={t("questionSetsRegenerate")}
        cancelLabel={tc("cancel")}
        onConfirm={() => {
          setRegenerateConfirm(false);
          handleGenerate("regenerated");
        }}
        testId="recruitment-interview-questions-regenerate-confirm"
      />

      <ConfirmDialog
        open={deleteId !== null}
        onOpenChange={(o) => !o && setDeleteId(null)}
        title={t("questionSetsDeleteTitle")}
        description={t("questionSetsDeleteDescription")}
        confirmLabel={tc("delete")}
        cancelLabel={tc("cancel")}
        destructive
        onConfirm={confirmDelete}
        testId="recruitment-interview-questions-delete-confirm"
      />
    </section>
  );
}

interface EmptyStateProps {
  resumeMissing: boolean;
  insufficient: boolean;
  generating: boolean;
  balance: number | null;
  cost: number | null;
  showCredits: boolean;
  onGenerate: () => void;
  onSample: () => void;
}

function EmptyState({
  resumeMissing,
  insufficient,
  generating,
  balance,
  cost,
  showCredits,
  onGenerate,
  onSample,
}: EmptyStateProps) {
  const t = useTranslations("recruitment");
  const withCredits = showCredits && cost !== null;
  return (
    <div
      className="rounded-lg border border-dashed p-10 text-center"
      data-testid="recruitment-interview-questions-empty"
    >
      <FileQuestion className="mx-auto mb-3 h-10 w-10 text-muted-foreground/50" />
      <p className="text-sm font-medium">{t("questionSetsEmptyTitle")}</p>
      <p className="mt-1 text-xs text-muted-foreground">
        {resumeMissing
          ? t("questionSetsEmptyResumeMissing")
          : insufficient
            ? t("questionSetsEmptyInsufficient", {
                cost: cost ?? 0,
                balance: balance ?? 0,
              })
            : t("questionSetsEmptyDefault")}
      </p>
      <div className="mt-4 flex items-center justify-center gap-2">
        <Button
          onClick={onGenerate}
          disabled={resumeMissing || insufficient || generating}
          data-testid="recruitment-interview-questions-generate-btn"
        >
          {generating ? (
            t("questionSetsGenerating")
          ) : (
            <>
              <Sparkles className="mr-1 h-4 w-4" />
              {withCredits
                ? t("questionSetsGenerateFirstSetCost", { cost: cost ?? 0 })
                : t("questionSetsGenerateFirstSet")}
            </>
          )}
        </Button>
        {insufficient && (
          <Button
            variant="outline"
            onClick={onSample}
            data-testid="recruitment-interview-questions-sample-btn"
          >
            {t("questionSetsViewSample")}
          </Button>
        )}
      </div>
    </div>
  );
}

interface QuestionItemProps {
  question: QuestionRow;
  readOnly: boolean;
  /** HRP-503: resolved from the vacancy profile; absent when unlinked. */
  competenceName?: string;
  /** HRP-487: options for the inline competence picker. */
  competences: CompetenceItem[];
  /** HRP-444: round label this question follows from, if it derives. */
  followsFrom?: string;
  onToggleCovered: () => void;
  onEdit: (patch: Partial<QuestionRow>) => void;
  onDelete: () => void;
}

// HRP-487: the pencil used to reveal only the question text. The draft
// below carries every editable attribute; ``source`` is deliberately
// absent — it records where the question came from and is not a user
// choice.
interface QuestionDraft {
  text: string;
  goal: QuestionGoal;
  priority: QuestionPriority;
  competenceId: string;
  resumeAnchor: string;
  indicators: string;
  followUps: string;
  rationale: string;
}

const UNLINKED = "__none__";

function toDraft(q: QuestionRow): QuestionDraft {
  return {
    text: q.text,
    goal: q.goal,
    priority: q.priority,
    competenceId: q.competence_id ? String(q.competence_id) : UNLINKED,
    resumeAnchor: q.resume_anchor_jsonb?.quote || "",
    indicators: (q.expected_answer_indicators || []).join("\n"),
    followUps: (q.follow_ups || []).join("\n"),
    rationale: q.rationale || "",
  };
}

function toLines(value: string): string[] {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

function QuestionItem({
  question,
  readOnly,
  competenceName,
  competences,
  followsFrom,
  onToggleCovered,
  onEdit,
  onDelete,
}: QuestionItemProps) {
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const [expanded, setExpanded] = useState(false);
  const edit = useInlineEdit<QuestionDraft>(() => toDraft(question));

  const meta = SOURCE_META[question.source];
  const Icon = meta.icon;

  function commitEdit() {
    const text = edit.draft.text.trim();
    if (!text) {
      toast.error(t("questionSetsTextRequiredInline"));
      return;
    }
    onEdit({
      text,
      goal: edit.draft.goal,
      priority: edit.draft.priority,
      competence_id:
        edit.draft.competenceId === UNLINKED ? null : edit.draft.competenceId,
      expected_answer_indicators: toLines(edit.draft.indicators),
      follow_ups: toLines(edit.draft.followUps),
      rationale: edit.draft.rationale.trim() || null,
      resume_anchor_jsonb: edit.draft.resumeAnchor.trim()
        ? { quote: edit.draft.resumeAnchor.trim(), section: null }
        : null,
    });
    edit.close();
  }

  const keyHandler = inlineEditKeys<HTMLDivElement>({
    onCommit: commitEdit,
    onCancel: edit.cancel,
  });

  if (edit.editing) {
    return (
      <div
        className="space-y-3 rounded-md border bg-card p-3"
        onKeyDown={keyHandler}
        data-testid={`recruitment-interview-question-editor-${question.id}`}
      >
        <div>
          <Label htmlFor={`qe-text-${question.id}`}>
            {t("questionSetsFieldQuestion")}
          </Label>
          <Textarea
            id={`qe-text-${question.id}`}
            autoFocus
            rows={3}
            value={edit.draft.text}
            maxLength={QUESTION_TEXT_MAX}
            onChange={(e) => edit.setDraft({ ...edit.draft, text: e.target.value })}
            data-testid={`recruitment-interview-question-edit-${question.id}`}
          />
        </div>

        <div className="grid gap-3 sm:grid-cols-3">
          <div>
            <Label>{t("questionSetsFieldGoal")}</Label>
            <Select
              value={edit.draft.goal}
              onValueChange={(v) =>
                edit.setDraft({ ...edit.draft, goal: v as QuestionGoal })
              }
            >
              <SelectTrigger
                className="w-full"
                data-testid={`recruitment-interview-question-edit-goal-${question.id}`}
              >
                <SelectValue>{t(GOAL_LABEL_KEYS[edit.draft.goal])}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                {Object.entries(GOAL_LABEL_KEYS).map(([k, labelKey]) => (
                  <SelectItem key={k} value={k}>
                    {t(labelKey)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label>{t("questionSetsFieldPriority")}</Label>
            <Select
              value={edit.draft.priority}
              onValueChange={(v) =>
                edit.setDraft({ ...edit.draft, priority: v as QuestionPriority })
              }
            >
              <SelectTrigger
                className="w-full"
                data-testid={`recruitment-interview-question-edit-priority-${question.id}`}
              >
                <SelectValue>
                  {t(PRIORITY_LABEL_KEYS[edit.draft.priority])}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {Object.entries(PRIORITY_LABEL_KEYS).map(([k, labelKey]) => (
                  <SelectItem key={k} value={k}>
                    {t(labelKey)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label>{t("questionSetsCompetence")}</Label>
            <Select
              value={edit.draft.competenceId}
              onValueChange={(v) =>
                edit.setDraft({ ...edit.draft, competenceId: v })
              }
            >
              <SelectTrigger
                className="w-full"
                data-testid={`recruitment-interview-question-edit-competence-${question.id}`}
              >
                <SelectValue>
                  {edit.draft.competenceId === UNLINKED
                    ? t("questionSetsCompetenceUnlinked")
                    : competences.find(
                        (c) => String(c.id) === edit.draft.competenceId,
                      )?.name || competenceName || t("questionSetsCompetence")}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={UNLINKED}>
                  {t("questionSetsCompetenceUnlinked")}
                </SelectItem>
                {competences
                  .filter((c) => Boolean(c.id))
                  .map((c) => (
                    <SelectItem key={String(c.id)} value={String(c.id)}>
                      {c.name}
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        <div>
          <Label htmlFor={`qe-anchor-${question.id}`}>
            {t("questionSetsFieldResumeAnchor")}
          </Label>
          <Textarea
            id={`qe-anchor-${question.id}`}
            rows={2}
            value={edit.draft.resumeAnchor}
            onChange={(e) =>
              edit.setDraft({ ...edit.draft, resumeAnchor: e.target.value })
            }
            data-testid={`recruitment-interview-question-edit-anchor-${question.id}`}
          />
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <Label htmlFor={`qe-ind-${question.id}`}>
              {t("questionSetsExpectedIndicators")}
            </Label>
            <Textarea
              id={`qe-ind-${question.id}`}
              rows={3}
              value={edit.draft.indicators}
              onChange={(e) =>
                edit.setDraft({ ...edit.draft, indicators: e.target.value })
              }
              data-testid={`recruitment-interview-question-edit-indicators-${question.id}`}
            />
            <p className="mt-1 text-xs text-muted-foreground">
              {t("questionSetsOnePerLine")}
            </p>
          </div>
          <div>
            <Label htmlFor={`qe-fu-${question.id}`}>
              {t("questionSetsFollowUps")}
            </Label>
            <Textarea
              id={`qe-fu-${question.id}`}
              rows={3}
              value={edit.draft.followUps}
              onChange={(e) =>
                edit.setDraft({ ...edit.draft, followUps: e.target.value })
              }
              data-testid={`recruitment-interview-question-edit-followups-${question.id}`}
            />
            <p className="mt-1 text-xs text-muted-foreground">
              {t("questionSetsOnePerLine")}
            </p>
          </div>
        </div>

        <div>
          <Label htmlFor={`qe-rat-${question.id}`}>
            {t("questionSetsWhyThisQuestion")}
          </Label>
          <Textarea
            id={`qe-rat-${question.id}`}
            rows={2}
            value={edit.draft.rationale}
            onChange={(e) =>
              edit.setDraft({ ...edit.draft, rationale: e.target.value })
            }
            data-testid={`recruitment-interview-question-edit-rationale-${question.id}`}
          />
        </div>

        <div className="flex justify-end gap-2">
          <Button variant="outline" size="sm" onClick={edit.cancel}>
            {tc("cancel")}
          </Button>
          <Button
            size="sm"
            onClick={commitEdit}
            data-testid={`recruitment-interview-question-edit-save-${question.id}`}
          >
            {t("questionSetsSaveQuestion")}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div
      className="rounded-md border bg-card p-3"
      data-testid={`recruitment-interview-question-${question.id ?? "preview"}`}
    >
      <div className="flex items-start gap-2">
        <button
          type="button"
          onClick={onToggleCovered}
          disabled={readOnly}
          aria-label={
            question.covered_at
              ? t("questionSetsMarkNotCovered")
              : t("questionSetsMarkCovered")
          }
          className={`mt-0.5 inline-flex h-5 w-5 items-center justify-center rounded-full border ${
            question.covered_at
              ? "border-emerald-500 bg-emerald-500 text-white"
              : "border-muted-foreground/40 text-transparent"
          }`}
          data-testid={`recruitment-interview-question-cover-${question.id ?? "preview"}`}
        >
          <Check className="h-3.5 w-3.5" />
        </button>

        {/* Source stays a read-only icon — see QuestionDraft. */}
        <Icon
          className={`mt-0.5 h-4 w-4 shrink-0 ${meta.tint}`}
          aria-label={t(meta.labelKey)}
        />

        <div className="min-w-0 flex-1 space-y-1">
          <button
            type="button"
            className={`block w-full text-left text-sm leading-snug ${
              question.covered_at ? "text-muted-foreground line-through" : ""
            }`}
            onClick={() => setExpanded((v) => !v)}
          >
            {question.text}
          </button>
          <div className="flex flex-wrap items-center gap-1.5 text-xs">
            <Badge
              variant="secondary"
              className={PRIORITY_BADGE[question.priority]}
            >
              {PRIORITY_LABEL_KEYS[question.priority]
                ? t(PRIORITY_LABEL_KEYS[question.priority])
                : question.priority}
            </Badge>
            <Badge variant="outline">
              {GOAL_LABEL_KEYS[question.goal]
                ? t(GOAL_LABEL_KEYS[question.goal])
                : question.goal}
            </Badge>
            {/* HRP-444: a question raised by the previous round says so,
                so it reads as a follow-up rather than a fresh idea. */}
            {followsFrom && (
              <span
                className="text-[11px] text-muted-foreground underline decoration-dotted"
                data-testid={`recruitment-interview-question-follows-from-${question.id ?? "preview"}`}
              >
                {t("questionSetsFollowsFrom", { round: followsFrom })}
              </span>
            )}
            {/* HRP-503: which profile competence this question probes. */}
            {competenceName && (
              <Badge
                variant="secondary"
                title={t("questionSetsCompetence")}
                data-testid={`recruitment-interview-question-competence-${question.id ?? "preview"}`}
              >
                {competenceName}
              </Badge>
            )}
            {question.resume_anchor_jsonb?.quote && (
              <span
                className="truncate text-muted-foreground"
                title={question.resume_anchor_jsonb.quote}
              >
                {t("questionSetsResumeAnchor", {
                  quote:
                    question.resume_anchor_jsonb.quote.slice(0, 60) +
                    (question.resume_anchor_jsonb.quote.length > 60 ? "…" : ""),
                })}
              </span>
            )}
            {question.covered_method === "auto_from_transcript" && (
              <Badge variant="secondary" className="text-[10px]">
                {t("questionSetsAutoCovered")}
              </Badge>
            )}
          </div>
          {expanded && (
            <div
              className="mt-2 space-y-2 rounded-md bg-muted/40 p-2 text-xs"
              data-testid={`recruitment-interview-question-detail-${question.id ?? "preview"}`}
            >
              {question.expected_answer_indicators.length > 0 && (
                <div>
                  <p className="font-medium">
                    {t("questionSetsExpectedIndicators")}
                  </p>
                  <ul className="ml-4 list-disc">
                    {question.expected_answer_indicators.map((i, idx) => (
                      <li key={idx}>{i}</li>
                    ))}
                  </ul>
                </div>
              )}
              {question.follow_ups.length > 0 && (
                <div>
                  <p className="font-medium">{t("questionSetsFollowUps")}</p>
                  <ul className="ml-4 list-disc">
                    {question.follow_ups.map((f, idx) => (
                      <li key={idx}>{f}</li>
                    ))}
                  </ul>
                </div>
              )}
              {question.rationale && (
                <div>
                  <p className="font-medium">
                    {t("questionSetsWhyThisQuestion")}
                  </p>
                  <p className="text-muted-foreground">{question.rationale}</p>
                </div>
              )}
            </div>
          )}
        </div>

        {!readOnly && (
          <div className="flex shrink-0 items-center gap-1">
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={() => edit.start(toDraft(question))}
              aria-label={t("questionSetsEditQuestionAria")}
              data-testid={`recruitment-interview-question-edit-btn-${question.id}`}
            >
              <PencilLine className="h-3.5 w-3.5" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={onDelete}
              aria-label={t("questionSetsDeleteQuestionAria")}
              data-testid={`recruitment-interview-question-delete-btn-${question.id}`}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={() => setExpanded((v) => !v)}
              aria-label={t("questionSetsToggleDetails")}
            >
              <ChevronDown
                className={`h-3.5 w-3.5 transition ${expanded ? "rotate-180" : ""}`}
              />
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

interface AddQuestionDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (payload: NewQuestionPayload) => void;
}

/**
 * HRP-485 task 2: the "Add custom question" form. Source is fixed to
 * ``manual`` here — questions bound to a profile competence come from
 * AddFromCompetencyDialog instead, so the old free-choice Source select
 * is gone.
 */
function AddQuestionDialog({
  open,
  onOpenChange,
  onSubmit,
}: AddQuestionDialogProps) {
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const [text, setText] = useState("");
  const [goal, setGoal] = useState<QuestionGoal>("verify_skill");
  const [priority, setPriority] = useState<QuestionPriority>("should_ask");
  const [anchor, setAnchor] = useState("");

  function reset() {
    setText("");
    setGoal("verify_skill");
    setPriority("should_ask");
    setAnchor("");
  }

  const trimmed = text.trim();
  const lengthInvalid =
    trimmed.length < QUESTION_TEXT_MIN || trimmed.length > QUESTION_TEXT_MAX;

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) reset();
        onOpenChange(o);
      }}
    >
      <DialogContent
        className="max-w-lg"
        data-testid="recruitment-interview-questions-add-dialog"
      >
        <DialogHeader>
          <DialogTitle>{t("questionSetsAddDialogTitle")}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label htmlFor="q-text">{t("questionSetsFieldQuestion")}</Label>
            <Textarea
              id="q-text"
              rows={3}
              value={text}
              maxLength={QUESTION_TEXT_MAX}
              onChange={(e) => setText(e.target.value)}
              placeholder={t("questionSetsQuestionPlaceholder")}
              data-testid="recruitment-interview-questions-add-text"
            />
            <p className="mt-1 text-xs text-muted-foreground">
              {t("questionSetsTextLengthHint", {
                min: QUESTION_TEXT_MIN,
                max: QUESTION_TEXT_MAX,
                count: trimmed.length,
              })}
            </p>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>{t("questionSetsFieldGoal")}</Label>
              <Select
                value={goal}
                onValueChange={(v) => setGoal(v as QuestionGoal)}
              >
                <SelectTrigger
                  className="w-full"
                  data-testid="recruitment-interview-questions-add-goal"
                >
                  <SelectValue>{t(GOAL_LABEL_KEYS[goal])}</SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {Object.entries(GOAL_LABEL_KEYS).map(([k, labelKey]) => (
                    <SelectItem key={k} value={k}>
                      {t(labelKey)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>{t("questionSetsFieldPriority")}</Label>
              <Select
                value={priority}
                onValueChange={(v) => setPriority(v as QuestionPriority)}
              >
                <SelectTrigger
                  className="w-full"
                  data-testid="recruitment-interview-questions-add-priority"
                >
                  <SelectValue>{t(PRIORITY_LABEL_KEYS[priority])}</SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {Object.entries(PRIORITY_LABEL_KEYS).map(([k, labelKey]) => (
                    <SelectItem key={k} value={k}>
                      {t(labelKey)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div>
            <Label htmlFor="q-anchor">
              {t("questionSetsFieldResumeAnchor")}
            </Label>
            <Textarea
              id="q-anchor"
              rows={2}
              value={anchor}
              maxLength={RESUME_ANCHOR_MAX}
              onChange={(e) => setAnchor(e.target.value)}
              placeholder={t("questionSetsResumeAnchorPlaceholder")}
              data-testid="recruitment-interview-questions-add-anchor"
            />
            <p className="mt-1 text-xs text-muted-foreground">
              {t("questionSetsResumeAnchorHint", { max: RESUME_ANCHOR_MAX })}
            </p>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {tc("cancel")}
          </Button>
          <Button
            onClick={() => {
              if (lengthInvalid) {
                toast.error(
                  t("questionSetsTextLengthError", {
                    min: QUESTION_TEXT_MIN,
                    max: QUESTION_TEXT_MAX,
                  }),
                );
                return;
              }
              onSubmit({
                text: trimmed,
                goal,
                priority,
                competence_id: null,
                expected_answer_indicators: [],
                follow_ups: [],
                rationale: null,
                source: "manual",
                resume_anchor_jsonb: anchor.trim()
                  ? { quote: anchor.trim(), section: null }
                  : null,
              });
              reset();
            }}
            data-testid="recruitment-interview-questions-add-submit"
          >
            {t("questionSetsAddSubmit")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

interface ExportDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  setId: string | null;
  setName: string;
}

function ExportDialog({
  open,
  onOpenChange,
  setId,
  setName,
}: ExportDialogProps) {
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const [format, setFormat] = useState<"compact" | "full" | "cards">("full");
  const [includeIndicators, setIncludeIndicators] = useState(true);
  const [includeFollowUps, setIncludeFollowUps] = useState(true);
  const [includeRationale, setIncludeRationale] = useState(false);
  const [includeResumeAnchor, setIncludeResumeAnchor] = useState(true);
  const [sort, setSort] =
    useState<"priority" | "competence" | "sort_order">("sort_order");
  const [busy, setBusy] = useState(false);

  async function handleExport() {
    if (!setId) return;
    setBusy(true);
    try {
      const blob = await api
        .post<Blob>(`/v1/question-sets/${setId}/export-pdf`, {
          format,
          include_indicators: includeIndicators,
          include_follow_ups: includeFollowUps,
          include_rationale: includeRationale,
          include_resume_anchor: includeResumeAnchor,
          sort,
        })
        .catch(async () => {
          // Some api.post wrappers don't handle binary; fall back to fetch.
          const token =
            typeof window !== "undefined"
              ? localStorage.getItem("access_token")
              : null;
          const res = await fetch(
            `${process.env.NEXT_PUBLIC_API_URL || "/api"}/v1/question-sets/${setId}/export-pdf`,
            {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                ...(token ? { Authorization: `Bearer ${token}` } : {}),
              },
              body: JSON.stringify({
                format,
                include_indicators: includeIndicators,
                include_follow_ups: includeFollowUps,
                include_rationale: includeRationale,
                include_resume_anchor: includeResumeAnchor,
                sort,
              }),
            },
          );
          if (!res.ok) throw new Error("Export failed");
          return res.blob();
        });
      const url = URL.createObjectURL(blob as Blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${setName.replace(/\W+/g, "-")}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
      onOpenChange(false);
    } catch {
      toast.error(t("questionSetsExportFailed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="recruitment-interview-questions-export-dialog">
        <DialogHeader>
          <DialogTitle>{t("questionSetsExportDialogTitle")}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label>{t("questionSetsFieldFormat")}</Label>
            <Select
              value={format}
              onValueChange={(v) => setFormat(v as typeof format)}
            >
              <SelectTrigger
                className="w-full"
                data-testid="recruitment-interview-questions-export-format"
              >
                <SelectValue>
                  {format === "full"
                    ? t("questionSetsFormatFull")
                    : format === "cards"
                      ? t("questionSetsFormatCards")
                      : t("questionSetsFormatCompact")}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="compact">
                  {t("questionSetsFormatCompact")}
                </SelectItem>
                <SelectItem value="full">
                  {t("questionSetsFormatFull")}
                </SelectItem>
                <SelectItem value="cards">
                  {t("questionSetsFormatCards")}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label>{t("questionSetsFieldSort")}</Label>
            <Select
              value={sort}
              onValueChange={(v) => setSort(v as typeof sort)}
            >
              <SelectTrigger
                className="w-full"
                data-testid="recruitment-interview-questions-export-sort"
              >
                <SelectValue>
                  {sort === "priority"
                    ? t("questionSetsSortPriority")
                    : sort === "competence"
                      ? t("questionSetsSortCompetence")
                      : t("questionSetsSortDefault")}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="sort_order">
                  {t("questionSetsSortDefault")}
                </SelectItem>
                <SelectItem value="priority">
                  {t("questionSetsSortPriority")}
                </SelectItem>
                <SelectItem value="competence">
                  {t("questionSetsSortCompetence")}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
          {/* HRP-484 task 1.3: fixed order, top to bottom. */}
          <div className="space-y-2 text-sm">
            <label className="flex items-center gap-2">
              <Input
                type="checkbox"
                className="h-4 w-4"
                checked={includeResumeAnchor}
                onChange={(e) => setIncludeResumeAnchor(e.target.checked)}
                data-testid="recruitment-interview-questions-export-opt-anchor"
              />
              {t("questionSetsOptResumeAnchor")}
            </label>
            <label className="flex items-center gap-2">
              <Input
                type="checkbox"
                className="h-4 w-4"
                checked={includeIndicators}
                onChange={(e) => setIncludeIndicators(e.target.checked)}
                data-testid="recruitment-interview-questions-export-opt-indicators"
              />
              {t("questionSetsOptIndicators")}
            </label>
            <label className="flex items-center gap-2">
              <Input
                type="checkbox"
                className="h-4 w-4"
                checked={includeFollowUps}
                onChange={(e) => setIncludeFollowUps(e.target.checked)}
                data-testid="recruitment-interview-questions-export-opt-followups"
              />
              {t("questionSetsOptFollowUps")}
            </label>
            <label className="flex items-center gap-2">
              <Input
                type="checkbox"
                className="h-4 w-4"
                checked={includeRationale}
                onChange={(e) => setIncludeRationale(e.target.checked)}
                data-testid="recruitment-interview-questions-export-opt-rationale"
              />
              {t("questionSetsOptRationale")}
            </label>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {tc("cancel")}
          </Button>
          <Button
            onClick={handleExport}
            disabled={busy}
            data-testid="recruitment-interview-questions-export-submit"
          >
            {busy ? t("questionSetsExporting") : t("questionSetsDownloadPdf")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
