"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type DragEvent,
} from "react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Loader2, Pause, Play, Upload, X } from "lucide-react";
import { api, ApiError, API_BASE } from "@/lib/api";
import type {
  InitUploadResponse,
  Interview,
  PartUrlResponse,
} from "@/lib/types";
import { toast } from "sonner";

interface InterviewUploadZoneProps {
  interviewId: string;
  consentSigned: boolean;
  onUploaded?: (interview: Interview) => void;
  onConsentMissing?: () => void;
}

import {
  MEDIA_MAX_BYTES,
  TRANSCRIPT_MAX_BYTES,
  UPLOAD_ACCEPT_ATTR,
  detectKind,
  effectiveMime,
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

async function putChunk(
  url: string,
  chunk: Blob,
  attempt = 0,
): Promise<string> {
  try {
    const res = await fetch(url, { method: "PUT", body: chunk });
    if (!res.ok) {
      throw new Error(`S3 PUT failed (HTTP ${res.status})`);
    }
    const etag = res.headers.get("ETag") || res.headers.get("etag");
    if (!etag) {
      throw new Error("S3 did not return an ETag");
    }
    return etag.replace(/"/g, "");
  } catch (err) {
    if (attempt < 2) {
      await new Promise((r) => setTimeout(r, 500 * Math.pow(3, attempt)));
      return putChunk(url, chunk, attempt + 1);
    }
    throw err;
  }
}

export function InterviewUploadZone({
  interviewId,
  consentSigned,
  onUploaded,
  onConsentMissing,
}: InterviewUploadZoneProps) {
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
            throw new Error("Upload cancelled");
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
        toast.success("Recording uploaded");
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
        toast.error(err instanceof Error ? err.message : "Upload failed");
      } finally {
        reset();
      }
    },
    [interviewId, persist, clearPersisted, onUploaded, reset, autoProcess],
  );

  const onFile = useCallback(
    async (file: File) => {
      if (!consentSigned) {
        onConsentMissing?.();
        toast.error("Get the candidate's recording consent first");
        return;
      }
      const kind = detectKind(file);
      if (kind === null) {
        toast.error("Unsupported file type");
        return;
      }
      const limit =
        kind === "text_transcript" ? TRANSCRIPT_MAX_BYTES : MEDIA_MAX_BYTES;
      if (file.size > limit) {
        toast.error(
          `File is larger than ${Math.floor(limit / (1024 * 1024))} MB`,
        );
        return;
      }

      setUploading(true);
      setActiveFile(file);
      setProgress(0);
      setBytesUploaded(0);

      // effectiveMime maps extension-detected files (browsers leave
      // File.type empty for AVI/m4a) to a real MIME so upload/init
      // passes backend validation.
      const mimeType = effectiveMime(file);
      const initKind = kind === "text_transcript" ? "audio" : kind;
      let init: InitUploadResponse | null = null;
      try {
        init = await api.post<InitUploadResponse>(
          `/recruitment/interviews/${interviewId}/upload/init`,
          {
            filename: file.name,
            mime_type: mimeType,
            size_bytes: file.size,
            kind: initKind,
          },
        );
      } catch (err) {
        if (err instanceof ApiError && err.status === 409) {
          onConsentMissing?.();
          toast.error(
            "Candidate consent is not signed (ConsentRequired). Send consent and retry.",
          );
        } else {
          toast.error(
            err instanceof Error ? err.message : "Failed to start upload",
          );
        }
        reset();
        return;
      }

      await runUpload(file, init, kind, mimeType, []);
    },
    [consentSigned, interviewId, onConsentMissing, reset, runUpload],
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
    toast.message("Cancelling upload…");
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
    toast.message("Select the same file to resume the upload");
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
            Drop the file here or click the button below.
            <br />
            Audio (mp3, wav, m4a) / Video (mp4, webm, mov, avi) up to 500 MB,
            PDF / TXT up to 10 MB.
          </p>
          <label className="flex items-center gap-2 text-xs">
            <Checkbox
              checked={autoProcess}
              onCheckedChange={(checked) => setAutoProcess(Boolean(checked))}
              data-testid="recruitment-interview-auto-process"
            />
            Transcribe and analyze automatically after upload
          </label>
          <Button
            variant="outline"
            size="sm"
            onClick={() => inputRef.current?.click()}
            disabled={!consentSigned}
            data-testid="recruitment-interview-btn-upload"
          >
            <Upload className="size-4" />
            {consentSigned ? "Upload recording" : "Consent required"}
          </Button>
          {resumable && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => void resumePending()}
              data-testid="recruitment-interview-btn-resume-after-reload"
            >
              <Play className="size-3.5" />
              Resume &ldquo;{resumable.fileName}&rdquo;
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
                <span>· ETA {Math.max(1, Math.round(etaSec))} s</span>
              )}
            </span>
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={onTogglePause}
                data-testid="recruitment-interview-btn-pause"
                aria-label={paused ? "Resume" : "Pause"}
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
                aria-label="Cancel upload"
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
    </div>
  );
}
