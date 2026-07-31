"use client";

import { useCallback, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { Upload, FileText, CheckCircle, AlertCircle, X } from "lucide-react";
import { Button } from "@/components/ui/button";

interface UploadZoneProps {
  onUpload: (files: File[]) => void;
  accept?: string;
  maxSize?: number; // MB
  multiple?: boolean;
}

type FileStatus = "queued" | "uploading" | "done" | "error";

interface QueuedFile {
  file: File;
  id: string;
  status: FileStatus;
  error?: string;
}

const DEFAULT_ACCEPT =
  ".pdf,.docx,.doc,.txt,.rtf,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,text/rtf";
const DEFAULT_MAX_SIZE = 20; // MB

export function UploadZone({
  onUpload,
  accept = DEFAULT_ACCEPT,
  maxSize = DEFAULT_MAX_SIZE,
  multiple = true,
}: UploadZoneProps) {
  const t = useTranslations("recruitment");
  const [files, setFiles] = useState<QueuedFile[]>([]);
  const [isDragOver, setIsDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const addFiles = useCallback(
    (incoming: FileList | File[]) => {
      const list = Array.from(incoming);
      const maxBytes = maxSize * 1024 * 1024;

      const queued: QueuedFile[] = list.map((file) => {
        const oversized = file.size > maxBytes;
        return {
          file,
          id: `${file.name}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          status: oversized ? "error" : "queued",
          error: oversized
            ? t("uploadZoneFileTooLarge", { maxSize })
            : undefined,
        };
      });

      const next = multiple ? [...files, ...queued] : queued;
      setFiles(next);

      const valid = queued
        .filter((q) => q.status === "queued")
        .map((q) => q.file);

      if (valid.length > 0) {
        // Mark as uploading
        setFiles((prev) =>
          prev.map((f) =>
            valid.includes(f.file) ? { ...f, status: "uploading" as const } : f,
          ),
        );
        onUpload(valid);
        // Mark as done after callback
        setTimeout(() => {
          setFiles((prev) =>
            prev.map((f) =>
              valid.includes(f.file) ? { ...f, status: "done" as const } : f,
            ),
          );
        }, 0);
      }
    },
    [files, maxSize, multiple, onUpload, t],
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragOver(false);
      if (e.dataTransfer.files.length > 0) {
        addFiles(e.dataTransfer.files);
      }
    },
    [addFiles],
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
  }, []);

  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      if (e.target.files && e.target.files.length > 0) {
        addFiles(e.target.files);
      }
      // Reset input so re-selecting the same file works
      e.target.value = "";
    },
    [addFiles],
  );

  const removeFile = useCallback((id: string) => {
    setFiles((prev) => prev.filter((f) => f.id !== id));
  }, []);

  const doneCount = files.filter((f) => f.status === "done").length;
  const totalCount = files.length;
  const progressPercent =
    totalCount > 0 ? Math.round((doneCount / totalCount) * 100) : 0;

  return (
    <div data-testid="recruitment-upload-zone" className="space-y-3">
      {/* Drop zone */}
      <div
        className={cn(
          "flex h-[300px] w-full max-w-[400px] cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed transition-colors",
          isDragOver
            ? "border-accent bg-accent/5"
            : "border-muted-foreground/25 hover:border-muted-foreground/50",
        )}
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onClick={() => inputRef.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
      >
        <Upload className="size-10 text-muted-foreground" />
        <div className="text-center">
          <p className="text-sm font-medium text-foreground">
            {t("uploadZoneDropHint")}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            {t("uploadZoneAcceptHint", { maxSize })}
          </p>
        </div>
      </div>

      <input
        ref={inputRef}
        type="file"
        accept={accept}
        multiple={multiple}
        onChange={handleInputChange}
        className="hidden"
      />

      {/* File queue */}
      {files.length > 0 && (
        <div className="space-y-2">
          {/* Batch progress */}
          {totalCount > 1 && (
            <div className="space-y-1">
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>
                  {t("uploadZoneProgress", {
                    done: doneCount,
                    total: totalCount,
                  })}
                </span>
                <span>{progressPercent}%</span>
              </div>
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full rounded-full bg-accent transition-all"
                  style={{ width: `${progressPercent}%` }}
                />
              </div>
            </div>
          )}

          {/* File list */}
          <ul className="space-y-1">
            {files.map((qf) => (
              <li
                key={qf.id}
                className="flex items-center gap-2 rounded-lg border px-3 py-2 text-sm"
              >
                <FileText className="size-4 shrink-0 text-muted-foreground" />
                <span className="min-w-0 flex-1 truncate">{qf.file.name}</span>
                <span className="shrink-0">
                  {qf.status === "queued" && (
                    <span className="text-xs text-muted-foreground">
                      {t("uploadZoneStatusQueued")}
                    </span>
                  )}
                  {qf.status === "uploading" && (
                    <span className="text-xs text-accent">
                      {t("uploadZoneStatusUploading")}
                    </span>
                  )}
                  {qf.status === "done" && (
                    <CheckCircle className="size-4 text-[var(--rec-data-full)]" />
                  )}
                  {qf.status === "error" && (
                    <span
                      className="flex items-center gap-1 text-xs text-destructive"
                      title={qf.error}
                    >
                      <AlertCircle className="size-4" />
                      {t("uploadZoneStatusError")}
                    </span>
                  )}
                </span>
                <Button
                  variant="ghost"
                  size="icon-xs"
                  onClick={(e) => {
                    e.stopPropagation();
                    removeFile(qf.id);
                  }}
                >
                  <X className="size-3" />
                </Button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
