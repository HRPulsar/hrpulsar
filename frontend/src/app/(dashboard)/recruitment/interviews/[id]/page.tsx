"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { api, ApiError } from "@/lib/api";
import type {
  CandidateVacancy,
  CompetenceItem,
  Interview,
  InterviewerOption,
  InterviewMediaURL,
  InterviewRoundOption,
  InterviewType,
  VacancyProfile,
} from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  AnalysisProgress,
  InterviewAnalysisPanel,
  InterviewPlayer,
  InterviewTextTranscriptDialog,
  InterviewUploadZone,
  RecruitmentBreadcrumbs,
  TranscriptEditDialog,
  TranscriptViewer,
} from "@/components/recruitment";
import { Check, FileText, Loader2, Pencil, Sparkles, Wand2, X } from "lucide-react";
import { toast } from "sonner";
import { formatDate, formatDateTime } from "@/lib/date-format";
import {
  joinLocalDateTime,
  labelForAssessmentRound,
  splitLocalDateTime,
} from "@/lib/recruitment-helpers";

const POLL_INTERVAL = 3000;

const EM_DASH = "—";

// HRP-387: the Details block edits one field at a time — everything else
// on the page keeps rendering while a single value is being changed.
type EditableField = "type" | "schedule" | "notes" | "title" | null;

export default function InterviewDetailPage() {
  const { id } = useParams<{ id: string }>();
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const [interview, setInterview] = useState<Interview | null>(null);
  const [media, setMedia] = useState<InterviewMediaURL | null>(null);
  const [profile, setProfile] = useState<VacancyProfile | null>(null);
  const [cvCtx, setCvCtx] = useState<CandidateVacancy | null>(null);
  const [loading, setLoading] = useState(true);
  const [editTranscriptOpen, setEditTranscriptOpen] = useState(false);
  const [textPasteOpen, setTextPasteOpen] = useState(false);
  const [busyAction, setBusyAction] = useState<
    null | "transcribe" | "analyze"
  >(null);
  const [editing, setEditing] = useState<EditableField>(null);
  const [savingField, setSavingField] = useState(false);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [rounds, setRounds] = useState<InterviewRoundOption[]>([]);
  const [people, setPeople] = useState<InterviewerOption[]>([]);
  const [currentSec, setCurrentSec] = useState(0);
  const audioRef = useRef<HTMLAudioElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const playerRef = useRef<HTMLMediaElement | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await api.get<Interview>(
        `/recruitment/interviews/${id}`,
      );
      setInterview(data);
      // After upload happens, try fetching media URL.
      if (data.audio_file_id || data.video_file_id) {
        try {
          const m = await api.get<InterviewMediaURL>(
            `/recruitment/interviews/${id}/media-url`,
          );
          setMedia(m);
        } catch {
          setMedia(null);
        }
      }
      return data;
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        toast.error(t("interviewNotFoundToast"));
      }
      return null;
    }
  }, [id, t]);

  useEffect(() => {
    void (async () => {
      const data = await refresh();
      // Best-effort fetch of candidate-vacancy context for breadcrumbs +
      // vacancy profile for competence names. None of these are critical —
      // the page renders the analysis even if they fail.
      if (data) {
        api
          .get<CandidateVacancy>(
            `/recruitment/candidate-vacancies/${data.candidate_vacancy_id}`,
          )
          .then(setCvCtx)
          .catch(() => null);
      }
      setLoading(false);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  // HRP-387: the subtitle shows the round this interview belongs to, and
  // the Details block resolves interviewer ids to names. Both are
  // best-effort — the page renders without them.
  useEffect(() => {
    if (!interview?.candidate_vacancy_id) return;
    let cancelled = false;
    api
      .get<InterviewRoundOption[]>(
        `/v1/candidate-vacancies/${interview.candidate_vacancy_id}/assessment-rounds`,
      )
      .then((rows) => {
        if (!cancelled) setRounds(Array.isArray(rows) ? rows : []);
      })
      .catch(() => null);
    return () => {
      cancelled = true;
    };
  }, [interview?.candidate_vacancy_id]);

  useEffect(() => {
    let cancelled = false;
    api
      .get<InterviewerOption[]>("/recruitment/interviewers")
      .then((rows) => {
        if (!cancelled) setPeople(Array.isArray(rows) ? rows : []);
      })
      .catch(() => null);
    return () => {
      cancelled = true;
    };
  }, []);

  // Once we know the vacancy id, fetch its profile to label competence ids.
  useEffect(() => {
    if (!cvCtx?.vacancy_id) return;
    let cancelled = false;
    api
      .get<{ profile: null } | VacancyProfile>(
        `/recruitment/vacancies/${cvCtx.vacancy_id}/profile`,
      )
      .then((res) => {
        if (cancelled) return;
        if (res && "profile_data" in res) setProfile(res as VacancyProfile);
      })
      .catch(() => null);
    return () => {
      cancelled = true;
    };
  }, [cvCtx?.vacancy_id]);

  // Every poll replaces `interview`, so keying the effect on the object
  // itself tore the interval down and rebuilt it three seconds at a time.
  // The boolean only changes when polling should actually start or stop.
  const pollInFlight =
    interview?.transcription_status === "processing" ||
    interview?.analysis_status === "processing";

  // Polling while transcription/analysis is in flight. Pauses when the tab
  // is hidden so we don't burn API quota for a window the user can't see;
  // resumes (with an immediate refresh) once the tab becomes visible again.
  useEffect(() => {
    if (!pollInFlight) return;

    let timer: ReturnType<typeof setInterval> | null = null;

    function start() {
      if (timer) return;
      timer = setInterval(() => void refresh(), POLL_INTERVAL);
    }

    function stop() {
      if (timer) {
        clearInterval(timer);
        timer = null;
      }
    }

    function onVisibility() {
      if (document.hidden) {
        stop();
      } else {
        void refresh();
        start();
      }
    }

    if (!document.hidden) start();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      stop();
    };
  }, [pollInFlight, refresh]);

  const competenceDictionary = (() => {
    const dict: Record<string, { name?: string }> = {};
    const items =
      ((profile?.profile_data?.competences as
        | (CompetenceItem & { id?: string })[]
        | undefined) ?? []);
    for (const c of items) {
      const key = c.id || c.name;
      if (key) dict[key] = { name: c.name };
    }
    return dict;
  })();

  function seekTo(sec: number) {
    const player =
      playerRef.current || videoRef.current || audioRef.current;
    if (!player) return;
    player.currentTime = sec;
  }

  async function handleTranscribe() {
    if (!interview) return;
    setBusyAction("transcribe");
    try {
      await api.post(
        `/recruitment/interviews/${interview.id}/transcribe`,
      );
      toast.success(t("interviewToastTranscriptionStarted"));
      await refresh();
    } catch (err) {
      toast.error(
        err instanceof Error
          ? err.message
          : t("interviewTranscriptionStartFailed"),
      );
    } finally {
      setBusyAction(null);
    }
  }

  async function handleAnalyze() {
    if (!interview) return;
    setBusyAction("analyze");
    try {
      await api.post(
        `/recruitment/interviews/${interview.id}/analyze`,
      );
      toast.success(t("interviewToastAnalysisStarted"));
      await refresh();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("interviewAnalysisStartFailed"),
      );
    } finally {
      setBusyAction(null);
    }
  }

  async function saveField(patch: Record<string, unknown>) {
    if (!interview) return;
    setSavingField(true);
    try {
      const updated = await api.put<Interview>(
        `/recruitment/interviews/${interview.id}`,
        patch,
      );
      setInterview(updated);
      setEditing(null);
      toast.success(t("interviewDetailsSaved"));
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("interviewDetailsSaveFailed"),
      );
    } finally {
      setSavingField(false);
    }
  }

  function startEdit(field: Exclude<EditableField, null>) {
    if (!interview) return;
    const split = splitLocalDateTime(interview.interview_date);
    setDraft({
      title: interview.title ?? "",
      type: interview.type ?? "undecided",
      date: split.date,
      time: split.time,
      duration: interview.duration_minutes
        ? String(interview.duration_minutes)
        : "",
      notes: interview.notes ?? "",
    });
    setEditing(field);
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16 text-muted-foreground">
        <Loader2 className="size-4 animate-spin" />
        {t("loading")}
      </div>
    );
  }
  if (!interview) {
    return (
      <div className="rounded-md border border-dashed p-12 text-center text-muted-foreground">
        {t("interviewNotFoundOrDeleted")}
      </div>
    );
  }

  const candidateName = cvCtx?.candidate_name || tc("candidate");
  const roundLabel = interview.round_id
    ? (() => {
        const found = rounds.find((r) => r.id === interview.round_id);
        return found ? labelForAssessmentRound(t, found) : null;
      })()
    : null;
  const subtitleParts = [cvCtx?.vacancy_title, roundLabel].filter(
    Boolean,
  ) as string[];
  const interviewerNames = (interview.interviewer_ids ?? [])
    .map((id) => people.find((p) => p.id === id)?.full_name)
    .filter(Boolean) as string[];
  // HRP-387: an interview created by dropping a file has no type of its own
  // until the upload lands; afterwards the type is a property of the asset
  // and stops being hand-editable.
  const typeLocked = Boolean(
    interview.audio_file_id ||
      interview.video_file_id ||
      interview.transcript_file_id,
  );
  const typeLabels: Record<string, string> = {
    audio: t("candidateInterviewsTypeAudio"),
    video: t("candidateInterviewsTypeVideo"),
    text_transcript: t("candidateInterviewsTypeTextTranscript"),
    undecided: t("candidateInterviewsTypeUndecided"),
  };

  return (
    <div data-testid="recruitment-interview-detail" className="space-y-5">
      <RecruitmentBreadcrumbs
        segments={[
          { label: t("candidatesTitle"), href: "/recruitment/candidates" },
          cvCtx?.candidate_id
            ? {
                label: candidateName,
                href: `/recruitment/candidates/${cvCtx.candidate_id}`,
              }
            : { label: candidateName },
          { label: t("interviewBreadcrumb") },
        ]}
      />

      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          {editing === "title" ? (
            <div className="flex items-center gap-2">
              <Input
                value={draft.title ?? ""}
                maxLength={100}
                onChange={(e) =>
                  setDraft((p) => ({ ...p, title: e.target.value }))
                }
                className="h-9 w-72"
                data-testid="recruitment-interview-title-input"
              />
              <Button
                size="icon-sm"
                disabled={savingField}
                onClick={() => saveField({ title: draft.title?.trim() || null })}
                aria-label={t("save")}
                data-testid="recruitment-interview-title-save"
              >
                <Check className="size-4" />
              </Button>
              <Button
                size="icon-sm"
                variant="ghost"
                onClick={() => setEditing(null)}
                aria-label={tc("cancel")}
              >
                <X className="size-4" />
              </Button>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <h1
                className="truncate text-xl font-semibold tracking-tight"
                data-testid="recruitment-interview-title"
              >
                {interview.title ||
                  t("interviewHeading", { name: candidateName })}
              </h1>
              <Button
                size="icon-sm"
                variant="ghost"
                onClick={() => startEdit("title")}
                aria-label={t("interviewEditTitleAria")}
                data-testid="recruitment-interview-title-edit"
              >
                <Pencil className="size-3.5" />
              </Button>
            </div>
          )}
          <p
            className="text-sm text-muted-foreground"
            data-testid="recruitment-interview-subtitle"
          >
            {subtitleParts.length > 0
              ? subtitleParts.join(" · ")
              : t("interviewNoVacancyContext")}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            render={
              cvCtx?.candidate_id ? (
                <Link
                  href={`/recruitment/candidates/${cvCtx.candidate_id}`}
                />
              ) : undefined
            }
            disabled={!cvCtx?.candidate_id}
          >
            {t("interviewBackToCandidate")}
          </Button>
        </div>
      </header>

      <section
        className="rounded-lg border bg-card p-4"
        data-testid="recruitment-interview-details"
      >
        <h2 className="mb-3 text-sm font-medium">
          {t("interviewDetailsHeading")}
        </h2>
        <dl className="grid gap-4 sm:grid-cols-3">
          <DetailField label={tc("candidate")}>
            {cvCtx?.candidate_id ? (
              <Link
                href={`/recruitment/candidates/${cvCtx.candidate_id}`}
                className="hover:underline"
              >
                {candidateName}
              </Link>
            ) : (
              candidateName
            )}
          </DetailField>

          <DetailField
            label={t("interviewDetailType")}
            onEdit={typeLocked ? undefined : () => startEdit("type")}
            editAria={t("interviewEditTypeAria")}
            testId="recruitment-interview-detail-type"
          >
            {editing === "type" ? (
              <div className="flex items-center gap-2">
                <Select
                  value={draft.type ?? "undecided"}
                  onValueChange={(v) => setDraft((p) => ({ ...p, type: v }))}
                >
                  <SelectTrigger
                    className="h-8 w-40"
                    data-testid="recruitment-interview-type-select"
                  >
                    <SelectValue>
                      {(value) => typeLabels[String(value)] ?? EM_DASH}
                    </SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {(
                      [
                        "audio",
                        "video",
                        "text_transcript",
                        "undecided",
                      ] as InterviewType[]
                    ).map((option) => (
                      <SelectItem key={option} value={option}>
                        {typeLabels[option]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button
                  size="icon-sm"
                  disabled={savingField}
                  onClick={() => saveField({ type: draft.type })}
                  aria-label={t("save")}
                  data-testid="recruitment-interview-type-save"
                >
                  <Check className="size-4" />
                </Button>
                <Button
                  size="icon-sm"
                  variant="ghost"
                  onClick={() => setEditing(null)}
                  aria-label={tc("cancel")}
                >
                  <X className="size-4" />
                </Button>
              </div>
            ) : (
              (typeLabels[interview.type ?? "undecided"] ?? EM_DASH)
            )}
          </DetailField>

          <DetailField label={t("columnStatus")}>
            {interview.status}
          </DetailField>

          <DetailField label={t("interviewDetailAdded")}>
            {formatDate(interview.created_at) || EM_DASH}
          </DetailField>

          <DetailField
            label={t("candidateInterviewsFieldDate")}
            onEdit={() => startEdit("schedule")}
            editAria={t("interviewEditScheduleAria")}
            testId="recruitment-interview-detail-schedule"
          >
            {editing === "schedule" ? (
              <div className="flex flex-wrap items-center gap-2">
                <Input
                  type="date"
                  className="h-8 w-36"
                  value={draft.date ?? ""}
                  onChange={(e) =>
                    setDraft((p) => ({ ...p, date: e.target.value }))
                  }
                  data-testid="recruitment-interview-date-input"
                />
                <Input
                  type="time"
                  className="h-8 w-28"
                  value={draft.time ?? ""}
                  onChange={(e) =>
                    setDraft((p) => ({ ...p, time: e.target.value }))
                  }
                  data-testid="recruitment-interview-time-input"
                />
                <Input
                  type="number"
                  min={1}
                  className="h-8 w-24"
                  value={draft.duration ?? ""}
                  onChange={(e) =>
                    setDraft((p) => ({ ...p, duration: e.target.value }))
                  }
                  data-testid="recruitment-interview-duration-input"
                />
                <Button
                  size="icon-sm"
                  disabled={savingField}
                  onClick={() =>
                    saveField({
                      interview_date: joinLocalDateTime(
                        draft.date ?? "",
                        draft.time ?? "",
                      ),
                      timezone:
                        Intl.DateTimeFormat().resolvedOptions().timeZone,
                      duration_minutes:
                        Number(draft.duration) > 0
                          ? Number(draft.duration)
                          : null,
                    })
                  }
                  aria-label={t("save")}
                  data-testid="recruitment-interview-schedule-save"
                >
                  <Check className="size-4" />
                </Button>
                <Button
                  size="icon-sm"
                  variant="ghost"
                  onClick={() => setEditing(null)}
                  aria-label={tc("cancel")}
                >
                  <X className="size-4" />
                </Button>
              </div>
            ) : (
              formatDateTime(interview.interview_date) || EM_DASH
            )}
          </DetailField>

          <DetailField label={t("interviewDetailDuration")}>
            {interview.duration_minutes
              ? t("interviewDetailDurationMinutes", {
                  minutes: interview.duration_minutes,
                })
              : EM_DASH}
          </DetailField>

          <DetailField
            label={t("candidateInterviewsFieldInterviewers")}
            className="sm:col-span-3"
          >
            {interviewerNames.length > 0
              ? interviewerNames.join(", ")
              : EM_DASH}
          </DetailField>
        </dl>
      </section>

      <section
        className="rounded-lg border bg-card p-4"
        data-testid="recruitment-interview-notes"
      >
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-medium">{t("candidateFieldNotes")}</h2>
          {editing === "notes" ? (
            <div className="flex items-center gap-1">
              <Button
                size="sm"
                disabled={savingField}
                onClick={() => saveField({ notes: draft.notes ?? "" })}
                data-testid="recruitment-interview-notes-save"
              >
                {t("save")}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setEditing(null)}
              >
                {tc("cancel")}
              </Button>
            </div>
          ) : (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => startEdit("notes")}
              data-testid="recruitment-interview-notes-edit"
            >
              <Pencil className="size-3.5" />
              {t("actionEdit")}
            </Button>
          )}
        </div>
        {editing === "notes" ? (
          <Textarea
            rows={4}
            maxLength={1000}
            value={draft.notes ?? ""}
            onChange={(e) => setDraft((p) => ({ ...p, notes: e.target.value }))}
            data-testid="recruitment-interview-notes-input"
          />
        ) : (
          <p className="whitespace-pre-wrap text-sm text-muted-foreground">
            {interview.notes?.trim() || t("interviewNoNotes")}
          </p>
        )}
      </section>

      {/* L-3 layout: 60/40 split with progress checklist on top of the right panel */}
      <div className="grid gap-4 lg:grid-cols-5">
        {/* LEFT — player + transcript */}
        <div className="space-y-4 lg:col-span-3">
          <section className="rounded-lg border bg-muted/30 p-3">
            {!interview.audio_file_id &&
            !interview.video_file_id &&
            !interview.transcript_file_id ? (
              <div className="space-y-3">
                <p className="text-sm text-muted-foreground">
                  {t("interviewNoRecording")}
                </p>
                <InterviewUploadZone
                  interviewId={interview.id}
                  consentSigned={!!interview.consent_signed_at}
                  interviewType={interview.type}
                  onUploaded={(updated) => {
                    setInterview(updated);
                    void refresh();
                  }}
                />
                <div className="flex items-center justify-center text-xs text-muted-foreground">
                  {t("interviewOr")}
                </div>
                <div className="flex items-center justify-center">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setTextPasteOpen(true)}
                    data-testid="recruitment-interview-btn-paste-text"
                  >
                    <FileText className="size-4" />
                    {t("interviewPasteText")}
                  </Button>
                </div>
              </div>
            ) : !media ? (
              <div className="flex items-center justify-center py-6 text-sm text-muted-foreground">
                <Loader2 className="size-4 animate-spin" />
                {t("interviewFetchingLink")}
              </div>
            ) : media.kind === "text_transcript" ? (
              <object
                data={media.url}
                type={media.mime_type || "application/pdf"}
                className="h-[480px] w-full rounded-md bg-white"
                data-testid="recruitment-interview-pdf-viewer"
              >
                <a
                  href={media.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm text-muted-foreground underline"
                >
                  {t("interviewOpenTranscriptFile")}
                </a>
              </object>
            ) : (
              <InterviewPlayer
                src={media.url}
                kind={media.kind}
                onTime={setCurrentSec}
                refSetter={(el) => {
                  playerRef.current = el;
                }}
              />
            )}
          </section>

          <section className="space-y-2">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-medium">
                {t("interviewTranscriptHeading")}
              </h2>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setEditTranscriptOpen(true)}
                disabled={!interview.transcript && interview.segments.length === 0}
                data-testid="recruitment-interview-btn-edit-transcript"
              >
                <Pencil className="size-3.5" />
                {t("interviewEditTranscript")}
              </Button>
            </div>
            <TranscriptViewer
              interview={interview}
              currentSec={currentSec}
              onSeek={seekTo}
              onSegmentChange={() => void refresh()}
            />
          </section>
        </div>

        {/* RIGHT — progress checklist + AI analysis */}
        <aside className="space-y-4 lg:col-span-2">
          <section className="rounded-lg border bg-card p-3">
            <h2 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              {t("interviewProgressHeading")}
            </h2>
            <AnalysisProgress interview={interview} />
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={handleTranscribe}
                disabled={
                  busyAction !== null ||
                  interview.transcription_status === "processing" ||
                  (!interview.audio_file_id && !interview.video_file_id)
                }
                data-testid="recruitment-interview-btn-transcribe"
              >
                {busyAction === "transcribe" ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <Wand2 className="size-4" />
                )}
                {interview.transcription_status === "completed"
                  ? t("interviewRetranscribe")
                  : t("interviewTranscribe")}
              </Button>
              <Button
                size="sm"
                onClick={handleAnalyze}
                disabled={
                  busyAction !== null ||
                  interview.analysis_status === "processing" ||
                  interview.transcription_status !== "completed"
                }
                data-testid="recruitment-interview-btn-analyze"
              >
                {busyAction === "analyze" ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <Sparkles className="size-4" />
                )}
                {t("interviewAnalyze")}
              </Button>
            </div>
          </section>

          <section>
            <h2 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              {t("interviewAiAnalysisHeading")}
            </h2>
            <InterviewAnalysisPanel
              interview={interview}
              competences={competenceDictionary}
              onSeek={seekTo}
            />
          </section>
        </aside>
      </div>

      <TranscriptEditDialog
        open={editTranscriptOpen}
        onOpenChange={setEditTranscriptOpen}
        interview={interview}
        onUpdated={(updated) => setInterview(updated)}
      />

      <InterviewTextTranscriptDialog
        open={textPasteOpen}
        onOpenChange={setTextPasteOpen}
        interviewId={interview.id}
        onSaved={(updated) => {
          setInterview(updated);
          void refresh();
        }}
      />
    </div>
  );
}

/** One cell of the Details block (HRP-387). Renders an em dash for the
 *  auto-created cards that have nothing to show yet, and an inline pencil
 *  for the fields the recruiter may still change. */
function DetailField({
  label,
  children,
  onEdit,
  editAria,
  testId,
  className,
}: {
  label: string;
  children: React.ReactNode;
  onEdit?: () => void;
  editAria?: string;
  testId?: string;
  className?: string;
}) {
  return (
    <div className={className} data-testid={testId}>
      <dt className="text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </dt>
      <dd className="mt-0.5 flex items-center gap-1 text-sm">
        <span className="min-w-0">{children}</span>
        {onEdit && (
          <Button
            size="icon-sm"
            variant="ghost"
            onClick={onEdit}
            aria-label={editAria}
            data-testid={testId ? `${testId}-edit` : undefined}
          >
            <Pencil className="size-3" />
          </Button>
        )}
      </dd>
    </div>
  );
}
