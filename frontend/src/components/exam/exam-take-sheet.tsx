"use client";

// HRP-328: employee-facing "Take this exam" side sheet plus the read-only
// results sheet. Mirrors the assessment survey sheet UX (HRP-146): answers
// autosave on every change, a partially answered exam reopens with the
// saved draft, and Submit stays locked until every question is answered.

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { RadioGroup, RadioItem } from "@/components/ui/radio";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { Check, X } from "lucide-react";
import { toast } from "sonner";

interface TakeOption {
  id: string;
  title: string;
  sort_index: number;
}

interface TakeQuestion {
  id: string;
  title: string;
  description: string | null;
  question_type: "single_choice" | "multiple_choice" | "essay";
  sort_index: number;
  weight: number;
  image_url: string | null;
  options: TakeOption[];
}

interface TakePayload {
  exam_id: string;
  status: string;
  mass_exam_title: string | null;
  questions: TakeQuestion[];
  answers: {
    question_id: string;
    selected_option_ids: string[];
    text_answer: string | null;
  }[];
}

interface DraftAnswer {
  selected: string[];
  text: string;
}

function isAnswered(a: DraftAnswer | undefined): boolean {
  return Boolean(a && (a.selected.length > 0 || a.text.trim()));
}

export function ExamTakeSheet({
  examId,
  open,
  onOpenChange,
  onFinished,
}: {
  examId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Called after answers were saved or the exam was submitted — the list
   * behind the sheet refreshes statuses/scores. */
  onFinished: () => void;
}) {
  const t = useTranslations("exams");
  const [payload, setPayload] = useState<TakePayload | null>(null);
  const [answers, setAnswers] = useState<Record<string, DraftAnswer>>({});
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const essayTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>(
    {},
  );
  // Every autosave in flight — Submit must wait for them all, or finish
  // could reach the server before the last answer does (onBlur fires the
  // essay save just before the button click lands).
  const inflightSaves = useRef<Set<Promise<void>>>(new Set());

  const loadPayload = useCallback(async (): Promise<boolean> => {
    if (!examId) return false;
    try {
      const data = await api.get<TakePayload>(`/exams/${examId}/questions`);
      const draft: Record<string, DraftAnswer> = {};
      for (const a of data.answers) {
        draft[a.question_id] = {
          selected: a.selected_option_ids ?? [],
          text: a.text_answer ?? "",
        };
      }
      setPayload(data);
      setAnswers(draft);
      return true;
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("errorLoadExam"),
      );
      return false;
    }
  }, [examId, t]);

  useEffect(() => {
    if (!open || !examId) return;
    let cancelled = false;
    setLoading(true);
    setPayload(null);
    void loadPayload().then((ok) => {
      if (cancelled) return;
      setLoading(false);
      if (!ok) onOpenChange(false);
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, examId]);

  const saveAnswer = useCallback(
    (questionId: string, draft: DraftAnswer): Promise<void> => {
      if (!examId) return Promise.resolve();
      const request = (async () => {
        try {
          await api.post(`/exams/${examId}/answer`, {
            question_id: questionId,
            selected_option_ids: draft.selected.length ? draft.selected : null,
            text_answer: draft.text || null,
          });
        } catch (err) {
          toast.error(
            err instanceof Error ? err.message : t("errorSaveAnswer"),
          );
        }
      })();
      inflightSaves.current.add(request);
      void request.finally(() => inflightSaves.current.delete(request));
      return request;
    },
    [examId, t],
  );

  function setChoice(questionId: string, optionIds: string[]) {
    const draft: DraftAnswer = { selected: optionIds, text: "" };
    setAnswers((prev) => ({ ...prev, [questionId]: draft }));
    void saveAnswer(questionId, draft);
  }

  function setEssay(questionId: string, text: string) {
    const draft: DraftAnswer = { selected: [], text };
    setAnswers((prev) => ({ ...prev, [questionId]: draft }));
    if (essayTimers.current[questionId]) {
      clearTimeout(essayTimers.current[questionId]);
    }
    essayTimers.current[questionId] = setTimeout(() => {
      delete essayTimers.current[questionId];
      void saveAnswer(questionId, draft);
    }, 600);
  }

  function flushEssaySaves(): Promise<void> {
    for (const [questionId, timer] of Object.entries(essayTimers.current)) {
      clearTimeout(timer);
      delete essayTimers.current[questionId];
      const draft = answers[questionId];
      if (draft) void saveAnswer(questionId, draft);
    }
    // Wait for everything in flight, including saves started elsewhere
    // (an onBlur flush racing the Submit click).
    return Promise.all([...inflightSaves.current]).then(() => undefined);
  }

  const questions = payload?.questions ?? [];
  const answeredCount = questions.filter((q) => isAnswered(answers[q.id])).length;
  const allAnswered = questions.length > 0 && answeredCount === questions.length;

  async function submit() {
    if (!examId) return;
    setSubmitting(true);
    try {
      // Debounced essay saves must land before finish — the backend
      // rejects submission while any question is still unanswered.
      await flushEssaySaves();
      const result = await api.post<{
        score: number;
        max_score: number | null;
        passed: boolean;
      }>(`/exams/${examId}/finish`, {});
      toast.success(
        result.max_score != null
          ? t("toastResultsSubmittedWithMax", {
              score: result.score,
              max: result.max_score,
            })
          : t("toastResultsSubmitted", { score: result.score }),
      );
      onOpenChange(false);
      onFinished();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("errorSubmitResults"),
      );
      // A failed autosave can leave the local draft ahead of the server
      // (submit then 400s with "answer all questions") — re-sync so the
      // progress counter reflects what the backend actually has.
      void loadPayload();
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Sheet
      open={open}
      onOpenChange={(o) => {
        onOpenChange(o);
        if (!o) {
          // Persist anything still in a debounce window, then let the list
          // pick up the in_progress status flip.
          void flushEssaySaves().then(onFinished);
        }
      }}
    >
      <SheetContent className="max-w-xl sm:max-w-xl" data-testid="exam-take-sheet">
        <SheetHeader>
          <SheetTitle>
            {payload?.mass_exam_title
              ? t("takeExamNamed", { title: payload.mass_exam_title })
              : t("takeExam")}
          </SheetTitle>
        </SheetHeader>
        {loading ? (
          <div className="flex-1 py-8 text-center text-sm text-muted-foreground">
            {t("loadingQuestions")}
          </div>
        ) : (
          <div className="flex-1 space-y-4 overflow-y-auto pr-1">
            <p
              className="text-xs text-muted-foreground"
              data-testid="exam-take-progress"
            >
              {t("takeProgress", {
                answered: answeredCount,
                total: questions.length,
              })}
            </p>
            {questions.map((q, idx) => {
              const draft = answers[q.id];
              return (
                <div
                  key={q.id}
                  className="rounded-md border p-3"
                  data-testid={`exam-take-question-${q.id}`}
                >
                  <p className="mb-1 text-sm font-medium">
                    {idx + 1}. {q.title}
                  </p>
                  {q.description && (
                    <p className="mb-2 text-xs text-muted-foreground">
                      {q.description}
                    </p>
                  )}
                  {q.image_url && (
                    // Native size capped by height, like the exam page —
                    // stretching small images to the sheet width blurs them.
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={q.image_url}
                      alt={t("questionIllustrationAlt")}
                      className="mb-2 max-h-48 max-w-full rounded-md border"
                    />
                  )}
                  {q.question_type === "single_choice" && (
                    <RadioGroup
                      value={draft?.selected[0] ?? ""}
                      onValueChange={(value) =>
                        setChoice(q.id, [value as string])
                      }
                      aria-label={t("answerForQuestion", { title: q.title })}
                    >
                      {q.options.map((opt) => (
                        <label
                          key={opt.id}
                          htmlFor={`exam-${q.id}-${opt.id}`}
                          className="flex cursor-pointer items-start gap-2 rounded-sm px-1 py-1 text-sm hover:bg-muted/40"
                        >
                          <RadioItem
                            id={`exam-${q.id}-${opt.id}`}
                            value={opt.id}
                            className="mt-0.5"
                            data-testid={`exam-take-option-${q.id}-${opt.id}`}
                          />
                          <span className="leading-snug">{opt.title}</span>
                        </label>
                      ))}
                    </RadioGroup>
                  )}
                  {q.question_type === "multiple_choice" && (
                    <div className="space-y-1">
                      {q.options.map((opt) => {
                        const checked = draft?.selected.includes(opt.id) ?? false;
                        return (
                          <label
                            key={opt.id}
                            className="flex cursor-pointer items-start gap-2 rounded-sm px-1 py-1 text-sm hover:bg-muted/40"
                          >
                            <Checkbox
                              checked={checked}
                              onCheckedChange={(next) => {
                                const current = draft?.selected ?? [];
                                setChoice(
                                  q.id,
                                  next
                                    ? [...current, opt.id]
                                    : current.filter((id) => id !== opt.id),
                                );
                              }}
                              className="mt-0.5"
                              data-testid={`exam-take-option-${q.id}-${opt.id}`}
                            />
                            <span className="leading-snug">{opt.title}</span>
                          </label>
                        );
                      })}
                    </div>
                  )}
                  {q.question_type === "essay" && (
                    <Textarea
                      placeholder={t("essayPlaceholder")}
                      value={draft?.text ?? ""}
                      onChange={(e) => setEssay(q.id, e.target.value)}
                      onBlur={flushEssaySaves}
                      className="min-h-[80px]"
                      data-testid={`exam-take-essay-${q.id}`}
                    />
                  )}
                </div>
              );
            })}
            <div className="sticky bottom-0 border-t bg-background py-3">
              {/* Disabled buttons swallow hover — the hint lives on the span. */}
              <span
                title={allAnswered ? undefined : t("submitHint")}
              >
                <Button
                  onClick={submit}
                  disabled={!allAnswered || submitting}
                  data-testid="exam-take-submit"
                >
                  {submitting ? t("submitting") : t("submitResults")}
                </Button>
              </span>
            </div>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}

// ---------------------------------------------------------------------------
// Read-only results sheet — the answer key is revealed after completion.
// ---------------------------------------------------------------------------

interface ReviewOption {
  id: string;
  title: string;
  sort_index: number;
  is_correct: boolean;
}

interface ReviewQuestion {
  id: string;
  title: string;
  description: string | null;
  question_type: "single_choice" | "multiple_choice" | "essay";
  weight: number;
  image_url: string | null;
  options: ReviewOption[];
  answer: {
    selected_option_ids: string[];
    text_answer: string | null;
    is_correct: boolean | null;
    score: number;
  } | null;
}

interface ReviewPayload {
  exam_id: string;
  score: number | null;
  max_score: number | null;
  mass_exam_title: string | null;
  questions: ReviewQuestion[];
}

export function ExamReviewSheet({
  examId,
  open,
  onOpenChange,
}: {
  examId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("exams");
  const [payload, setPayload] = useState<ReviewPayload | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open || !examId) return;
    let cancelled = false;
    setLoading(true);
    setPayload(null);
    (async () => {
      try {
        const data = await api.get<ReviewPayload>(`/exams/${examId}/review`);
        if (!cancelled) setPayload(data);
      } catch (err) {
        if (!cancelled) {
          toast.error(
            err instanceof Error ? err.message : t("errorLoadResults"),
          );
          onOpenChange(false);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, examId]);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        className="max-w-xl sm:max-w-xl"
        data-testid="exam-review-sheet"
      >
        <SheetHeader>
          <SheetTitle>
            {payload?.mass_exam_title
              ? t("resultsNamed", { title: payload.mass_exam_title })
              : t("results")}
          </SheetTitle>
        </SheetHeader>
        {loading || !payload ? (
          <div className="flex-1 py-8 text-center text-sm text-muted-foreground">
            {t("loadingResults")}
          </div>
        ) : (
          <div className="flex-1 space-y-4 overflow-y-auto pr-1">
            <p className="text-sm" data-testid="exam-review-score">
              {t("reviewScoreLabel")}{" "}
              <span className="font-semibold">
                {payload.score ?? 0}
                {payload.max_score != null ? ` / ${payload.max_score}` : ""}
              </span>
            </p>
            {payload.questions.map((q, idx) => {
              const selected = new Set(q.answer?.selected_option_ids ?? []);
              return (
                <div
                  key={q.id}
                  className="rounded-md border p-3"
                  data-testid={`exam-review-question-${q.id}`}
                >
                  <div className="mb-2 flex items-start justify-between gap-2">
                    <p className="text-sm font-medium">
                      {idx + 1}. {q.title}
                    </p>
                    {q.answer?.is_correct != null && (
                      <Badge
                        variant="outline"
                        className={
                          q.answer.is_correct
                            ? "border-emerald-500 text-emerald-600"
                            : "border-red-500 text-red-600"
                        }
                        data-testid={`exam-review-verdict-${q.id}`}
                      >
                        {q.answer.is_correct ? t("verdictCorrect") : t("verdictIncorrect")}
                      </Badge>
                    )}
                  </div>
                  {q.image_url && (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={q.image_url}
                      alt={t("questionIllustrationAlt")}
                      className="mb-2 max-h-48 max-w-full rounded-md border"
                    />
                  )}
                  {q.question_type === "essay" ? (
                    <p className="whitespace-pre-wrap rounded-md bg-muted/40 p-2 text-sm">
                      {q.answer?.text_answer || "—"}
                    </p>
                  ) : (
                    <div className="space-y-1">
                      {q.options.map((opt) => {
                        const isSelected = selected.has(String(opt.id));
                        const cls = opt.is_correct
                          ? "border-emerald-500 bg-emerald-50 text-emerald-900"
                          : isSelected
                            ? "border-red-500 bg-red-50 text-red-900"
                            : "";
                        return (
                          <div
                            key={opt.id}
                            className={`flex items-center gap-2 rounded-md border px-2 py-1 text-sm ${cls}`}
                            data-testid={`exam-review-option-${q.id}-${opt.id}`}
                          >
                            {opt.is_correct ? (
                              <Check className="size-3.5 shrink-0 text-emerald-600" />
                            ) : isSelected ? (
                              <X className="size-3.5 shrink-0 text-red-600" />
                            ) : (
                              <span className="size-3.5 shrink-0" />
                            )}
                            <span>{opt.title}</span>
                            {isSelected && (
                              <span className="ml-auto text-xs text-muted-foreground">
                                {t("yourAnswer")}
                              </span>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
