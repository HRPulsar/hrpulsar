"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import {
  Bot,
  Check,
  ChevronDown,
  Download,
  FileQuestion,
  Lightbulb,
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

type QuestionSource =
  | "ai_generated"
  | "manual"
  | "from_competency_indicator"
  | "from_blind_spot";
type QuestionPriority = "must" | "should" | "nice_to_ask";
type QuestionGoal = "clarification" | "depth" | "risk" | "motivation" | "fit";
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
}

const GENERATE_ACTION = "recruitment.generate_question_set";

const SOURCE_META: Record<
  QuestionSource,
  { label: string; icon: typeof Bot; tint: string }
> = {
  ai_generated: { label: "AI", icon: Bot, tint: "text-sky-600" },
  manual: { label: "Manual", icon: Pin, tint: "text-amber-600" },
  from_competency_indicator: {
    label: "Indicator",
    icon: Target,
    tint: "text-violet-600",
  },
  from_blind_spot: {
    label: "Blind spot",
    icon: Lightbulb,
    tint: "text-rose-600",
  },
};

const PRIORITY_BADGE: Record<QuestionPriority, string> = {
  must: BADGE_COLOR.rose,
  should: BADGE_COLOR.amber,
  nice_to_ask: BADGE_COLOR.emerald,
};

const GOAL_LABEL: Record<QuestionGoal, string> = {
  clarification: "Clarification",
  depth: "Depth",
  risk: "Risk",
  motivation: "Motivation",
  fit: "Fit",
};

function activeQuestions(set: QuestionSet): QuestionRow[] {
  return set.questions.filter((q) => q.status === "active");
}

export function InterviewQuestionSets({
  candidateId,
  vacancyOptions,
  initialVacancyId,
}: Props) {
  const [vacancyId, setVacancyId] = useState<string | undefined>(
    initialVacancyId || vacancyOptions[0]?.id,
  );
  const [sets, setSets] = useState<QuestionSet[]>([]);
  const [activeSetId, setActiveSetId] = useState<string | null>(null);
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
  const [exportOpen, setExportOpen] = useState(false);
  const [regenerateConfirm, setRegenerateConfirm] = useState(false);
  const [deleteId, setDeleteId] = useState<string | null>(null);
  // HRP-205: transcribed interview rounds for this candidate-vacancy.
  // Their presence unlocks "Generate next set" (mode=dynamic_next).
  const [transcribedRounds, setTranscribedRounds] = useState<string[]>([]);

  const currentVacancy = useMemo(
    () => vacancyOptions.find((v) => v.id === vacancyId),
    [vacancyOptions, vacancyId],
  );

  useEffect(() => {
    const cvId = currentVacancy?.candidate_vacancy_id;
    if (!cvId) {
      setTranscribedRounds([]);
      return;
    }
    let cancelled = false;
    api
      .get<
        Array<{
          id: string;
          transcription_status: string;
          archived_at: string | null;
        }>
      >(`/recruitment/candidate-vacancies/${cvId}/interviews`)
      .then((rows) => {
        if (cancelled) return;
        setTranscribedRounds(
          rows
            .filter(
              (r) =>
                r.transcription_status === "completed" && !r.archived_at,
            )
            .map((r) => r.id),
        );
      })
      .catch(() => {
        if (!cancelled) setTranscribedRounds([]);
      });
    return () => {
      cancelled = true;
    };
  }, [currentVacancy?.candidate_vacancy_id]);

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
      if (ours.length && !ours.some((s) => s.id === activeSetId)) {
        setActiveSetId(ours[0].id);
      }
      if (!ours.length) setActiveSetId(null);
    } catch {
      setSets([]);
      setActiveSetId(null);
    } finally {
      setLoading(false);
    }
  }, [candidateId, vacancyId, activeSetId]);

  useEffect(() => {
    loadSets();
  }, [loadSets]);

  const currentSet =
    sample ?? sets.find((s) => s.id === activeSetId) ?? null;

  // Credit copy only renders on SaaS builds where billing is active; the
  // number is server-priced so it stays in sync with backend/ee/credits.yaml.
  const creditSuffix =
    isSaas && generateCost !== null ? ` (${generateCost} cr)` : "";

  async function handleSample() {
    try {
      const s = await api.get<QuestionSet>("/v1/question-sets/sample");
      setSample(s);
      toast.message("Sample mode — no credits charged");
    } catch {
      toast.error("Failed to load sample");
    }
  }

  async function handleGenerate(mode: GenerationMode) {
    if (!currentVacancy?.candidate_vacancy_id) return;
    setGenerating(true);
    try {
      const body: Record<string, unknown> = { mode, set_type: "pre_interview" };
      if (mode === "regenerated" && currentSet?.id) {
        body.target_set_id = currentSet.id;
      }
      if (mode === "dynamic_next") {
        body.set_type = "interview_round";
        body.source_round_ids = transcribedRounds;
      }
      const created = await api.post<QuestionSet>(
        `/v1/candidate-vacancies/${currentVacancy.candidate_vacancy_id}/question-sets`,
        body,
      );
      setSample(null);
      setSets((prev) => {
        const filtered = prev.filter((s) => s.id !== created.id);
        return [created, ...filtered];
      });
      setActiveSetId(created.id);
      toast.success("Question set ready");
      refreshBalance();
    } catch (err) {
      const msg =
        err && typeof err === "object" && "message" in err
          ? String((err as { message: unknown }).message)
          : "Failed to generate";
      toast.error(msg);
    } finally {
      setGenerating(false);
    }
  }

  async function handleAdd(payload: Partial<QuestionRow>) {
    if (!currentSet?.id) return;
    try {
      const created = await api.post<QuestionRow>(
        `/v1/question-sets/${currentSet.id}/questions`,
        {
          text: payload.text || "",
          goal: payload.goal || "clarification",
          priority: payload.priority || "should",
          competence_id: payload.competence_id || null,
          rationale: payload.rationale || null,
          source: payload.source || "manual",
          expected_answer_indicators: payload.expected_answer_indicators || [],
          follow_ups: payload.follow_ups || [],
        },
      );
      setSets((prev) =>
        prev.map((s) =>
          s.id === currentSet.id
            ? { ...s, questions: [...s.questions, created] }
            : s,
        ),
      );
      toast.success("Question added");
      setAddOpen(false);
    } catch (err) {
      const msg =
        err && typeof err === "object" && "message" in err
          ? String((err as { message: unknown }).message)
          : "Failed to add";
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
      toast.error("Failed to update");
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
      toast.error("Failed to save");
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
      toast.success("Question deleted");
    } catch {
      toast.error("Failed to delete");
    } finally {
      setDeleteId(null);
    }
  }

  const resumeMissing = currentVacancy?.has_parsed_resume === false;

  return (
    <section
      data-testid="recruitment-interview-questions-section"
      className="space-y-3"
    >
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Sparkles className="h-5 w-5 text-sky-600" />
          <h2 className="text-lg font-semibold">Interview questions</h2>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {vacancyOptions.length > 1 && (
            <Select value={vacancyId} onValueChange={setVacancyId}>
              <SelectTrigger
                className="w-64"
                data-testid="recruitment-interview-questions-vacancy-select"
              >
                <SelectValue placeholder="Select vacancy">
                  {(value) =>
                    vacancyOptions.find((v) => v.id === value)?.title ??
                    "Select vacancy"
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
          {sets.length > 0 && (
            <Button
              variant="outline"
              size="sm"
              data-testid="recruitment-interview-questions-export-btn"
              onClick={() => setExportOpen(true)}
            >
              <Download className="mr-1 h-4 w-4" />
              Export PDF
            </Button>
          )}
        </div>
      </header>

      {sets.length > 0 && !sample && (
        <div
          role="tablist"
          aria-label="Question sets"
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
          <Button
            variant="ghost"
            size="sm"
            onClick={() => handleGenerate("initial")}
            disabled={generating || resumeMissing}
            data-testid="recruitment-interview-questions-new-set-btn"
          >
            <Plus className="mr-1 h-4 w-4" />
            New set
          </Button>
          {transcribedRounds.length > 0 && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => handleGenerate("dynamic_next")}
              disabled={generating || resumeMissing || insufficient}
              data-testid="recruitment-interview-questions-next-set-btn"
            >
              <Sparkles className="mr-1 h-4 w-4" />
              Generate next set{creditSuffix}
            </Button>
          )}
        </div>
      )}

      {loading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
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
                  {currentSet.generation_mode.replace(/_/g, " ")}
                </Badge>
                {currentSet.status === "sample" && (
                  <Badge variant="secondary">Sample</Badge>
                )}
              </CardTitle>
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
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setAddOpen(true)}
                    data-testid="recruitment-interview-questions-add-btn"
                  >
                    <Plus className="mr-1 h-4 w-4" />
                    Add
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setRegenerateConfirm(true)}
                    disabled={generating || insufficient}
                    data-testid="recruitment-interview-questions-regenerate-btn"
                  >
                    <RefreshCw className="mr-1 h-4 w-4" />
                    Re-generate{creditSuffix}
                  </Button>
                </>
              )}
            </div>
          </CardHeader>
          <CardContent className="space-y-2">
            {activeQuestions(currentSet).length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Set is empty. Add a question or regenerate.
              </p>
            ) : (
              activeQuestions(currentSet).map((q) => (
                <QuestionItem
                  key={q.id || `${q.sort_order}-${q.text.slice(0, 8)}`}
                  question={q}
                  readOnly={currentSet.status === "sample"}
                  onToggleCovered={() => handleToggleCovered(q)}
                  onEdit={(patch) => handleEdit(q, patch)}
                  onDelete={() => q.id && setDeleteId(q.id)}
                />
              ))
            )}
          </CardContent>
        </Card>
      ) : null}

      <AddQuestionDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        onSubmit={handleAdd}
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
        title="Re-generate this set?"
        description={`AI-generated questions will be replaced. Manual and indicator entries stay.${
          isSaas && generateCost !== null ? ` Cost: ${generateCost} credits.` : ""
        }`}
        confirmLabel="Re-generate"
        cancelLabel="Cancel"
        onConfirm={() => {
          setRegenerateConfirm(false);
          handleGenerate("regenerated");
        }}
        testId="recruitment-interview-questions-regenerate-confirm"
      />

      <ConfirmDialog
        open={deleteId !== null}
        onOpenChange={(o) => !o && setDeleteId(null)}
        title="Delete question?"
        description="Soft-deletes the row. It will not return on regeneration."
        confirmLabel="Delete"
        cancelLabel="Cancel"
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
  const withCredits = showCredits && cost !== null;
  return (
    <div
      className="rounded-lg border border-dashed p-10 text-center"
      data-testid="recruitment-interview-questions-empty"
    >
      <FileQuestion className="mx-auto mb-3 h-10 w-10 text-muted-foreground/50" />
      <p className="text-sm font-medium">No question set yet</p>
      <p className="mt-1 text-xs text-muted-foreground">
        {resumeMissing
          ? "Upload and parse a resume to enable AI generation."
          : insufficient
            ? `Generation needs ${cost} credits. Current balance: ${
                balance ?? 0
              }. View a sample at no cost while you top up.`
            : `Generate the first set tailored to this candidate's resume.`}
      </p>
      <div className="mt-4 flex items-center justify-center gap-2">
        <Button
          onClick={onGenerate}
          disabled={resumeMissing || insufficient || generating}
          data-testid="recruitment-interview-questions-generate-btn"
        >
          {generating ? (
            "Generating…"
          ) : (
            <>
              <Sparkles className="mr-1 h-4 w-4" />
              {withCredits
                ? `Generate first set (${cost} credits)`
                : "Generate first set"}
            </>
          )}
        </Button>
        {insufficient && (
          <Button
            variant="outline"
            onClick={onSample}
            data-testid="recruitment-interview-questions-sample-btn"
          >
            View sample
          </Button>
        )}
      </div>
    </div>
  );
}

interface QuestionItemProps {
  question: QuestionRow;
  readOnly: boolean;
  onToggleCovered: () => void;
  onEdit: (patch: Partial<QuestionRow>) => void;
  onDelete: () => void;
}

function QuestionItem({
  question,
  readOnly,
  onToggleCovered,
  onEdit,
  onDelete,
}: QuestionItemProps) {
  const [expanded, setExpanded] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(question.text);

  const meta = SOURCE_META[question.source];
  const Icon = meta.icon;

  function commitEdit() {
    if (draft.trim() && draft !== question.text) {
      onEdit({ text: draft.trim() });
    }
    setEditing(false);
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
            question.covered_at ? "Mark as not covered" : "Mark as covered"
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

        <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${meta.tint}`} aria-label={meta.label} />

        <div className="min-w-0 flex-1 space-y-1">
          {editing ? (
            <Textarea
              autoFocus
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onBlur={commitEdit}
              rows={2}
              data-testid={`recruitment-interview-question-edit-${question.id}`}
            />
          ) : (
            <button
              type="button"
              className={`block w-full text-left text-sm leading-snug ${
                question.covered_at ? "text-muted-foreground line-through" : ""
              }`}
              onClick={() => setExpanded((v) => !v)}
            >
              {question.text}
            </button>
          )}
          <div className="flex flex-wrap items-center gap-1.5 text-xs">
            <Badge
              variant="secondary"
              className={PRIORITY_BADGE[question.priority]}
            >
              {question.priority.replace("_", " ")}
            </Badge>
            <Badge variant="outline">{GOAL_LABEL[question.goal]}</Badge>
            {question.resume_anchor_jsonb?.quote && (
              <span
                className="truncate text-muted-foreground"
                title={question.resume_anchor_jsonb.quote}
              >
                Resume: “{question.resume_anchor_jsonb.quote.slice(0, 60)}
                {question.resume_anchor_jsonb.quote.length > 60 ? "…" : ""}”
              </span>
            )}
            {question.covered_method === "auto_from_transcript" && (
              <Badge variant="secondary" className="text-[10px]">
                Auto-covered
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
                  <p className="font-medium">Expected indicators</p>
                  <ul className="ml-4 list-disc">
                    {question.expected_answer_indicators.map((i, idx) => (
                      <li key={idx}>{i}</li>
                    ))}
                  </ul>
                </div>
              )}
              {question.follow_ups.length > 0 && (
                <div>
                  <p className="font-medium">Follow-ups</p>
                  <ul className="ml-4 list-disc">
                    {question.follow_ups.map((f, idx) => (
                      <li key={idx}>{f}</li>
                    ))}
                  </ul>
                </div>
              )}
              {question.rationale && (
                <div>
                  <p className="font-medium">Why this question</p>
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
              onClick={() => setEditing(true)}
              aria-label="Edit question"
              data-testid={`recruitment-interview-question-edit-btn-${question.id}`}
            >
              <PencilLine className="h-3.5 w-3.5" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={onDelete}
              aria-label="Delete question"
              data-testid={`recruitment-interview-question-delete-btn-${question.id}`}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={() => setExpanded((v) => !v)}
              aria-label="Toggle details"
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
  onSubmit: (payload: Partial<QuestionRow>) => void;
}

function AddQuestionDialog({
  open,
  onOpenChange,
  onSubmit,
}: AddQuestionDialogProps) {
  const [text, setText] = useState("");
  const [goal, setGoal] = useState<QuestionGoal>("clarification");
  const [priority, setPriority] = useState<QuestionPriority>("should");
  const [source, setSource] =
    useState<"manual" | "from_competency_indicator">("manual");

  function reset() {
    setText("");
    setGoal("clarification");
    setPriority("should");
    setSource("manual");
  }

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
          <DialogTitle>Add a question</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label htmlFor="q-text">Question</Label>
            <Textarea
              id="q-text"
              rows={3}
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="What concrete decision did you make under uncertainty?"
              data-testid="recruitment-interview-questions-add-text"
            />
          </div>
          <div className="grid grid-cols-3 gap-3">
            <div>
              <Label>Goal</Label>
              <Select
                value={goal}
                onValueChange={(v) => setGoal(v as QuestionGoal)}
              >
                <SelectTrigger data-testid="recruitment-interview-questions-add-goal">
                  <SelectValue>{GOAL_LABEL[goal] ?? goal}</SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {Object.entries(GOAL_LABEL).map(([k, v]) => (
                    <SelectItem key={k} value={k}>
                      {v}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>Priority</Label>
              <Select
                value={priority}
                onValueChange={(v) => setPriority(v as QuestionPriority)}
              >
                <SelectTrigger data-testid="recruitment-interview-questions-add-priority">
                  <SelectValue>
                    {priority === "must"
                      ? "Must"
                      : priority === "nice_to_ask"
                        ? "Nice to ask"
                        : "Should"}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="must">Must</SelectItem>
                  <SelectItem value="should">Should</SelectItem>
                  <SelectItem value="nice_to_ask">Nice to ask</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>Type</Label>
              <Select
                value={source}
                onValueChange={(v) =>
                  setSource(v as "manual" | "from_competency_indicator")
                }
              >
                <SelectTrigger data-testid="recruitment-interview-questions-add-source">
                  <SelectValue>
                    {source === "from_competency_indicator"
                      ? "From indicator"
                      : "Custom"}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="manual">Custom</SelectItem>
                  <SelectItem value="from_competency_indicator">
                    From indicator
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={() => {
              if (!text.trim()) {
                toast.error("Question text is required");
                return;
              }
              onSubmit({ text, goal, priority, source });
              reset();
            }}
            data-testid="recruitment-interview-questions-add-submit"
          >
            Add question
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
      toast.error("Failed to export");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="recruitment-interview-questions-export-dialog">
        <DialogHeader>
          <DialogTitle>Export to PDF</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label>Format</Label>
            <Select
              value={format}
              onValueChange={(v) => setFormat(v as typeof format)}
            >
              <SelectTrigger>
                <SelectValue>
                  {format === "full"
                    ? "Full (interviewer prep)"
                    : format === "cards"
                      ? "Cards"
                      : "Compact (list)"}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="compact">Compact (list)</SelectItem>
                <SelectItem value="full">Full (interviewer prep)</SelectItem>
                <SelectItem value="cards">Cards</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label>Sort</Label>
            <Select
              value={sort}
              onValueChange={(v) => setSort(v as typeof sort)}
            >
              <SelectTrigger>
                <SelectValue>
                  {sort === "priority"
                    ? "Priority"
                    : sort === "competence"
                      ? "Competence"
                      : "Default"}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="sort_order">Default</SelectItem>
                <SelectItem value="priority">Priority</SelectItem>
                <SelectItem value="competence">Competence</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="grid grid-cols-2 gap-2 text-sm">
            <label className="flex items-center gap-2">
              <Input
                type="checkbox"
                className="h-4 w-4"
                checked={includeIndicators}
                onChange={(e) => setIncludeIndicators(e.target.checked)}
              />
              Indicators
            </label>
            <label className="flex items-center gap-2">
              <Input
                type="checkbox"
                className="h-4 w-4"
                checked={includeFollowUps}
                onChange={(e) => setIncludeFollowUps(e.target.checked)}
              />
              Follow-ups
            </label>
            <label className="flex items-center gap-2">
              <Input
                type="checkbox"
                className="h-4 w-4"
                checked={includeRationale}
                onChange={(e) => setIncludeRationale(e.target.checked)}
              />
              Rationale
            </label>
            <label className="flex items-center gap-2">
              <Input
                type="checkbox"
                className="h-4 w-4"
                checked={includeResumeAnchor}
                onChange={(e) => setIncludeResumeAnchor(e.target.checked)}
              />
              Resume anchor
            </label>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={handleExport}
            disabled={busy}
            data-testid="recruitment-interview-questions-export-submit"
          >
            {busy ? "Exporting…" : "Download PDF"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
