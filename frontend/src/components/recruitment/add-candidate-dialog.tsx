"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Loader2,
  Upload,
  UserPlus,
} from "lucide-react";
import { toast } from "sonner";
import { useTranslations } from "next-intl";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { ALERT_TONE } from "@/lib/badge-tones";
import { ApiError, api } from "@/lib/api";
import {
  BULK_UPLOAD_ACCEPT,
  BULK_UPLOAD_MAX_FILES,
  BULK_UPLOAD_MAX_FILE_BYTES,
  type BatchFinalizeFile,
  type BatchFinalizeResponse,
  type BulkResumeAck,
  type ManualCandidateResponse,
  type ResumeDedupPreviewItem,
  type ResumeParseStatusItem,
  type ResumeParseStatusResponse,
} from "@/lib/recruitment-types";
import {
  buildManualPayload,
  manualPayloadValidationError,
  validateBulkUploadSelection,
} from "@/lib/recruitment-helpers";

interface AddCandidateDialogProps {
  vacancyId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCandidatesChanged: () => void;
  onManualCreated?: (candidateId: string) => void;
}

type UploadStep = "select" | "parsing" | "summary";

interface UploadedFile extends BulkResumeAck {
  // mirror server fields plus the latest poll snapshot
  parse_status: string;
  full_name: string | null;
  email: string | null;
  last_position: string | null;
  error: string | null;
}

interface ImportRow {
  file_id: string;
  filename: string;
  full_name: string | null;
  email: string | null;
  existing_candidate_id: string | null;
  existing_candidate_full_name: string | null;
  // "create" → new candidate, "link" → attach existing one to vacancy
  action: "create" | "link";
}

const POLL_INTERVAL_MS = 2500;

function bytesToMb(bytes: number): string {
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function maxFileBytesMb(): string {
  return `${Math.round(BULK_UPLOAD_MAX_FILE_BYTES / (1024 * 1024))} MB`;
}

export function AddCandidateDialog({
  vacancyId,
  open,
  onOpenChange,
  onCandidatesChanged,
  onManualCreated,
}: AddCandidateDialogProps) {
  const t = useTranslations("recruitment");
  const [tab, setTab] = useState<"upload" | "manual">("upload");

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-w-[720px] p-0 sm:max-w-[720px]"
        data-testid="vacancy-candidates-add-modal"
      >
        <DialogHeader className="space-y-1 border-b px-6 py-4">
          <DialogTitle>{t("candidateAddButton")}</DialogTitle>
          <DialogDescription>{t("addCandidateDescription")}</DialogDescription>
        </DialogHeader>

        <Tabs
          defaultValue="upload"
          value={tab}
          onValueChange={(v) => setTab(v as "upload" | "manual")}
          className="px-6 py-4"
        >
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger
              value="upload"
              data-testid="vacancy-candidates-add-modal-tab-upload"
            >
              <Upload className="mr-2 size-4" />
              {t("addCandidateTabUpload")}
            </TabsTrigger>
            <TabsTrigger
              value="manual"
              data-testid="vacancy-candidates-add-modal-tab-manual"
            >
              <UserPlus className="mr-2 size-4" />
              {t("addCandidateTabManual")}
            </TabsTrigger>
          </TabsList>

          <TabsContent value="upload" className="mt-4">
            <UploadTab
              key={open ? "open" : "closed"}
              vacancyId={vacancyId}
              onDone={() => {
                onCandidatesChanged();
                onOpenChange(false);
              }}
              onCancel={() => onOpenChange(false)}
            />
          </TabsContent>

          <TabsContent value="manual" className="mt-4">
            <ManualTab
              vacancyId={vacancyId}
              onCreated={(candidateId) => {
                onCandidatesChanged();
                onOpenChange(false);
                onManualCreated?.(candidateId);
              }}
              onCancel={() => onOpenChange(false)}
            />
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Upload tab — 3 states: select → parsing → summary
// ---------------------------------------------------------------------------

interface UploadTabProps {
  vacancyId: string;
  onDone: () => void;
  onCancel: () => void;
}

function UploadTab({ vacancyId, onDone, onCancel }: UploadTabProps) {
  const t = useTranslations("recruitment");
  const [step, setStep] = useState<UploadStep>("select");
  const [picked, setPicked] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [files, setFiles] = useState<UploadedFile[]>([]);
  const [importRows, setImportRows] = useState<ImportRow[]>([]);
  const [importing, setImporting] = useState(false);

  const fileIds = useMemo(() => files.map((f) => f.file_id), [files]);

  // ── poll parsing-status while we're on the parsing step ───────────────
  useEffect(() => {
    if (step !== "parsing" || fileIds.length === 0) return;
    let cancelled = false;

    async function tick() {
      try {
        // FastAPI expects repeated query params for `list[uuid.UUID]`;
        // CSV would be parsed as a single string and 422.
        const params = new URLSearchParams();
        for (const id of fileIds) params.append("file_ids", id);
        const data = await api.get<ResumeParseStatusResponse>(
          `/recruitment/vacancies/${vacancyId}/resumes/parsing-status?${params.toString()}`,
        );
        if (cancelled) return;
        applyParseSnapshot(data.files);
        if (
          (data.counts.pending ?? 0) === 0 &&
          (data.counts.processing ?? 0) === 0
        ) {
          await finalizeImportSummary();
        }
      } catch (err) {
        if (cancelled) return;
        toast.error(
          err instanceof Error
            ? err.message
            : t("addCandidateParseStatusFailed"),
        );
      }
    }

    const handle = window.setInterval(tick, POLL_INTERVAL_MS);
    // Kick off an immediate fetch so the user isn't staring at the initial
    // ack snapshot for 2.5 s before the first transition.
    tick();
    return () => {
      cancelled = true;
      window.clearInterval(handle);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, fileIds.join(",")]);

  const applyParseSnapshot = useCallback(
    (snapshot: ResumeParseStatusItem[]) => {
      setFiles((prev) => {
        const byId = new Map(snapshot.map((s) => [s.file_id, s]));
        return prev.map((f) => {
          const fresh = byId.get(f.file_id);
          if (!fresh) return f;
          return {
            ...f,
            parse_status: fresh.parse_status,
            full_name: fresh.full_name,
            email: fresh.email,
            last_position: fresh.last_position,
            error: fresh.error,
          };
        });
      });
    },
    [],
  );

  const finalizeImportSummary = useCallback(async () => {
    if (fileIds.length === 0) {
      setStep("summary");
      return;
    }
    try {
      const params = new URLSearchParams();
      for (const id of fileIds) params.append("file_ids", id);
      const dedup = await api.get<ResumeDedupPreviewItem[]>(
        `/recruitment/vacancies/${vacancyId}/resumes/dedup-preview?${params.toString()}`,
      );
      const byId = new Map(dedup.map((d) => [d.file_id, d]));
      setFiles((current) => {
        const rows: ImportRow[] = current
          .filter((f) => f.parse_status !== "failed")
          .map((f) => {
            const dup = byId.get(f.file_id);
            return {
              file_id: f.file_id,
              filename: f.original_filename,
              full_name: f.full_name,
              email: f.email,
              existing_candidate_id: dup?.existing_candidate_id ?? null,
              existing_candidate_full_name:
                dup?.existing_candidate_full_name ?? null,
              action: dup?.existing_candidate_id ? "link" : "create",
            };
          });
        setImportRows(rows);
        return current;
      });
      setStep("summary");
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("addCandidateDedupFailed"),
      );
      setStep("summary");
    }
  }, [fileIds, vacancyId, t]);

  const handlePick = useCallback(
    (list: FileList | File[]) => {
      const arr = Array.from(list);
      setUploadError(null);
      const err = validateBulkUploadSelection(t, arr);
      if (err) {
        setUploadError(err);
        return;
      }
      setPicked(arr);
    },
    [t],
  );

  const startParsing = useCallback(async () => {
    if (picked.length === 0) {
      setUploadError(t("addCandidatePickAtLeastOne"));
      return;
    }
    const form = new FormData();
    for (const f of picked) form.append("files", f, f.name);
    setUploading(true);
    setUploadError(null);
    try {
      const ack = await api.postForm<BulkResumeAck[]>(
        `/recruitment/vacancies/${vacancyId}/resumes/bulk-upload`,
        form,
      );
      setFiles(
        ack.map((a) => ({
          ...a,
          full_name: null,
          email: null,
          last_position: null,
          error: null,
        })),
      );
      setStep("parsing");
    } catch (err) {
      const msg =
        err instanceof Error ? err.message : t("addCandidateUploadFailed");
      setUploadError(msg);
    } finally {
      setUploading(false);
    }
  }, [picked, vacancyId, t]);

  const updateRowAction = useCallback(
    (fileId: string, action: ImportRow["action"]) => {
      setImportRows((prev) =>
        prev.map((r) => (r.file_id === fileId ? { ...r, action } : r)),
      );
    },
    [],
  );

  const startImport = useCallback(async () => {
    if (importRows.length === 0) {
      onDone();
      return;
    }
    setImporting(true);
    const payload: BatchFinalizeFile[] = importRows.map((r) => ({
      file_id: r.file_id,
      link_candidate_id:
        r.action === "link" && r.existing_candidate_id
          ? r.existing_candidate_id
          : null,
    }));
    try {
      const result = await api.post<BatchFinalizeResponse>(
        `/recruitment/vacancies/${vacancyId}/candidates/from-parsed`,
        { files: payload },
      );
      const created = result.created.length;
      const linked = result.linked.length;
      const skipped = result.skipped.length;
      toast.success(
        t("addCandidateImportToast", { count: created, linked, skipped }),
      );
      onDone();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("addCandidateImportFailed"),
      );
    } finally {
      setImporting(false);
    }
  }, [importRows, vacancyId, onDone, t]);

  if (step === "select") {
    return (
      <SelectStep
        picked={picked}
        onPick={handlePick}
        onClear={() => {
          setPicked([]);
          setUploadError(null);
        }}
        onStart={startParsing}
        onCancel={onCancel}
        uploading={uploading}
        error={uploadError}
      />
    );
  }

  if (step === "parsing") {
    const total = files.length;
    const processed = files.filter(
      (f) => f.parse_status === "completed" || f.parse_status === "failed",
    ).length;
    return <ParsingStep files={files} total={total} processed={processed} />;
  }

  return (
    <SummaryStep
      rows={importRows}
      busy={importing}
      onCancel={onCancel}
      onImport={startImport}
      onChangeAction={updateRowAction}
    />
  );
}

interface SelectStepProps {
  picked: File[];
  onPick: (list: FileList | File[]) => void;
  onClear: () => void;
  onStart: () => void;
  onCancel: () => void;
  uploading: boolean;
  error: string | null;
}

function SelectStep({
  picked,
  onPick,
  onClear,
  onStart,
  onCancel,
  uploading,
  error,
}: SelectStepProps) {
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);

  return (
    <div className="space-y-4">
      <div
        className={cn(
          "flex h-44 cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed text-center transition-colors",
          dragOver
            ? "border-primary/60 bg-primary/5"
            : "border-muted-foreground/30 hover:border-muted-foreground/50",
        )}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          if (e.dataTransfer.files.length > 0) onPick(e.dataTransfer.files);
        }}
        role="button"
        tabIndex={0}
        data-testid="vacancy-candidates-add-dropzone"
      >
        <Upload className="size-7 text-muted-foreground" />
        <p className="text-sm font-medium">{t("addCandidateDropzone")}</p>
        <p className="text-xs text-muted-foreground">
          {t("addCandidateDropzoneHint", {
            maxFiles: BULK_UPLOAD_MAX_FILES,
            maxSize: maxFileBytesMb(),
          })}
        </p>
      </div>
      <input
        ref={inputRef}
        type="file"
        multiple
        accept={BULK_UPLOAD_ACCEPT}
        className="hidden"
        onChange={(e) => {
          if (e.target.files) onPick(e.target.files);
          e.target.value = "";
        }}
      />
      {picked.length > 0 && (
        <ul className="space-y-1">
          {picked.map((f) => (
            <li
              key={`${f.name}-${f.size}`}
              className="flex items-center justify-between rounded-md border px-3 py-2 text-sm"
            >
              <span className="truncate">{f.name}</span>
              <span className="text-xs text-muted-foreground">
                {bytesToMb(f.size)}
              </span>
            </li>
          ))}
        </ul>
      )}
      {error && (
        <p className="rounded-md border border-destructive/50 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      )}
      <DialogFooter>
        <Button variant="ghost" onClick={onCancel} disabled={uploading}>
          {tc("cancel")}
        </Button>
        {picked.length > 0 && (
          <Button variant="ghost" onClick={onClear} disabled={uploading}>
            {t("actionClear")}
          </Button>
        )}
        <Button
          onClick={onStart}
          disabled={uploading || picked.length === 0}
          data-testid="vacancy-candidates-add-submit-btn"
        >
          {uploading
            ? t("addCandidateUploading")
            : t("addCandidateStartParsing", { count: picked.length })}
        </Button>
      </DialogFooter>
    </div>
  );
}

interface ParsingStepProps {
  files: UploadedFile[];
  total: number;
  processed: number;
}

function ParsingStep({ files, total, processed }: ParsingStepProps) {
  const t = useTranslations("recruitment");
  const percent = total > 0 ? Math.round((processed / total) * 100) : 0;
  return (
    <div className="space-y-3">
      <div className="space-y-1">
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>
            {t("addCandidateParsedProgress", { processed, total })}
          </span>
          <span>{percent}%</span>
        </div>
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
          <div
            className="h-full rounded-full bg-primary transition-all"
            style={{ width: `${percent}%` }}
          />
        </div>
      </div>
      <ul className="max-h-[320px] space-y-2 overflow-y-auto">
        {files.map((f) => (
          <li
            key={f.file_id}
            className="rounded-md border px-3 py-2 text-sm"
            data-testid={`vacancy-candidates-add-file-${f.file_id}`}
          >
            <div className="flex items-center justify-between gap-3">
              <span className="truncate font-medium">
                {f.full_name || f.original_filename}
              </span>
              <FileBadge
                status={f.parse_status}
                testId={`vacancy-candidates-add-file-${f.file_id}-status`}
              />
            </div>
            {f.parse_status === "completed" && (
              <p className="mt-1 truncate text-xs text-muted-foreground">
                {[f.last_position, f.email].filter(Boolean).join(" · ") || "—"}
              </p>
            )}
            {f.parse_status === "failed" && (
              <p
                className="mt-1 text-xs text-destructive"
                title={f.error ?? undefined}
              >
                {f.error || t("addCandidateParseFailed")}
              </p>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function FileBadge({ status, testId }: { status: string; testId?: string }) {
  const t = useTranslations("recruitment");
  if (status === "completed") {
    return (
      <span
        className="inline-flex items-center gap-1 text-xs text-emerald-700"
        data-testid={testId}
      >
        <CheckCircle2 className="size-3.5" /> {t("addCandidateStatusParsed")}
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span
        className="inline-flex items-center gap-1 text-xs text-destructive"
        data-testid={testId}
      >
        <AlertTriangle className="size-3.5" /> {t("addCandidateStatusFailed")}
      </span>
    );
  }
  return (
    <span
      className="inline-flex items-center gap-1 text-xs text-muted-foreground"
      data-testid={testId}
    >
      <Loader2 className="size-3.5 animate-spin" />{" "}
      {status === "processing"
        ? t("addCandidateStatusParsing")
        : t("addCandidateStatusQueued")}
    </span>
  );
}

interface SummaryStepProps {
  rows: ImportRow[];
  busy: boolean;
  onCancel: () => void;
  onImport: () => void;
  onChangeAction: (fileId: string, action: ImportRow["action"]) => void;
}

function SummaryStep({
  rows,
  busy,
  onCancel,
  onImport,
  onChangeAction,
}: SummaryStepProps) {
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  if (rows.length === 0) {
    return (
      <div className="space-y-3 text-center">
        <p className="text-sm text-muted-foreground">
          {t("addCandidateNothingToImport")}
        </p>
        <DialogFooter>
          <Button variant="ghost" onClick={onCancel}>
            {t("addCandidateClose")}
          </Button>
        </DialogFooter>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">
        {t("addCandidateReviewHint")}
      </p>
      <ul className="max-h-[360px] space-y-2 overflow-y-auto">
        {rows.map((r) => (
          <li
            key={r.file_id}
            className="rounded-md border px-3 py-2 text-sm"
            data-testid={`vacancy-candidates-add-file-${r.file_id}`}
          >
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate font-medium">
                  {r.full_name || r.filename}
                </p>
                <p className="truncate text-xs text-muted-foreground">
                  {r.email || t("addCandidateNoEmailParsed")}
                </p>
              </div>
              {r.existing_candidate_id && (
                <span
                  className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-medium text-amber-800"
                  data-testid={`vacancy-candidate-duplicate-warning-${r.file_id}`}
                >
                  {t("addCandidateDuplicate")}
                </span>
              )}
            </div>
            {r.existing_candidate_id && (
              <div className="mt-2 flex flex-col gap-1 text-xs">
                <label className="flex items-center gap-2">
                  <input
                    type="radio"
                    name={`dedup-${r.file_id}`}
                    checked={r.action === "link"}
                    onChange={() => onChangeAction(r.file_id, "link")}
                  />
                  <span>
                    {t.rich("addCandidateLinkTo", {
                      name:
                        r.existing_candidate_full_name ||
                        t("addCandidateExistingCandidate"),
                      strong: (chunks) => (
                        <span className="font-medium">{chunks}</span>
                      ),
                    })}
                  </span>
                </label>
                <label className="flex items-center gap-2">
                  <input
                    type="radio"
                    name={`dedup-${r.file_id}`}
                    checked={r.action === "create"}
                    onChange={() => onChangeAction(r.file_id, "create")}
                  />
                  <span>{t("addCandidateCreateNew")}</span>
                </label>
              </div>
            )}
          </li>
        ))}
      </ul>
      <DialogFooter>
        <Button variant="ghost" onClick={onCancel} disabled={busy}>
          {tc("cancel")}
        </Button>
        <Button
          onClick={onImport}
          disabled={busy}
          data-testid="vacancy-candidates-add-submit-btn"
        >
          {busy
            ? t("addCandidateImporting")
            : t("addCandidateImportBtn", { count: rows.length })}
        </Button>
      </DialogFooter>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Manual tab
// ---------------------------------------------------------------------------

interface ManualTabProps {
  vacancyId: string;
  onCreated: (candidateId: string) => void;
  onCancel: () => void;
}

interface ManualForm {
  full_name: string;
  email: string;
  phone: string;
  linkedin_url: string;
  location: string;
  current_position: string;
  years_of_experience: string;
  source: string;
  notes: string;
}

const EMPTY_MANUAL: ManualForm = {
  full_name: "",
  email: "",
  phone: "",
  linkedin_url: "",
  location: "",
  current_position: "",
  years_of_experience: "",
  source: "",
  notes: "",
};

function ManualTab({ vacancyId, onCreated, onCancel }: ManualTabProps) {
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const [form, setForm] = useState<ManualForm>(EMPTY_MANUAL);
  const [submitting, setSubmitting] = useState(false);
  const [conflict, setConflict] = useState<{
    existing_candidate_id: string;
    message: string;
  } | null>(null);

  const update = useCallback(
    (key: keyof ManualForm) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
      setForm((prev) => ({ ...prev, [key]: e.target.value }));
    },
    [],
  );

  const submit = useCallback(
    async (linkCandidateId?: string) => {
      const validationError = manualPayloadValidationError(t, form);
      if (validationError) {
        toast.error(validationError);
        return;
      }
      setSubmitting(true);
      try {
        const payload = buildManualPayload(form, linkCandidateId);
        const result = await api.post<ManualCandidateResponse>(
          `/recruitment/vacancies/${vacancyId}/candidates`,
          payload,
        );
        toast.success(
          t("addCandidateToastAdded", { name: result.full_name }),
        );
        setConflict(null);
        onCreated(result.id);
        setForm(EMPTY_MANUAL);
      } catch (err) {
        if (
          err instanceof ApiError &&
          err.status === 409 &&
          err.detail &&
          typeof err.detail === "object" &&
          (err.detail as { code?: unknown }).code ===
            "candidate_email_conflict"
        ) {
          const detail = err.detail as {
            existing_candidate_id?: string;
            message?: string;
          };
          if (detail.existing_candidate_id) {
            setConflict({
              existing_candidate_id: detail.existing_candidate_id,
              message: detail.message || t("addCandidateEmailConflict"),
            });
            return;
          }
        }
        toast.error(
          err instanceof Error ? err.message : t("addCandidateAddFailed"),
        );
      } finally {
        setSubmitting(false);
      }
    },
    [form, onCreated, vacancyId, t],
  );

  return (
    <form
      data-testid="vacancy-candidates-add-manual-form"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      className="space-y-4"
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <Field
          label={t("addCandidateFieldFullName")}
          name="full_name"
          value={form.full_name}
          onChange={update("full_name")}
        />
        <Field
          label={t("columnEmail")}
          type="email"
          name="email"
          value={form.email}
          onChange={update("email")}
        />
        <Field
          label={t("candidateFieldPhone")}
          name="phone"
          value={form.phone}
          onChange={update("phone")}
        />
        <Field
          label={t("candidateFieldLinkedinUrl")}
          name="linkedin_url"
          value={form.linkedin_url}
          onChange={update("linkedin_url")}
        />
        <Field
          label={t("candidateFieldLocation")}
          name="location"
          value={form.location}
          onChange={update("location")}
        />
        <Field
          label={t("candidateFieldCurrentPosition")}
          name="current_position"
          value={form.current_position}
          onChange={update("current_position")}
        />
        <Field
          label={t("candidateFieldYearsExperience")}
          name="years_of_experience"
          type="number"
          inputMode="numeric"
          min={0}
          max={80}
          value={form.years_of_experience}
          onChange={update("years_of_experience")}
        />
        <Field
          label={t("columnSource")}
          name="source"
          value={form.source}
          onChange={update("source")}
          placeholder={t("addCandidateSourcePlaceholder")}
        />
      </div>
      <div className="space-y-1">
        <Label className="text-xs" htmlFor="vacancy-candidates-add-manual-field-notes">
          {t("candidateFieldNotes")}
        </Label>
        <Textarea
          id="vacancy-candidates-add-manual-field-notes"
          rows={3}
          value={form.notes}
          onChange={update("notes")}
          data-testid="vacancy-candidates-add-manual-field-notes"
        />
      </div>

      {conflict && (
        <div className={`rounded-md border p-3 text-sm ${ALERT_TONE.amber}`}>
          <p className="font-medium">{conflict.message}</p>
          <p className="mt-1 text-xs opacity-80">
            {t("addCandidateLinkExistingPrompt")}
          </p>
          <div className="mt-2 flex gap-2">
            <Button
              size="sm"
              variant="outline"
              type="button"
              disabled={submitting}
              onClick={() => setConflict(null)}
            >
              {tc("cancel")}
            </Button>
            <Button
              size="sm"
              type="button"
              disabled={submitting}
              onClick={() => submit(conflict.existing_candidate_id)}
            >
              {t("addCandidateLinkExisting")}
            </Button>
          </div>
        </div>
      )}

      <DialogFooter>
        <Button
          type="button"
          variant="ghost"
          disabled={submitting}
          onClick={onCancel}
        >
          {tc("cancel")}
        </Button>
        <Button
          type="submit"
          disabled={submitting}
          data-testid="vacancy-candidates-add-submit-btn"
        >
          {submitting ? t("addCandidateAdding") : t("candidateAddButton")}
        </Button>
      </DialogFooter>
    </form>
  );
}

interface FieldProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label: string;
  name: string;
}

function Field({ label, name, ...rest }: FieldProps) {
  const id = `vacancy-candidates-add-manual-field-${name}`;
  return (
    <div className="space-y-1">
      <Label className="text-xs" htmlFor={id}>
        {label}
      </Label>
      <Input id={id} {...rest} data-testid={id} />
    </div>
  );
}

