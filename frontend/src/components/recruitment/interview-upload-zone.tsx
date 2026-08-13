"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type DragEvent,
} from "react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Loader2, Pause, Play, Upload, X } from "lucide-react";
import { api, ApiError, API_BASE } from "@/lib/api";
import type {
  InitUploadResponse,
  Interview,
  InterviewType,
  PartUrlResponse,
} from "@/lib/types";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { toast } from "sonner";

interface InterviewUploadZoneProps {
  interviewId: string;
  consentSigned: boolean;
  // HRP-405: the interview's declared recording type. When the dropped
  // file is of a different kind we ask before switching the type
  // ("undecided" is adopted silently — nothing to overwrite).
  interviewType?: InterviewType | null;
  onUploaded?: (interview: Interview) => void;
  onConsentMissing?: () => void;
}

type UploadKind = "audio" | "video" | "text_transcript";

import {
  MEDIA_MAX_BYTES,
  TRANSCRIPT_MAX_BYTES,
  UPLOAD_ACCEPT_ATTR,
  UploadError,
  detectKind,
  effectiveMime,
  putChunk,
  requiresTypeSwitchConfirm,
} from "@/lib/interview-upload";

interface ChunkResult {
  part_number: number;
  etag: string;
}

interface PersistedSession {
  uploadId: string;
  sessionId?: string | null;
  partSize: number;
  totalParts: number;
  fileName: string;
  fileSize: number;
  kind: "audio" | "video" | "text_transcript";
  mimeType: string;
  parts: ChunkResult[];
}

function storageKey(interviewId: string): string {
  return `hrp202-upload:${interviewId}`;
}

export function InterviewUploadZone({
  interviewId,
  consentSigned,
  interviewType,
  onUploaded,
  onConsentMissing,
}: InterviewUploadZoneProps) {
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const inputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [bytesUploaded, setBytesUploaded] = useState(0);
  const [activeFile, setActiveFile] = useState<File | null>(null);
  const [speedMbps, setSpeedMbps] = useState<number | null>(null);
  const [etaSec, setEtaSec] = useState<number | null>(null);
  const [paused, setPaused] = useState(false);
  const [resumable, setResumable] = useState<PersistedSession | null>(null);
  const [dragOver, setDragOver] = useState(false);
  // HRP-405: file whose kind contradicts the interview's declared type,
  // parked until the recruiter confirms the type switch.
  const [pendingKindSwitch, setPendingKindSwitch] = useState<{
    file: File;
    kind: UploadKind;
  } | null>(null);
  // Literal t() calls (not dynamic keys) keep next-intl's key typing and
  // the catalog-parity guard honest.
  const kindSwitchTitle: Record<UploadKind, string> = {
    audio: t("interviewUploadTypeSwitchAudio"),
    video: t("interviewUploadTypeSwitchVideo"),
    text_transcript: t("interviewUploadTypeSwitchTranscript"),
  };
  const interviewTypeLabel: Record<InterviewType, string> = {
    audio: t("candidateInterviewsTypeAudio"),
    video: t("candidateInterviewsTypeVideo"),
    text_transcript: t("candidateInterviewsTypeTextTranscript"),
    undecided: t("candidateInterviewsTypeUndecided"),
  };
  // HRP-202 REDO: chain transcribe -> analyze automatically once the
  // upload completes. Text transcripts skip the chain (no ASR needed).
  const [autoProcess, setAutoProcess] = useState(true);

  const stateRef = useRef<{
    cancelled: boolean;
    paused: boolean;
    uploadId: string | null;
  }>({ cancelled: false, paused: false, uploadId: null });

  useEffect(() => {
    try {
      const raw = localStorage.getItem(storageKey(interviewId));
      if (raw) setResumable(JSON.parse(raw) as PersistedSession);
    } catch {
      setResumable(null);
    }
  }, [interviewId]);

  const persist = useCallback(
    (session: PersistedSession) => {
      try {
        localStorage.setItem(
          storageKey(interviewId),
          JSON.stringify(session),
        );
      } catch {
        /* quota full — non-fatal */
      }
    },
    [interviewId],
  );

  const clearPersisted = useCallback(() => {
    try {
      localStorage.removeItem(storageKey(interviewId));
    } catch {
      /* ignore */
    }
    setResumable(null);
  }, [interviewId]);

  const reset = useCallback(() => {
    setUploading(false);
    setProgress(0);
    setBytesUploaded(0);
    setActiveFile(null);
    setSpeedMbps(null);
    setEtaSec(null);
    setPaused(false);
    stateRef.current = {
      cancelled: false,
      paused: false,
      uploadId: null,
    };
    if (inputRef.current) inputRef.current.value = "";
  }, []);

  const runUpload = useCallback(
    async (
      file: File,
      init: InitUploadResponse,
      kind: "audio" | "video" | "text_transcript",
      mimeType: string,
      initialParts: ChunkResult[] = [],
    ) => {
      const partSize = init.part_size;
      const totalParts = init.total_parts;
      const parts: ChunkResult[] = [...initialParts];
      stateRef.current.uploadId = init.upload_id;

      const startTime = performance.now();
      let baselineBytes = parts.reduce(
        (acc, _, idx) =>
          acc + Math.min(partSize, file.size - (parts.length - 1 - idx) * partSize),
        0,
      );
      baselineBytes = Math.min(file.size, parts.length * partSize);
      setBytesUploaded(baselineBytes);

      try {
        for (let n = 1; n <= totalParts; n++) {
          if (parts.some((p) => p.part_number === n)) continue;
          while (stateRef.current.paused && !stateRef.current.cancelled) {
            await new Promise((r) => setTimeout(r, 250));
          }
          if (stateRef.current.cancelled) {
            throw new Error(t("interviewUploadCancelledError"));
          }
          const start = (n - 1) * partSize;
          const end = Math.min(start + partSize, file.size);
          const chunk = file.slice(start, end);

          const partUrl = await api.post<PartUrlResponse>(
            `/recruitment/interviews/${interviewId}/upload/part-url`,
            { upload_id: init.upload_id, part_number: n },
          );
          const etag = await putChunk(partUrl.url, chunk);
          parts.push({ part_number: n, etag });

          // Persist server-side: TUS-style PATCH so HEAD can resume.
          try {
            await fetch(
              `${API_BASE}/recruitment/interviews/${interviewId}/upload/${init.upload_id}`,
              {
                method: "PATCH",
                headers: {
                  "Content-Type": "application/json",
                  "Upload-Offset": String(baselineBytes + (end - start)),
                  Authorization: `Bearer ${typeof window !== "undefined" ? localStorage.getItem("access_token") || "" : ""}`,
                },
                body: JSON.stringify({
                  part_number: n,
                  etag,
                  size: end - start,
                }),
              },
            );
          } catch {
            /* offset is also recoverable from S3 + parts on Complete */
          }

          baselineBytes += end - start;
          const elapsed = (performance.now() - startTime) / 1000;
          const speed = baselineBytes / Math.max(0.001, elapsed);
          const remaining = file.size - baselineBytes;
          setBytesUploaded(baselineBytes);
          setSpeedMbps(speed / (1024 * 1024));
          setEtaSec(speed > 0 ? remaining / speed : null);
          setProgress(Math.round((n / totalParts) * 95));

          persist({
            uploadId: init.upload_id,
            sessionId: init.session_id,
            partSize,
            totalParts,
            fileName: file.name,
            fileSize: file.size,
            kind,
            mimeType,
            parts,
          });
        }

        const completedKindParam = `kind=${kind}&filename=${encodeURIComponent(
          file.name,
        )}&mime_type=${encodeURIComponent(mimeType)}`;
        const interview = await api.post<Interview>(
          `/recruitment/interviews/${interviewId}/upload/complete?${completedKindParam}`,
          {
            upload_id: init.upload_id,
            parts,
            auto_process: autoProcess && kind !== "text_transcript",
          },
        );
        setProgress(100);
        clearPersisted();
        toast.success(t("interviewUploadToastSuccess"));
        onUploaded?.(interview);
      } catch (err) {
        if (!stateRef.current.cancelled) {
          try {
            await api.post(
              `/recruitment/interviews/${interviewId}/upload/abort`,
              { upload_id: init.upload_id },
            );
          } catch {
            /* noop */
          }
        }
        clearPersisted();
        // UploadError carries a stable code — surface the localized text
        // instead of the technical English message it keeps for logs.
        toast.error(
          err instanceof UploadError
            ? err.code === "s3PutFailed"
              ? t("uploadS3PutFailed", { status: err.status ?? 0 })
              : err.code === "s3Unreachable"
                ? t("uploadS3Unreachable")
                : t("uploadS3NoEtag")
            : err instanceof Error
              ? err.message
              : t("interviewUploadFailed"),
        );
      } finally {
        reset();
      }
    },
    [interviewId, persist, clearPersisted, onUploaded, reset, autoProcess, t],
  );

  const startUpload = useCallback(
    async (file: File, kind: UploadKind) => {
      setUploading(true);
      setActiveFile(file);
      setProgress(0);
      setBytesUploaded(0);

      // effectiveMime maps extension-detected files (browsers leave
      // File.type empty for AVI/m4a) to a real MIME so upload/init
      // passes backend validation.
      const mimeType = effectiveMime(file);
      let init: InitUploadResponse | null = null;
      try {
        init = await api.post<InitUploadResponse>(
          `/recruitment/interviews/${interviewId}/upload/init`,
          {
            filename: file.name,
            mime_type: mimeType,
            size_bytes: file.size,
            // HRP-385: the real kind — see interview-upload.ts.
            kind,
          },
        );
      } catch (err) {
        if (err instanceof ApiError && err.status === 409) {
          onConsentMissing?.();
          toast.error(t("interviewUploadConsentNotSigned"));
        } else if (err instanceof ApiError && err.status === 402) {
          // HRP-547: the balance is checked and held before the transfer
          // starts, so this fires with the file still on disk. Say that
          // outright — "failed to start upload" reads like a glitch worth
          // retrying, and a retry cannot help here.
          toast.error(t("interviewUploadInsufficientCredits"));
        } else if (err instanceof ApiError && err.status === 429) {
          // A demo workspace out of quota has no admin to top it up, so it
          // gets the sandbox wording the rest of the demo surfaces use
          // rather than "ask your administrator" (HRP-252).
          toast.error(err.message || t("interviewUploadInsufficientCredits"));
        } else {
          toast.error(
            err instanceof Error
              ? err.message
              : t("interviewUploadStartFailed"),
          );
        }
        reset();
        return;
      }

      await runUpload(file, init, kind, mimeType, []);
    },
    [interviewId, onConsentMissing, reset, runUpload, t],
  );

  const onFile = useCallback(
    async (file: File) => {
      if (!consentSigned) {
        onConsentMissing?.();
        toast.error(t("interviewUploadConsentFirst"));
        return;
      }
      const kind = detectKind(file);
      if (kind === null) {
        toast.error(t("interviewUploadUnsupportedType"));
        return;
      }
      const limit =
        kind === "text_transcript" ? TRANSCRIPT_MAX_BYTES : MEDIA_MAX_BYTES;
      if (file.size > limit) {
        toast.error(
          t("interviewUploadTooLarge", {
            limit: String(Math.floor(limit / (1024 * 1024))),
          }),
        );
        return;
      }

      // HRP-405: an interview that already declares a recording type must
      // not silently flip to another one.
      if (requiresTypeSwitchConfirm(interviewType, kind)) {
        setPendingKindSwitch({ file, kind });
        return;
      }

      await startUpload(file, kind);
    },
    [consentSigned, interviewType, onConsentMissing, startUpload, t],
  );

  function onCancel() {
    stateRef.current.cancelled = true;
    if (stateRef.current.uploadId) {
      void fetch(
        `${API_BASE}/recruitment/interviews/${interviewId}/upload/abort`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${typeof window !== "undefined" ? localStorage.getItem("access_token") || "" : ""}`,
          },
          body: JSON.stringify({ upload_id: stateRef.current.uploadId }),
          keepalive: true,
        },
      );
    }
    clearPersisted();
    toast.message(t("interviewUploadCancelling"));
  }

  function onTogglePause() {
    const next = !stateRef.current.paused;
    stateRef.current.paused = next;
    setPaused(next);
  }

  async function resumePending() {
    if (!resumable) return;
    const handle = inputRef.current;
    if (!handle) return;
    handle.click();
    toast.message(t("interviewUploadResumeHint"));
  }

  function onDragOver(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragOver(true);
  }

  function onDragLeave() {
    setDragOver(false);
  }

  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer?.files?.[0];
    if (file) void onFile(file);
  }

  const sizeText = activeFile
    ? `${(bytesUploaded / (1024 * 1024)).toFixed(1)} / ${(
        activeFile.size /
        (1024 * 1024)
      ).toFixed(1)} MB`
    : null;

  return (
    <div className="space-y-2">
      <input
        ref={inputRef}
        type="file"
        accept={UPLOAD_ACCEPT_ATTR}
        className="sr-only"
        data-testid="recruitment-interview-input-file"
        onChange={(e) => {
          const f = e.target.files?.[0];
          // HRP-405: clear the input so picking the same file again still
          // fires onChange — declining the type-switch dialog (or any
          // failed attempt) otherwise leaves the picker inert.
          e.target.value = "";
          if (f) void onFile(f);
        }}
      />
      {!uploading ? (
        <div
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          onDrop={onDrop}
          data-testid="recruitment-interview-dropzone"
          className={[
            "flex flex-col items-center justify-center gap-2 rounded-md border border-dashed p-6 text-sm text-muted-foreground transition-colors",
            dragOver ? "border-accent bg-accent/5" : "",
          ].join(" ")}
        >
          <Upload className="size-6 opacity-60" aria-hidden />
          <p className="text-center text-xs">
            {t("interviewUploadDropHint")}
            <br />
            {t("interviewUploadFormatsHint")}
          </p>
          <label className="flex items-center gap-2 text-xs">
            <Checkbox
              checked={autoProcess}
              onCheckedChange={(checked) => setAutoProcess(Boolean(checked))}
              data-testid="recruitment-interview-auto-process"
            />
            {t("interviewUploadAutoProcess")}
          </label>
          <Button
            variant="outline"
            size="sm"
            onClick={() => inputRef.current?.click()}
            disabled={!consentSigned}
            data-testid="recruitment-interview-btn-upload"
          >
            <Upload className="size-4" />
            {consentSigned
              ? t("interviewUploadButton")
              : t("interviewUploadConsentRequired")}
          </Button>
          {resumable && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => void resumePending()}
              data-testid="recruitment-interview-btn-resume-after-reload"
            >
              <Play className="size-3.5" />
              {t("interviewUploadResumeFile", { name: resumable.fileName })}
            </Button>
          )}
        </div>
      ) : (
        <div className="space-y-1.5 rounded-md border p-3">
          <div className="flex items-center justify-between text-xs">
            <span className="flex items-center gap-2 text-muted-foreground">
              <Loader2 className="size-3 animate-spin" />
              {activeFile?.name} — {progress}%
              {sizeText && <span>· {sizeText}</span>}
              {speedMbps != null && (
                <span>· {speedMbps.toFixed(2)} MB/s</span>
              )}
              {etaSec != null && Number.isFinite(etaSec) && (
                <span>
                  ·{" "}
                  {t("interviewUploadEta", {
                    seconds: String(Math.max(1, Math.round(etaSec))),
                  })}
                </span>
              )}
            </span>
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={onTogglePause}
                data-testid="recruitment-interview-btn-pause"
                aria-label={
                  paused ? t("interviewUploadResume") : t("interviewUploadPause")
                }
              >
                {paused ? (
                  <Play className="size-3.5" />
                ) : (
                  <Pause className="size-3.5" />
                )}
              </Button>
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={onCancel}
                data-testid="recruitment-interview-btn-cancel"
                aria-label={t("interviewUploadCancelAria")}
              >
                <X className="size-3.5" />
              </Button>
            </div>
          </div>
          <div
            className="h-1 w-full overflow-hidden rounded bg-muted"
            role="progressbar"
            aria-live="polite"
            aria-valuenow={progress}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            <div
              className="h-full bg-accent transition-[width] duration-200"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>
      )}

      <ConfirmDialog
        open={pendingKindSwitch !== null}
        onOpenChange={(o) => !o && setPendingKindSwitch(null)}
        title={pendingKindSwitch ? kindSwitchTitle[pendingKindSwitch.kind] : ""}
        description={
          pendingKindSwitch
            ? t("interviewUploadTypeSwitchDescription", {
                current: interviewTypeLabel[interviewType ?? "undecided"],
                next: interviewTypeLabel[pendingKindSwitch.kind],
              })
            : undefined
        }
        confirmLabel={t("interviewUploadTypeSwitchConfirm")}
        cancelLabel={tc("cancel")}
        onConfirm={() => {
          // ConfirmDialog closes itself afterwards, which clears the
          // pending file via onOpenChange — clearing it here instead
          // would blank the dialog's own copy mid exit-animation.
          if (pendingKindSwitch) {
            void startUpload(pendingKindSwitch.file, pendingKindSwitch.kind);
          }
        }}
        testId="recruitment-interview-type-switch-confirm"
      />
    </div>
  );
}
