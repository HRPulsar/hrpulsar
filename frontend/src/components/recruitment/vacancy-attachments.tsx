"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Paperclip, Trash2, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { toast } from "sonner";

type Attachment = {
  id: string;
  filename: string;
  mime_type: string | null;
  size_bytes: number | null;
  uploaded_at: string;
};

const MAX_FILES = 10;
const MAX_BYTES = 25 * 1024 * 1024;

// Mirrors the backend allowlist (HRP-135). Anything outside surfaces as
// 415 from the API — the UI also blocks the picker upfront.
const MIME_ALLOW = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "text/plain",
  "text/markdown",
  "text/csv",
  "application/json",
  "image/png",
  "image/jpeg",
  "image/gif",
  "image/webp",
  "application/zip",
  "application/epub+zip",
];

function formatSize(bytes: number | null): string {
  if (bytes === null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

interface Props {
  vacancyId: string;
  canEdit: boolean;
}

export function VacancyAttachments({ vacancyId, canEdit }: Props) {
  const t = useTranslations("recruitment");
  const [items, setItems] = useState<Attachment[]>([]);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await api.get<Attachment[]>(
        `/recruitment/vacancies/${vacancyId}/attachments`,
      );
      setItems(Array.isArray(data) ? data : []);
    } catch {
      // 404 on a brand-new vacancy is fine — just render an empty list.
    }
  }, [vacancyId]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await api.get<Attachment[]>(
          `/recruitment/vacancies/${vacancyId}/attachments`,
        );
        if (!cancelled) setItems(Array.isArray(data) ? data : []);
      } catch {
        // 404 on a brand-new vacancy — empty list is fine.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [vacancyId]);

  async function handleFiles(filesList: FileList | null) {
    if (!filesList || filesList.length === 0) return;
    const files = Array.from(filesList);
    const room = MAX_FILES - items.length;
    if (room <= 0) {
      toast.error(t("attachmentsTooMany", { max: MAX_FILES }));
      return;
    }
    const accepted = files.slice(0, room);
    const skipped = files.length - accepted.length;
    if (skipped > 0) {
      toast.warning(
        t("attachmentsPartialUpload", {
          accepted: accepted.length,
          total: files.length,
          max: MAX_FILES,
        }),
      );
    }
    setBusy(true);
    for (const f of accepted) {
      if (f.size > MAX_BYTES) {
        toast.error(t("attachmentsFileTooLarge", { name: f.name }));
        continue;
      }
      if (f.type && !MIME_ALLOW.includes(f.type)) {
        toast.error(
          t("attachmentsUnsupportedType", { name: f.name, type: f.type }),
        );
        continue;
      }
      try {
        await api.upload(
          `/recruitment/vacancies/${vacancyId}/attachments`,
          f,
        );
      } catch (err) {
        toast.error(
          err instanceof Error
            ? `${f.name}: ${err.message}`
            : t("attachmentsUploadFailed", { name: f.name }),
        );
      }
    }
    setBusy(false);
    await load();
    if (inputRef.current) inputRef.current.value = "";
  }

  async function handleDelete(id: string, name: string) {
    if (!confirm(t("attachmentsDeleteConfirm", { name }))) return;
    try {
      await api.delete(
        `/recruitment/vacancies/${vacancyId}/attachments/${id}`,
      );
      toast.success(t("attachmentsToastRemoved"));
      setItems((prev) => prev.filter((a) => a.id !== id));
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("attachmentsDeleteFailed"),
      );
    }
  }

  return (
    <div
      className="space-y-3 rounded-md border bg-card p-4"
      data-testid="vacancy-attachments"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Paperclip className="h-4 w-4 text-muted-foreground" />
          <h3 className="text-sm font-medium">{t("attachmentsTitle")}</h3>
          <span className="text-xs text-muted-foreground">
            {t("attachmentsCounter", {
              count: items.length,
              max: MAX_FILES,
              size: formatSize(MAX_BYTES),
            })}
          </span>
        </div>
        {canEdit && (
          <>
            <input
              ref={inputRef}
              type="file"
              multiple
              hidden
              data-testid="vacancy-attachments-input"
              accept={MIME_ALLOW.join(",")}
              onChange={(e) => handleFiles(e.target.files)}
            />
            <Button
              variant="outline"
              size="sm"
              disabled={busy || items.length >= MAX_FILES}
              onClick={() => inputRef.current?.click()}
              data-testid="vacancy-attachments-upload-btn"
            >
              <Upload className="mr-1 h-3 w-3" />
              {t("attachmentsUploadButton")}
            </Button>
          </>
        )}
      </div>
      {items.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          {t("attachmentsEmpty")}
        </p>
      ) : (
        <ul className="divide-y text-sm">
          {items.map((a) => (
            <li
              key={a.id}
              className="flex items-center justify-between py-1.5"
              data-testid={`vacancy-attachment-row-${a.id}`}
            >
              <div className="flex min-w-0 flex-col">
                <span className="truncate font-medium">{a.filename}</span>
                <span className="text-xs text-muted-foreground">
                  {a.mime_type ?? t("attachmentsMimeUnknown")} •{" "}
                  {formatSize(a.size_bytes)}
                </span>
              </div>
              {canEdit && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => handleDelete(a.id, a.filename)}
                  data-testid={`vacancy-attachment-delete-${a.id}`}
                >
                  <Trash2 className="h-3 w-3" />
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
