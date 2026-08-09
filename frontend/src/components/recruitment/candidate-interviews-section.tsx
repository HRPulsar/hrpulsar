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
  ArchiveRestore,
  CalendarPlus,
  FileAudio,
  FileText,
  FileVideo,
  Mic,
  MoreVertical,
  Pencil,
  ShieldAlert,
  Trash2,
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
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ApiError, api } from "@/lib/api";
import { formatDate } from "@/lib/date-format";
import {
  UPLOAD_ACCEPT_ATTR,
  detectKind,
  UploadError,
  uploadInterviewMedia,
} from "@/lib/interview-upload";
import { labelForAssessmentRound } from "@/lib/recruitment-helpers";
import type {
  ConsentRequest,
  Interview,
  InterviewRoundOption,
  InterviewType,
} from "@/lib/types";
import { ScheduleInterviewDialog } from "./schedule-interview-dialog";

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
  const [rounds, setRounds] = useState<InterviewRoundOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [consent, setConsent] = useState<ConsentRequest | null>(null);
  const [consentLoaded, setConsentLoaded] = useState(false);
  const [scheduleOpen, setScheduleOpen] = useState(false);
  const [editing, setEditing] = useState<Interview | null>(null);
  const [pendingArchive, setPendingArchive] = useState<Interview | null>(null);
  const [showArchived, setShowArchived] = useState(false);
  const [autoProcess, setAutoProcess] = useState(true);
  const [uploads, setUploads] = useState<FileProgress[]>([]);
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [sendingConsent, setSendingConsent] = useState(false);
  // HRP-472: a snackbar disappeared before the recruiter could read where
  // consent templates are configured — this is a modal now.
  const [consentSetupOpen, setConsentSetupOpen] = useState(false);
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");

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
        `/recruitment/candidate-vacancies/${cvId}/interviews?include_archived=true`,
      );
      setInterviews(rows);
    } catch {
      setInterviews([]);
    } finally {
      setLoading(false);
    }
  }, [cvId]);

  useEffect(() => {
    loadInterviews();
  }, [loadInterviews]);

  // HRP-418: rows render "Interview 1 · added yyyy-mm-dd" — the round part
  // needs the Manager-assessment rounds of the same candidate-vacancy.
  useEffect(() => {
    if (!cvId) {
      setRounds([]);
      return;
    }
    let cancelled = false;
    api
      .get<InterviewRoundOption[]>(
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
  }, [cvId]);

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

  const visibleInterviews = useMemo(
    () =>
      showArchived
        ? interviews
        : interviews.filter((iv) => !iv.archived_at),
    [interviews, showArchived],
  );
  const archivedCount = useMemo(
    () => interviews.filter((iv) => iv.archived_at).length,
    [interviews],
  );

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
      // HRP-472: the only 409 this endpoint raises is "no active consent
      // template". It needs a modal — the user has to go configure one.
      if (err instanceof ApiError && err.status === 409) {
        setConsentSetupOpen(true);
      } else {
        toast.error(
          err instanceof Error
            ? err.message
            : t("candidateInterviewsConsentSendFailed"),
        );
      }
    } finally {
      setSendingConsent(false);
    }
  }

  async function archiveInterview(interview: Interview) {
    try {
      await api.post(`/recruitment/interviews/${interview.id}/archive`);
      toast.success(t("candidateInterviewsArchived"));
      await loadInterviews();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("candidateInterviewsArchiveFailed"),
      );
    }
  }

  async function restoreInterview(interview: Interview) {
    try {
      await api.post(`/recruitment/interviews/${interview.id}/restore`);
      toast.success(t("candidateInterviewsRestored"));
      await loadInterviews();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("candidateInterviewsRestoreFailed"),
      );
    }
  }

  function roundLabelFor(interview: Interview): string | null {
    if (!interview.round_id) return null;
    const found = rounds.find((r) => r.id === interview.round_id);
    return found ? labelForAssessmentRound(t, found) : null;
  }

  return (
    <Card
      data-testid="recruitment-candidate-interviews-section"
      className="gap-3"
    >
      <CardHeader className="flex flex-wrap items-center justify-between gap-3">
        <CardTitle className="flex items-center gap-2 text-lg">
          <Mic className="h-5 w-5 text-sky-600" />
          {t("candidateInterviewsTitle")}
          <span
            className="text-muted-foreground"
            data-testid="recruitment-candidate-interviews-count"
          >
            {t("candidateInterviewsCount", {
              count: visibleInterviews.length,
            })}
          </span>
        </CardTitle>
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
      </CardHeader>

      <CardContent className="space-y-3">
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

        <div className="flex flex-wrap items-center justify-between gap-3">
          <label className="flex items-center gap-2 text-sm">
            <Checkbox
              checked={autoProcess}
              onCheckedChange={(checked) => setAutoProcess(Boolean(checked))}
              data-testid="recruitment-candidate-interviews-auto-process"
            />
            {t("candidateInterviewsAutoProcess")}
          </label>
          {(archivedCount > 0 || showArchived) && (
            <label className="flex items-center gap-2 text-sm text-muted-foreground">
              <Checkbox
                checked={showArchived}
                onCheckedChange={(checked) => setShowArchived(Boolean(checked))}
                data-testid="recruitment-candidate-interviews-show-archived"
              />
              {t("candidateInterviewsShowArchived", { count: archivedCount })}
            </label>
          )}
        </div>

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

        <div className="space-y-2">
          {loading ? (
            <p className="text-sm text-muted-foreground">{t("loading")}</p>
          ) : visibleInterviews.length === 0 ? (
            <p
              className="text-sm text-muted-foreground"
              data-testid="recruitment-candidate-interviews-empty"
            >
              {t("candidateInterviewsEmpty")}
            </p>
          ) : (
            visibleInterviews.map((iv) => {
              const Icon = TYPE_ICON[iv.type ?? "undecided"] ?? Mic;
              const isArchived = Boolean(iv.archived_at);
              const round = roundLabelFor(iv);
              const fallbackTitle = iv.interview_date
                ? t("candidateInterviewsRowTitleDated", {
                    date: formatDate(iv.interview_date),
                  })
                : t("interviewBreadcrumb");
              return (
                <div
                  key={iv.id}
                  className="flex flex-wrap items-center gap-3 rounded-md border p-3"
                  data-testid={`recruitment-candidate-interview-row-${iv.id}`}
                >
                  <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
                  <div className="min-w-0 flex-1">
                    <Link
                      href={`/recruitment/interviews/${iv.id}`}
                      className="block truncate text-sm font-medium hover:underline"
                      data-testid={`recruitment-candidate-interview-title-${iv.id}`}
                    >
                      {iv.title || fallbackTitle}
                    </Link>
                    <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                      <span
                        data-testid={`recruitment-candidate-interview-meta-${iv.id}`}
                      >
                        {round
                          ? t("candidateInterviewsRowMetaWithRound", {
                              round,
                              date: formatDate(iv.created_at),
                            })
                          : t("candidateInterviewsRowMeta", {
                              date: formatDate(iv.created_at),
                            })}
                      </span>
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
                  <Badge
                    variant="outline"
                    className="text-xs"
                    data-testid={`recruitment-candidate-interview-status-${iv.id}`}
                  >
                    {iv.status}
                  </Badge>
                  <DropdownMenu>
                    <DropdownMenuTrigger
                      aria-label={t("candidateInterviewsRowMenuAria")}
                      data-testid={`recruitment-candidate-interview-menu-${iv.id}`}
                      render={<Button variant="ghost" size="icon-sm" />}
                    >
                      <MoreVertical className="h-4 w-4" />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      {isArchived ? (
                        <DropdownMenuItem
                          onClick={() => restoreInterview(iv)}
                          data-testid={`recruitment-candidate-interview-restore-${iv.id}`}
                        >
                          <ArchiveRestore className="mr-2 h-4 w-4" />
                          {t("candidateInterviewsRestore")}
                        </DropdownMenuItem>
                      ) : (
                        <>
                          <DropdownMenuItem
                            onClick={() => setEditing(iv)}
                            data-testid={`recruitment-candidate-interview-edit-${iv.id}`}
                          >
                            <Pencil className="mr-2 h-4 w-4" />
                            {t("actionEdit")}
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            onClick={() => setPendingArchive(iv)}
                            data-testid={`recruitment-candidate-interview-archive-${iv.id}`}
                          >
                            <Trash2 className="mr-2 h-4 w-4" />
                            {t("candidateInterviewsArchive")}
                          </DropdownMenuItem>
                        </>
                      )}
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
              );
            })
          )}
        </div>
      </CardContent>

      <ScheduleInterviewDialog
        open={scheduleOpen}
        onOpenChange={setScheduleOpen}
        vacancyOptions={vacancyOptions}
        vacancyId={vacancyId}
        onSaved={() => {
          setScheduleOpen(false);
          loadInterviews();
        }}
      />

      <ScheduleInterviewDialog
        open={editing !== null}
        onOpenChange={(next) => {
          if (!next) setEditing(null);
        }}
        vacancyOptions={vacancyOptions}
        vacancyId={vacancyId}
        interview={editing}
        onSaved={() => {
          setEditing(null);
          loadInterviews();
        }}
      />

      <ConfirmDialog
        open={pendingArchive !== null}
        onOpenChange={(next) => {
          if (!next) setPendingArchive(null);
        }}
        title={t("candidateInterviewsArchiveConfirmTitle")}
        description={t("candidateInterviewsArchiveConfirmBody")}
        confirmLabel={t("candidateInterviewsArchive")}
        cancelLabel={tc("cancel")}
        destructive
        testId="recruitment-candidate-interviews-archive-confirm"
        onConfirm={async () => {
          if (pendingArchive) await archiveInterview(pendingArchive);
          setPendingArchive(null);
        }}
      />

      <Dialog open={consentSetupOpen} onOpenChange={setConsentSetupOpen}>
        <DialogContent data-testid="recruitment-candidate-interviews-consent-setup-dialog">
          <DialogHeader>
            <DialogTitle>{t("candidateInterviewsConsentSetupTitle")}</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            {t.rich("candidateInterviewsConsentSetupBody", {
              path: (chunks) => <em>{chunks}</em>,
            })}
          </p>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setConsentSetupOpen(false)}
            >
              {tc("close")}
            </Button>
            <Button
              render={
                <Link href="/recruitment/settings/consent-templates" />
              }
              data-testid="recruitment-candidate-interviews-consent-setup-link"
            >
              {t("candidateInterviewsConsentSetupAction")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
