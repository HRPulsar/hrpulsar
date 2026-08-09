"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Check, Loader2, X } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioItem } from "@/components/ui/radio";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import {
  joinLocalDateTime,
  labelForAssessmentRound,
  splitLocalDateTime,
} from "@/lib/recruitment-helpers";
import type {
  Interview,
  InterviewerOption,
  InterviewRoundOption,
  InterviewType,
} from "@/lib/types";

// HRP-386: hard caps from the acceptance criteria. Enforced on the input
// elements so the user sees the ceiling while typing — the backend column
// is wider on purpose (bulk upload stores whole file names as titles).
const TITLE_MAX = 100;
const NOTES_MAX = 1000;

const NO_ROUND = "__none__";

const TYPE_ORDER: InterviewType[] = [
  "audio",
  "video",
  "text_transcript",
  "undecided",
];

export interface ScheduleVacancyOption {
  id: string;
  title: string;
  candidate_vacancy_id: string;
}

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  vacancyOptions: ScheduleVacancyOption[];
  /** Vacancy preselected from the Interviews block selector. */
  vacancyId?: string;
  /** Present in edit mode — the vacancy field is locked to its own link. */
  interview?: Interview | null;
  onSaved: () => void;
}

export function ScheduleInterviewDialog({
  open,
  onOpenChange,
  vacancyOptions,
  vacancyId,
  interview,
  onSaved,
}: Props) {
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const isEdit = Boolean(interview);
  // HRP-418: the title of an interview that already carries a recording is
  // the file identity — renaming it would desync the card from the asset.
  const titleLocked = isEdit && interview?.status === "uploaded";
  const typeLocked = Boolean(
    interview?.audio_file_id ||
      interview?.video_file_id ||
      interview?.transcript_file_id,
  );

  const [selectedVacancy, setSelectedVacancy] = useState<string | undefined>(
    vacancyId ?? vacancyOptions[0]?.id,
  );
  const [roundId, setRoundId] = useState<string>(NO_ROUND);
  const [title, setTitle] = useState("");
  const [date, setDate] = useState("");
  const [time, setTime] = useState("");
  const [duration, setDuration] = useState("60");
  const [interviewers, setInterviewers] = useState<string[]>([]);
  const [type, setType] = useState<InterviewType>("audio");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [rounds, setRounds] = useState<InterviewRoundOption[]>([]);
  const [people, setPeople] = useState<InterviewerOption[]>([]);

  const cvId = useMemo(() => {
    if (isEdit) return interview?.candidate_vacancy_id;
    return vacancyOptions.find((v) => v.id === selectedVacancy)
      ?.candidate_vacancy_id;
  }, [isEdit, interview, vacancyOptions, selectedVacancy]);

  // What the form is seeded from, readable without becoming a dependency
  // of the reset below. Declared before it so the values are already
  // current in the commit that flips `open`.
  const seed = useRef({ interview, vacancyId, vacancyOptions });
  useEffect(() => {
    seed.current = { interview, vacancyId, vacancyOptions };
  });

  // Reset the form when the dialog opens so a cancelled edit never leaks
  // into the next one — and only then: a background refetch of the
  // candidate card used to re-run this and wipe half-typed input while
  // the dialog was open.
  useEffect(() => {
    if (!open) return;
    const {
      interview: source,
      vacancyId: preselected,
      vacancyOptions: options,
    } = seed.current;
    if (source) {
      const split = splitLocalDateTime(source.interview_date);
      setSelectedVacancy(
        options.find(
          (v) => v.candidate_vacancy_id === source.candidate_vacancy_id,
        )?.id ?? preselected,
      );
      setRoundId(source.round_id ?? NO_ROUND);
      setTitle(source.title ?? "");
      setDate(split.date);
      setTime(split.time);
      setDuration(
        source.duration_minutes ? String(source.duration_minutes) : "",
      );
      setInterviewers(source.interviewer_ids ?? []);
      setType((source.type as InterviewType) ?? "undecided");
      setNotes(source.notes ?? "");
      return;
    }
    setSelectedVacancy(preselected ?? options[0]?.id);
    setRoundId(NO_ROUND);
    setTitle("");
    setDate("");
    setTime("");
    setDuration("60");
    setInterviewers([]);
    setType("audio");
    setNotes("");
  }, [open]);

  // Rounds belong to the selected candidate-vacancy — switching the
  // vacancy has to reload them and drop a now-foreign selection.
  useEffect(() => {
    if (!open || !cvId) {
      setRounds([]);
      return;
    }
    let cancelled = false;
    api
      .get<InterviewRoundOption[]>(
        `/v1/candidate-vacancies/${cvId}/assessment-rounds`,
      )
      .then((rows) => {
        if (cancelled) return;
        const list = Array.isArray(rows) ? rows : [];
        setRounds(list);
        setRoundId((prev) =>
          prev !== NO_ROUND && !list.some((r) => r.id === prev)
            ? NO_ROUND
            : prev,
        );
      })
      .catch(() => {
        if (!cancelled) setRounds([]);
      });
    return () => {
      cancelled = true;
    };
  }, [open, cvId]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    api
      .get<InterviewerOption[]>("/recruitment/interviewers")
      .then((rows) => {
        if (!cancelled) setPeople(Array.isArray(rows) ? rows : []);
      })
      .catch(() => {
        if (!cancelled) setPeople([]);
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  const toggleInterviewer = useCallback((id: string) => {
    setInterviewers((prev) =>
      prev.includes(id) ? prev.filter((p) => p !== id) : [...prev, id],
    );
  }, []);

  async function submit() {
    if (!cvId) return;
    setBusy(true);
    const payload = {
      title: title.trim().slice(0, TITLE_MAX) || null,
      round_id: roundId === NO_ROUND ? null : roundId,
      interview_date: joinLocalDateTime(date, time),
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      duration_minutes: Number(duration) > 0 ? Number(duration) : null,
      interviewers,
      type,
      notes: notes.trim().slice(0, NOTES_MAX) || null,
    };
    try {
      if (interview) {
        await api.put<Interview>(
          `/recruitment/interviews/${interview.id}`,
          titleLocked ? { ...payload, title: interview.title ?? null } : payload,
        );
        toast.success(t("candidateInterviewsUpdated"));
      } else {
        await api.post<Interview>(
          `/recruitment/candidate-vacancies/${cvId}/interviews`,
          payload,
        );
        toast.success(t("candidateInterviewsScheduled"));
      }
      onSaved();
    } catch (err) {
      toast.error(
        err instanceof Error
          ? err.message
          : t("candidateInterviewsScheduleFailed"),
      );
    } finally {
      setBusy(false);
    }
  }

  const typeLabels: Record<InterviewType, string> = {
    audio: t("candidateInterviewsTypeAudio"),
    video: t("candidateInterviewsTypeVideo"),
    text_transcript: t("candidateInterviewsTypeTextTranscript"),
    undecided: t("candidateInterviewsTypeUndecided"),
  };

  const selectedPeople = people.filter((p) => interviewers.includes(p.id));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-h-[90vh] max-w-lg overflow-y-auto"
        data-testid="recruitment-candidate-interviews-schedule-dialog"
      >
        <DialogHeader>
          <DialogTitle>
            {isEdit
              ? t("candidateInterviewsEditTitle")
              : t("candidateInterviewsScheduleButton")}
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1">
            <Label htmlFor="iv-vacancy">
              {t("candidateInterviewsFieldVacancy")}
            </Label>
            <Select
              value={selectedVacancy}
              onValueChange={setSelectedVacancy}
              disabled={isEdit || vacancyOptions.length <= 1}
            >
              <SelectTrigger
                id="iv-vacancy"
                data-testid="recruitment-candidate-interviews-schedule-vacancy"
              >
                <SelectValue
                  placeholder={t("candidateInterviewsSelectVacancy")}
                >
                  {(value) =>
                    vacancyOptions.find((v) => v.id === value)?.title ??
                    t("candidateInterviewsSelectVacancy")
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
          </div>

          <div className="space-y-1">
            <Label htmlFor="iv-round">
              {t("candidateInterviewsFieldRound")}
            </Label>
            <Select value={roundId} onValueChange={setRoundId}>
              <SelectTrigger
                id="iv-round"
                data-testid="recruitment-candidate-interviews-schedule-round"
              >
                <SelectValue placeholder={t("candidateInterviewsRoundNone")}>
                  {(value) => {
                    const found = rounds.find((r) => r.id === value);
                    return found
                      ? labelForAssessmentRound(t, found)
                      : t("candidateInterviewsRoundNone");
                  }}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NO_ROUND}>
                  {t("candidateInterviewsRoundNone")}
                </SelectItem>
                {rounds.map((r) => (
                  <SelectItem key={r.id} value={r.id}>
                    {labelForAssessmentRound(t, r)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1">
            <Label htmlFor="iv-title">{t("columnTitle")}</Label>
            <Input
              id="iv-title"
              value={title}
              maxLength={TITLE_MAX}
              disabled={titleLocked}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={t("candidateInterviewsTitlePlaceholder")}
              data-testid="recruitment-candidate-interviews-schedule-title"
            />
            <p className="text-xs text-muted-foreground">
              {titleLocked
                ? t("candidateInterviewsTitleLocked")
                : t("candidateInterviewsTitleHint", { max: TITLE_MAX })}
            </p>
          </div>

          <div className="grid grid-cols-3 gap-3">
            <div className="space-y-1">
              <Label htmlFor="iv-date">
                {t("candidateInterviewsFieldScheduledDate")}
              </Label>
              <Input
                id="iv-date"
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                data-testid="recruitment-candidate-interviews-schedule-date"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="iv-time">
                {t("candidateInterviewsFieldScheduledTime")}
              </Label>
              <Input
                id="iv-time"
                type="time"
                value={time}
                onChange={(e) => setTime(e.target.value)}
                data-testid="recruitment-candidate-interviews-schedule-time"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="iv-duration">
                {t("candidateInterviewsFieldDuration")}
              </Label>
              <Input
                id="iv-duration"
                type="number"
                min={1}
                value={duration}
                onChange={(e) => setDuration(e.target.value)}
                data-testid="recruitment-candidate-interviews-schedule-duration"
              />
            </div>
          </div>

          <div className="space-y-1">
            <Label>{t("candidateInterviewsFieldInterviewers")}</Label>
            <div
              className="max-h-40 space-y-1 overflow-y-auto rounded-md border p-2"
              data-testid="recruitment-candidate-interviews-schedule-interviewers"
            >
              {people.length === 0 ? (
                <p className="px-1 py-0.5 text-xs text-muted-foreground">
                  {t("candidateInterviewsNoInterviewers")}
                </p>
              ) : (
                people.map((p) => {
                  const picked = interviewers.includes(p.id);
                  return (
                    <button
                      key={p.id}
                      type="button"
                      onClick={() => toggleInterviewer(p.id)}
                      aria-pressed={picked}
                      className={`flex w-full items-center justify-between rounded px-2 py-1 text-left text-sm hover:bg-muted ${
                        picked ? "bg-muted" : ""
                      }`}
                      data-testid={`recruitment-candidate-interviews-schedule-interviewer-${p.id}`}
                    >
                      <span className="min-w-0 truncate">
                        {p.full_name}
                        <span className="ml-2 text-xs text-muted-foreground">
                          {p.email}
                        </span>
                      </span>
                      {picked && <Check className="size-4 shrink-0" />}
                    </button>
                  );
                })
              )}
            </div>
            {selectedPeople.length > 0 && (
              <div className="flex flex-wrap gap-1 pt-1">
                {selectedPeople.map((p) => (
                  <Badge
                    key={p.id}
                    variant="secondary"
                    className="gap-1 text-xs"
                  >
                    {p.full_name}
                    <button
                      type="button"
                      aria-label={t("candidateInterviewsRemoveInterviewer", {
                        name: p.full_name,
                      })}
                      onClick={() => toggleInterviewer(p.id)}
                    >
                      <X className="size-3" />
                    </button>
                  </Badge>
                ))}
              </div>
            )}
          </div>

          <div className="space-y-1">
            <Label>{t("candidateInterviewsFieldType")}</Label>
            <RadioGroup
              value={type}
              onValueChange={(v) => setType(v as InterviewType)}
              disabled={typeLocked}
              data-testid="recruitment-candidate-interviews-schedule-type"
            >
              {TYPE_ORDER.map((option) => (
                <Label
                  key={option}
                  className="flex items-center gap-2 text-sm font-normal"
                >
                  <RadioItem
                    value={option}
                    data-testid={`recruitment-candidate-interviews-schedule-type-${option}`}
                  />
                  {typeLabels[option]}
                </Label>
              ))}
            </RadioGroup>
            {typeLocked && (
              <p className="text-xs text-muted-foreground">
                {t("candidateInterviewsTypeLocked")}
              </p>
            )}
          </div>

          <div className="space-y-1">
            <Label htmlFor="iv-notes">{t("candidateFieldNotes")}</Label>
            <Textarea
              id="iv-notes"
              rows={3}
              value={notes}
              maxLength={NOTES_MAX}
              onChange={(e) => setNotes(e.target.value)}
              data-testid="recruitment-candidate-interviews-schedule-notes"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {tc("cancel")}
          </Button>
          <Button
            onClick={submit}
            disabled={busy || !cvId}
            data-testid="recruitment-candidate-interviews-schedule-save"
          >
            {busy && <Loader2 className="size-4 animate-spin" />}
            {isEdit ? t("save") : t("candidateInterviewsSchedule")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
