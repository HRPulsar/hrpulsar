"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent,
} from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import {
  CalendarPlus,
  ExternalLink,
  FileAudio,
  FileText,
  FileVideo,
  Mic,
  ShieldAlert,
  Upload,
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
import { Checkbox } from "@/components/ui/checkbox";
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
import { api } from "@/lib/api";
import { formatDate } from "@/lib/date-format";
import {
  UPLOAD_ACCEPT_ATTR,
  detectKind,
  UploadError,
  uploadInterviewMedia,
} from "@/lib/interview-upload";
import type { ConsentRequest, Interview, InterviewType } from "@/lib/types";

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
  candidateEmail?: string | null;
}

interface FileProgress {
  name: string;
  fraction: number;
  status: "uploading" | "done" | "failed";
  error?: string;
}

const TYPE_ICON: Record<string, typeof Mic> = {
  audio: FileAudio,
  video: FileVideo,
  text_transcript: FileText,
  undecided: Mic,
};

const PROCESSING_TONE: Record<string, string> = {
  pending: "text-muted-foreground",
  processing: "text-amber-600",
  completed: "text-emerald-600",
  failed: "text-rose-600",
};

function processingBadge(label: string, status?: string | null) {
  if (!status || status === "pending") return null;
  return (
    <span className={`text-xs ${PROCESSING_TONE[status] ?? ""}`}>
      {label}: {status}
    </span>
  );
}

export function CandidateInterviewsSection({
  candidateId,
  vacancyOptions,
  initialVacancyId,
  candidateEmail,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [vacancyId, setVacancyId] = useState<string | undefined>(
    initialVacancyId || vacancyOptions[0]?.id,
  );
  const [interviews, setInterviews] = useState<Interview[]>([]);
  const [loading, setLoading] = useState(true);
  const [consent, setConsent] = useState<ConsentRequest | null>(null);
  const [consentLoaded, setConsentLoaded] = useState(false);
  const [scheduleOpen, setScheduleOpen] = useState(false);
  const [autoProcess, setAutoProcess] = useState(true);
  const [uploads, setUploads] = useState<FileProgress[]>([]);
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [sendingConsent, setSendingConsent] = useState(false);
  const t = useTranslations("recruitment");

  const currentVacancy = useMemo(
    () => vacancyOptions.find((v) => v.id === vacancyId),
    [vacancyOptions, vacancyId],
  );
  const cvId = currentVacancy?.candidate_vacancy_id;
  const consentSigned = consent?.status === "signed";

  const loadInterviews = useCallback(async () => {
    if (!cvId) {
      setInterviews([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const rows = await api.get<Interview[]>(
        `/recruitment/candidate-vacancies/${cvId}/interviews`,
      );
      setInterviews(rows.filter((r) => !r.archived_at));
    } catch {
      setInterviews([]);
    } finally {
      setLoading(false);
    }
  }, [cvId]);

  useEffect(() => {
    loadInterviews();
  }, [loadInterviews]);

  useEffect(() => {
    let cancelled = false;
    api
      .get<ConsentRequest | null>(
        `/recruitment/candidates/${candidateId}/consent/latest`,
      )
      .then((c) => {
        if (!cancelled) setConsent(c);
      })
      .catch(() => {
        if (!cancelled) setConsent(null);
      })
      .finally(() => {
        if (!cancelled) setConsentLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [candidateId]);

  // Interviews still transcribing / analyzing: poll so statuses flip
  // without a manual refresh (REDO checklist §5 — no F5 required).
  const hasActiveProcessing = interviews.some(
    (i) =>
      i.transcription_status === "processing" ||
      i.analysis_status === "processing",
  );
  useEffect(() => {
    if (!hasActiveProcessing) return;
    const timer = setInterval(() => {
      // Skip ticks while the tab is hidden — no one is watching the
      // status badges, so don't keep the backend busy.
      if (document.visibilityState === "visible") loadInterviews();
    }, 5000);
    return () => clearInterval(timer);
  }, [hasActiveProcessing, loadInterviews]);

  const handleFiles = useCallback(
    async (files: File[]) => {
      if (!cvId || files.length === 0) return;
      if (!consentSigned) {
        toast.error(t("candidateInterviewsConsentRequired"));
        return;
      }
      const invalid = files.filter((f) => detectKind(f) === null);
      if (invalid.length) {
        toast.error(
          t("candidateInterviewsUnsupportedType", {
            files: invalid.map((f) => f.name).join(", "),
          }),
        );
        return;
      }
      setUploading(true);
      setUploads(
        files.map((f) => ({ name: f.name, fraction: 0, status: "uploading" })),
      );
      // Progress rows are keyed by array index (1:1, order-stable with
      // `files`) — file names may collide when files come from different
      // folders.
      const patchUpload = (idx: number, patch: Partial<FileProgress>) =>
        setUploads((prev) =>
          prev.map((u, i) => (i === idx ? { ...u, ...patch } : u)),
        );
      let failed = 0;
      for (const [idx, file] of files.entries()) {
        try {
          const kind = detectKind(file);
          const created = await api.post<Interview>(
            `/recruitment/candidate-vacancies/${cvId}/interviews`,
            {
              title: file.name,
              type: (kind === "text_transcript"
                ? "text_transcript"
                : kind) as InterviewType,
            },
          );
          await uploadInterviewMedia(created.id, file, {
            autoProcess,
            onProgress: (fraction) => patchUpload(idx, { fraction }),
          });
          patchUpload(idx, { fraction: 1, status: "done" });
        } catch (err) {
          failed += 1;
          patchUpload(idx, {
            status: "failed",
            // UploadError carries a stable code — show localized text
            // instead of its technical English message.
            error:
              err instanceof UploadError
                ? err.code === "s3PutFailed"
                  ? t("uploadS3PutFailed", { status: err.status ?? 0 })
                  : err.code === "s3Unreachable"
                    ? t("uploadS3Unreachable")
                    : t("uploadS3NoEtag")
                : err instanceof Error
                  ? err.message
                  : t("candidateInterviewsUploadFailed"),
          });
        }
      }
      setUploading(false);
      if (failed === 0) {
        toast.success(
          t("candidateInterviewsUploaded", { count: files.length }),
        );
        setUploads([]);
      } else {
        toast.error(
          t("candidateInterviewsUploadsFailed", {
            failed,
            total: files.length,
          }),
        );
      }
      await loadInterviews();
      if (inputRef.current) inputRef.current.value = "";
    },
    [cvId, consentSigned, autoProcess, loadInterviews, t],
  );

  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragOver(false);
    if (uploading) return;
    handleFiles(Array.from(e.dataTransfer.files));
  }

  async function sendConsentRequest() {
    if (!candidateEmail) {
      toast.error(t("candidateInterviewsNoEmail"));
      return;
    }
    setSendingConsent(true);
    try {
      const created = await api.post<ConsentRequest>(
        `/recruitment/candidates/${candidateId}/consent/send`,
        { email: candidateEmail },
      );
      setConsent(created);
      toast.success(t("candidateInterviewsConsentSent"));
    } catch (err) {
      toast.error(
        err instanceof Error
          ? err.message
          : t("candidateInterviewsConsentSendFailed"),
      );
    } finally {
      setSendingConsent(false);
    }
  }

  return (
    <section
      data-testid="recruitment-candidate-interviews-section"
      className="space-y-3"
    >
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Mic className="h-5 w-5 text-sky-600" />
          <h2 className="text-lg font-semibold">
            {t("candidateInterviewsTitle")}
          </h2>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {vacancyOptions.length > 1 && (
            <Select value={vacancyId} onValueChange={setVacancyId}>
              <SelectTrigger
                className="w-64"
                data-testid="recruitment-candidate-interviews-vacancy-select"
              >
                <SelectValue placeholder={t("candidateInterviewsSelectVacancy")}>
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
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={() => setScheduleOpen(true)}
            disabled={!cvId}
            data-testid="recruitment-candidate-interviews-schedule-btn"
          >
            <CalendarPlus className="mr-1 h-4 w-4" />
            {t("candidateInterviewsScheduleButton")}
          </Button>
        </div>
      </header>

      {consentLoaded && !consentSigned && (
        <div
          className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm dark:border-amber-900 dark:bg-amber-950/40"
          data-testid="recruitment-candidate-interviews-consent-banner"
        >
          <span className="inline-flex items-center gap-2">
            <ShieldAlert className="h-4 w-4 text-amber-600" />
            {consent?.status === "pending"
              ? t("candidateInterviewsConsentPending")
              : t("candidateInterviewsConsentMissing")}
          </span>
          {consent?.status !== "pending" && (
            <Button
              variant="outline"
              size="sm"
              onClick={sendConsentRequest}
              disabled={sendingConsent}
              data-testid="recruitment-candidate-interviews-consent-send-btn"
            >
              {sendingConsent
                ? t("candidateInterviewsSending")
                : t("candidateInterviewsSendConsent")}
            </Button>
          )}
        </div>
      )}

      <div
        role="button"
        tabIndex={0}
        aria-label={t("candidateInterviewsDropzoneAria")}
        onClick={() => !uploading && consentSigned && inputRef.current?.click()}
        onKeyDown={(e) => {
          if ((e.key === "Enter" || e.key === " ") && !uploading && consentSigned) {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        className={`cursor-pointer rounded-lg border border-dashed p-6 text-center transition ${
          dragOver ? "border-sky-500 bg-sky-50 dark:bg-sky-950/30" : ""
        } ${!consentSigned || uploading ? "cursor-not-allowed opacity-60" : ""}`}
        data-testid="recruitment-candidate-interviews-dropzone"
      >
        <Upload className="mx-auto mb-2 h-6 w-6 text-muted-foreground/60" />
        <p className="text-sm font-medium">
          {t("candidateInterviewsDropzoneTitle")}
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          {t("candidateInterviewsDropzoneHint")}
        </p>
        <input
          ref={inputRef}
          type="file"
          multiple
          hidden
          accept={UPLOAD_ACCEPT_ATTR}
          onChange={(e) =>
            handleFiles(Array.from(e.currentTarget.files ?? []))
          }
          data-testid="recruitment-candidate-interviews-file-input"
        />
      </div>

      <label className="flex items-center gap-2 text-sm">
        <Checkbox
          checked={autoProcess}
          onCheckedChange={(checked) => setAutoProcess(Boolean(checked))}
          data-testid="recruitment-candidate-interviews-auto-process"
        />
        {t("candidateInterviewsAutoProcess")}
      </label>

      {uploads.length > 0 && (
        <div className="space-y-1" data-testid="recruitment-candidate-interviews-progress">
          {uploads.map((u, idx) => (
            <div key={idx} className="flex items-center gap-2 text-xs">
              <span className="w-56 truncate">{u.name}</span>
              <div className="h-1.5 flex-1 overflow-hidden rounded bg-muted">
                <div
                  className={`h-full ${
                    u.status === "failed" ? "bg-rose-500" : "bg-sky-500"
                  }`}
                  style={{ width: `${Math.round(u.fraction * 100)}%` }}
                />
              </div>
              <span className="w-20 text-right text-muted-foreground">
                {u.status === "failed"
                  ? t("candidateInterviewsUploadStatusFailed")
                  : u.status === "done"
                    ? t("candidateInterviewsUploadStatusDone")
                    : `${Math.round(u.fraction * 100)}%`}
              </span>
            </div>
          ))}
        </div>
      )}

      <Card>
        <CardHeader className="py-3">
          <CardTitle className="text-base">
            {t("candidateInterviewsRoundsCount", { count: interviews.length })}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {loading ? (
            <p className="text-sm text-muted-foreground">{t("loading")}</p>
          ) : interviews.length === 0 ? (
            <p
              className="text-sm text-muted-foreground"
              data-testid="recruitment-candidate-interviews-empty"
            >
              {t("candidateInterviewsEmpty")}
            </p>
          ) : (
            interviews.map((iv) => {
              const Icon = TYPE_ICON[iv.type ?? "undecided"] ?? Mic;
              return (
                <div
                  key={iv.id}
                  className="flex flex-wrap items-center gap-3 rounded-md border p-3"
                  data-testid={`recruitment-candidate-interview-row-${iv.id}`}
                >
                  <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">
                      {iv.title ||
                        (iv.interview_date
                          ? t("candidateInterviewsRowTitleDated", {
                              date: formatDate(iv.interview_date),
                            })
                          : t("interviewBreadcrumb"))}
                    </p>
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant="outline" className="text-xs">
                        {iv.status}
                      </Badge>
                      {processingBadge(
                        t("candidateInterviewsTranscriptLabel"),
                        iv.transcription_status,
                      )}
                      {processingBadge(
                        t("candidateInterviewsAiLabel"),
                        iv.analysis_status,
                      )}
                      {iv.auto_process && (
                        <Badge variant="secondary" className="text-xs">
                          {t("candidateInterviewsAutoBadge")}
                        </Badge>
                      )}
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    render={<Link href={`/recruitment/interviews/${iv.id}`} />}
                    data-testid={`recruitment-candidate-interview-open-${iv.id}`}
                  >
                    {t("candidateInterviewsOpen")}
                    <ExternalLink className="ml-1 h-3.5 w-3.5" />
                  </Button>
                </div>
              );
            })
          )}
        </CardContent>
      </Card>

      <ScheduleDialog
        open={scheduleOpen}
        onOpenChange={setScheduleOpen}
        cvId={cvId}
        onCreated={() => {
          setScheduleOpen(false);
          loadInterviews();
        }}
      />
    </section>
  );
}

interface ScheduleDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  cvId?: string;
  onCreated: () => void;
}

function ScheduleDialog({
  open,
  onOpenChange,
  cvId,
  onCreated,
}: ScheduleDialogProps) {
  const [title, setTitle] = useState("");
  const [date, setDate] = useState("");
  const [duration, setDuration] = useState("60");
  const [type, setType] = useState<InterviewType>("undecided");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");

  async function submit() {
    if (!cvId) return;
    setBusy(true);
    try {
      await api.post<Interview>(
        `/recruitment/candidate-vacancies/${cvId}/interviews`,
        {
          title: title.trim() || null,
          interview_date: date ? new Date(date).toISOString() : null,
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
          duration_minutes: Number(duration) || null,
          type,
          notes: notes.trim() || null,
        },
      );
      toast.success(t("candidateInterviewsScheduled"));
      setTitle("");
      setDate("");
      setNotes("");
      onCreated();
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

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-w-md"
        data-testid="recruitment-candidate-interviews-schedule-dialog"
      >
        <DialogHeader>
          <DialogTitle>{t("candidateInterviewsScheduleButton")}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1">
            <Label htmlFor="iv-title">{t("columnTitle")}</Label>
            <Input
              id="iv-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={t("candidateInterviewsTitlePlaceholder")}
              data-testid="recruitment-candidate-interviews-schedule-title"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label htmlFor="iv-date">
                {t("candidateInterviewsFieldDate")}
              </Label>
              <Input
                id="iv-date"
                type="datetime-local"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                data-testid="recruitment-candidate-interviews-schedule-date"
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
              />
            </div>
          </div>
          <div className="space-y-1">
            <Label>{t("candidateInterviewsFieldType")}</Label>
            <Select
              value={type}
              onValueChange={(v) => setType(v as InterviewType)}
            >
              <SelectTrigger data-testid="recruitment-candidate-interviews-schedule-type">
                <SelectValue>
                  {(value) =>
                    ({
                      audio: t("candidateInterviewsTypeAudio"),
                      video: t("candidateInterviewsTypeVideo"),
                      text_transcript: t(
                        "candidateInterviewsTypeTextTranscript",
                      ),
                      undecided: t("candidateInterviewsTypeUndecided"),
                    })[value as InterviewType] ??
                    t("candidateInterviewsTypeUndecided")
                  }
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="undecided">
                  {t("candidateInterviewsTypeUndecided")}
                </SelectItem>
                <SelectItem value="audio">
                  {t("candidateInterviewsTypeAudio")}
                </SelectItem>
                <SelectItem value="video">
                  {t("candidateInterviewsTypeVideo")}
                </SelectItem>
                <SelectItem value="text_transcript">
                  {t("candidateInterviewsTypeTextTranscript")}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <Label htmlFor="iv-notes">{t("candidateFieldNotes")}</Label>
            <Textarea
              id="iv-notes"
              rows={2}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
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
            {busy
              ? t("candidateInterviewsSaving")
              : t("candidateInterviewsSchedule")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
