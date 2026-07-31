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
  InterviewMediaURL,
  VacancyProfile,
} from "@/lib/types";
import { Button } from "@/components/ui/button";
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
import { FileText, Loader2, Pencil, Sparkles, Wand2 } from "lucide-react";
import { toast } from "sonner";
import { formatDateTime } from "@/lib/date-format";

const POLL_INTERVAL = 3000;

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

  // Once we know the vacancy id, fetch its profile to label competence ids.
  useEffect(() => {
    if (!cvCtx?.vacancy_id) return;
    api
      .get<{ profile: null } | VacancyProfile>(
        `/recruitment/vacancies/${cvCtx.vacancy_id}/profile`,
      )
      .then((res) => {
        if (res && "profile_data" in res) setProfile(res as VacancyProfile);
      })
      .catch(() => null);
  }, [cvCtx?.vacancy_id]);

  // Polling while transcription/analysis is in flight. Pauses when the tab
  // is hidden so we don't burn API quota for a window the user can't see;
  // resumes (with an immediate refresh) once the tab becomes visible again.
  useEffect(() => {
    if (!interview) return;
    const inFlight =
      interview.transcription_status === "processing" ||
      interview.analysis_status === "processing";
    if (!inFlight) return;

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
  }, [interview, refresh]);

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
        <div>
          <h1 className="text-xl font-semibold tracking-tight">
            {t("interviewHeading", { name: candidateName })}
          </h1>
          <p className="text-sm text-muted-foreground">
            {interview.interview_date
              ? formatDateTime(interview.interview_date)
              : t("interviewDateNotSet")}
            {cvCtx?.vacancy_title && ` · ${cvCtx.vacancy_title}`}
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
