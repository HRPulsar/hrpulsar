"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import type { ImportJob, ImportJobList } from "@/lib/types";
import { formatDate } from "@/lib/date-format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { RequireSection } from "@/components/require-section";
import { usePermissions } from "@/hooks/use-permissions";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Hint } from "@/components/ui/hint";
import { toast } from "sonner";
import { Pagination } from "@/components/pagination";
import { AlertTriangle, CheckCircle2, Download, Info, Upload, X } from "lucide-react";
import { BADGE_COLOR } from "@/lib/badge-tones";
import { useAuth } from "@/context/auth-context";

const PAGE_SIZE = 20;

// HRP-806: a demo emails only this many new employees per session. Copy of
// DEMO_IMPORT_EMAIL_LIMIT in backend/app/modules/data_import/tasks.py,
// pinned by demo-email-limit-parity.test.ts.
const DEMO_IMPORT_EMAIL_LIMIT = 5;

/** Import type → key in the `settings` message namespace. */
const importTypes = [
  { value: "employees", labelKey: "importTypeEmployees" },
  { value: "dictionaries", labelKey: "importTypeDictionaries" },
];

// HRP-671: history rows render the same labels as the upload picker above.
const IMPORT_TYPE_KEYS: Record<string, string> = Object.fromEntries(
  importTypes.map((item) => [item.value, item.labelKey]),
);

const statusColors: Record<string, string> = {
  pending: BADGE_COLOR.yellow,
  processing: BADGE_COLOR.blue,
  completed: BADGE_COLOR.green,
  failed: BADGE_COLOR.red,
};

const STATUS_KEYS: Record<string, string> = {
  pending: "importStatusPending",
  processing: "importStatusProcessing",
  completed: "importStatusCompleted",
  failed: "importStatusFailed",
};

const templates: Record<string, { columns: string[]; required: string[]; example: string[][] }> = {
  employees: {
    columns: ["email", "first_name", "last_name", "position", "hire_date"],
    required: ["email", "first_name", "last_name", "position", "hire_date"],
    example: [
      ["john@company.com", "John", "Doe", "Software Engineer", "2024-01-15"],
      ["jane@company.com", "Jane", "Smith", "Product Manager", "2024-03-01"],
    ],
  },
  dictionaries: {
    columns: ["type", "title", "description"],
    required: ["type", "title"],
    example: [
      ["grade", "Junior", "Entry-level position"],
      ["grade", "Middle", "Mid-level position"],
      ["specialization", "Backend", "Backend development"],
    ],
  },
};

// HRP-806: Excel reads a CSV with the separator of its locale, so a German or
// Russian Excel put the comma template into one column. This line tells Excel
// the separator; the backend reader skips it.
const EXCEL_SEPARATOR_HINT = "sep=,";

function downloadTemplate(type: string) {
  const tmpl = templates[type];
  if (!tmpl) return;
  const rows = [tmpl.columns, ...tmpl.example];
  const csv = [
    EXCEL_SEPARATOR_HINT,
    ...rows.map((r) => r.map((c) => `"${c}"`).join(",")),
  ].join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${type}_template.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

/** Problem codes are rendered through the message catalog, so the preview
 * grid stays translatable. */
type CellErrorCode = "required" | "email" | "date";

/** The file as the import will read it - `POST /import/{type}/preview`:
 * its first rows, and the counts for the whole file. */
interface ImportPreview {
  columns: string[];
  rows: {
    line: number;
    cells: string[];
    problem: { code: CellErrorCode; column: number } | null;
  }[];
  total_rows: number;
  problem_rows: number;
}

export default function ImportPage() {
  const t = useTranslations("settings");
  const tSections = useTranslations("sections");
  const tc = useTranslations("common");
  const { user } = useAuth();
  const isDemo = !!user?.tenant_is_demo;
  // HRP-831: `view` reads the history, `manage` uploads.
  const canImport = usePermissions().canImport;
  const [jobs, setJobs] = useState<ImportJob[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [importType, setImportType] = useState("employees");
  const [uploading, setUploading] = useState(false);
  // Reading a file for the preview is not importing it: the Import button
  // keeps its own label, only the file picker waits.
  const [previewing, setPreviewing] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [errorJob, setErrorJob] = useState<ImportJob | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // GF9: Preview state
  const [previewFile, setPreviewFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);

  const loadJobs = useCallback(async (p?: number) => {
    try {
      const currentPage = p ?? page;
      const params = new URLSearchParams();
      params.set("skip", String((currentPage - 1) * PAGE_SIZE));
      params.set("limit", String(PAGE_SIZE));
      const data = await api.get<ImportJobList>(`/import/jobs?${params}`);
      setJobs(data.items);
      setTotal(data.total);
      return data.items;
    } catch {
      // ignore
      return [];
    } finally {
      setLoading(false);
    }
  }, [page]);

  useEffect(() => {
    loadJobs(page);
  }, [page, loadJobs]);

  // Poll while any job is processing
  useEffect(() => {
    const hasProcessing = jobs.some((j) => j.status === "pending" || j.status === "processing");
    if (hasProcessing && !pollingRef.current) {
      pollingRef.current = setInterval(loadJobs, 3000);
    } else if (!hasProcessing && pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
        pollingRef.current = null;
      }
    };
  }, [jobs, loadJobs]);

  // HRP-806: the backend reads the file for the preview with the import's
  // own reader and row check - a page-side parser once called a file valid
  // that the import then refused row by row.
  async function handleFilePreview(file: File) {
    // The previous file's table goes first: a refused or empty file must
    // not leave it standing under the new name.
    clearPreview();
    setPreviewing(true);
    try {
      const result = await api.upload<ImportPreview>(
        `/import/${importType}/preview`,
        file,
      );
      if (result.total_rows === 0) {
        toast.error(t("importFileNeedsRows"));
        return;
      }
      setPreviewFile(file);
      setPreview(result);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("importFailed"));
    } finally {
      setPreviewing(false);
    }
  }

  function clearPreview() {
    setPreviewFile(null);
    setPreview(null);
  }

  async function confirmImport() {
    if (!previewFile) return;
    setUploading(true);
    try {
      await api.upload<ImportJob>(`/import/${importType}`, previewFile);
      toast.success(t("importStarted"));
      clearPreview();
      setPage(1);
      await loadJobs(1);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("importFailed"));
    } finally {
      setUploading(false);
    }
  }

  function onFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) handleFilePreview(file);
    e.target.value = "";
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFilePreview(file);
  }

  function onDragOver(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(true);
  }

  function onDragLeave(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
  }

  function cellErrorMessage(code: CellErrorCode, column: number): string {
    if (code === "required") {
      return t("importRequiredColumn", {
        column: templates[importType]?.columns[column] ?? "",
      });
    }
    if (code === "email") return t("importInvalidEmail");
    return t("importInvalidDate");
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">
        {tc("loading")}
      </div>
    );
  }

  const errorCount = preview?.problem_rows ?? 0;
  const hasErrors = errorCount > 0;
  // The import reads columns by position: the first `required` ones are the
  // required ones, whatever the file's header calls them, and a column the
  // file lacks is shown under the template's name.
  const requiredCount = templates[importType]?.required.length ?? 0;
  const previewColumns = preview
    ? Array.from(
        { length: Math.max(preview.columns.length, requiredCount) },
        (_, i) => preview.columns[i] || templates[importType]?.columns[i] || "",
      )
    : [];

  return (
    <RequireSection code="import">
    <div className="space-y-6">
      <div>
        <div className="flex items-center gap-2">
          <h1 className="text-2xl font-semibold tracking-tight">
            {t("importTitle")}
          </h1>
          <Hint
            text={tSections("import.hint")}
            data-testid="import-hint-title"
          />
        </div>
        <p className="text-sm text-muted-foreground">{t("importSubtitle")}</p>
      </div>

      {/* Upload section - `manage` on the import section (HRP-831) */}
      {canImport && (
      <Card>
        <CardHeader>
          <CardTitle>{t("importUploadTitle")}</CardTitle>
          <CardDescription>{t("importUploadDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center gap-4">
            <Select value={importType} onValueChange={(val) => { setImportType(val); clearPreview(); }}>
              <SelectTrigger className="w-48">
                <SelectValue>
                  {(() => {
                    const entry = importTypes.find(
                      (item) => item.value === importType,
                    );
                    return entry ? t(entry.labelKey) : "";
                  })()}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {importTypes.map((item) => (
                  <SelectItem key={item.value} value={item.value}>
                    {t(item.labelKey)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button variant="outline" size="sm" onClick={() => downloadTemplate(importType)}>
              <Download className="mr-1 h-4 w-4" />
              {t("importDownloadTemplate")}
            </Button>
          </div>

          {!previewFile ? (
            <div
              className={`relative flex flex-col items-center justify-center rounded-lg border-2 border-dashed p-8 transition-colors ${
                dragOver
                  ? "border-primary bg-primary/5"
                  : "border-border hover:border-primary/50"
              }`}
              onDrop={onDrop}
              onDragOver={onDragOver}
              onDragLeave={onDragLeave}
            >
              <Upload className="mb-3 h-8 w-8 text-muted-foreground" />
              <p className="text-sm font-medium">
                {t.rich("importDropzone", {
                  browse: (chunks) => (
                    <button
                      type="button"
                      className="text-primary underline underline-offset-2"
                      onClick={() => fileInputRef.current?.click()}
                      disabled={uploading || previewing}
                    >
                      {chunks}
                    </button>
                  ),
                })}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {t("importSupportedFormats")}
              </p>
              <input
                ref={fileInputRef}
                type="file"
                accept=".xlsx,.csv"
                className="hidden"
                onChange={onFileSelect}
                disabled={uploading || previewing}
              />
            </div>
          ) : null}

          <div className="rounded-md bg-muted/50 p-3">
            <p className="text-xs font-medium text-muted-foreground">
              {t("importExpectedColumns", {
                type: (() => {
                  const entry = importTypes.find(
                    (item) => item.value === importType,
                  );
                  return entry ? t(entry.labelKey) : "";
                })(),
              })}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              {templates[importType]?.columns.join(", ")}
            </p>
            {importType === "employees" &&
              (isDemo ? (
                <p
                  className="mt-2 flex items-start gap-1.5 text-xs font-medium text-foreground"
                  data-testid="import-demo-email-limit-note"
                >
                  <Info className="mt-px h-3.5 w-3.5 shrink-0 text-primary" />
                  {t("importEmployeesEmailNoteDemo", {
                    limit: DEMO_IMPORT_EMAIL_LIMIT,
                  })}
                </p>
              ) : (
                <p className="mt-2 text-xs text-muted-foreground">
                  {t("importEmployeesEmailNote")}
                </p>
              ))}
            {isDemo && (
              <p
                className="mt-2 flex items-start gap-1.5 text-xs font-medium text-foreground"
                data-testid="import-demo-credits-note"
              >
                <Info className="mt-px h-3.5 w-3.5 shrink-0 text-primary" />
                {t("importDemoCreditsNote")}
              </p>
            )}
          </div>
        </CardContent>
      </Card>
      )}

      {/* GF9: Preview section */}
      {previewFile && (
        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <div>
              <CardTitle>
                {t("importPreviewTitle", { name: previewFile.name })}
              </CardTitle>
              <CardDescription>
                {t("importRowsFound", { count: preview?.total_rows ?? 0 })}
                {hasErrors ? (
                  <span className="ml-2 text-destructive">
                    <AlertTriangle className="mr-1 inline h-3.5 w-3.5" />
                    {t("importErrorsDetected", { count: errorCount })}
                  </span>
                ) : (
                  <span className="ml-2 text-green-600">
                    <CheckCircle2 className="mr-1 inline h-3.5 w-3.5" />
                    {t("importAllValid")}
                  </span>
                )}
              </CardDescription>
            </div>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={clearPreview} disabled={uploading}>
                <X className="mr-1 h-4 w-4" />
                {tc("cancel")}
              </Button>
              <Button size="sm" onClick={confirmImport} disabled={uploading}>
                <Upload className="mr-1 h-4 w-4" />
                {uploading ? t("importUploading") : t("importAction")}
              </Button>
            </div>
          </CardHeader>
          {preview && (
            <CardContent>
              <div className="max-h-96 overflow-auto rounded-lg border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-12 text-center">#</TableHead>
                      {previewColumns.map((h, i) => (
                        <TableHead key={i}>
                          {h}
                          {i < requiredCount && (
                            <span className="ml-0.5 text-destructive">*</span>
                          )}
                        </TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {preview.rows.map((row) => {
                      const problem = row.problem;
                      return (
                        <TableRow key={row.line} className={problem ? "bg-destructive/5" : ""}>
                          <TableCell className="text-center text-xs text-muted-foreground">
                            {row.line}
                          </TableCell>
                          {previewColumns.map((_, ci) => {
                            const cellErr = problem?.column === ci ? problem : null;
                            return (
                              <TableCell
                                key={ci}
                                className={cellErr ? "relative" : ""}
                              >
                                <span className={cellErr ? "text-destructive font-medium" : ""}>
                                  {row.cells[ci] || ""}
                                </span>
                                {cellErr && (
                                  <span className="block text-xs text-destructive mt-0.5">
                                    {cellErrorMessage(cellErr.code, ci)}
                                  </span>
                                )}
                              </TableCell>
                            );
                          })}
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </div>
              {preview.rows.length < preview.total_rows && (
                <p
                  className="mt-3 text-xs text-muted-foreground"
                  data-testid="import-preview-truncated"
                >
                  {t("importPreviewTruncated", {
                    shown: preview.rows.length,
                    total: preview.total_rows,
                  })}
                </p>
              )}
              {hasErrors && (
                <p className="mt-3 text-xs text-muted-foreground">
                  {t("importErrorsWarning")}
                </p>
              )}
            </CardContent>
          )}
        </Card>
      )}

      {/* Import history */}
      <Card>
        <CardHeader>
          <CardTitle>{t("importHistoryTitle")}</CardTitle>
          <CardDescription>
            {t("importJobsCount", { count: total })}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {jobs.length === 0 ? (
            <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground">
              {t("importNoJobs")}
            </div>
          ) : (
            <div className="rounded-lg border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("importColFile")}</TableHead>
                    <TableHead>{t("importColType")}</TableHead>
                    <TableHead>{t("importColStatus")}</TableHead>
                    <TableHead>{t("importColProgress")}</TableHead>
                    <TableHead>{t("importColErrors")}</TableHead>
                    <TableHead>{t("importColDate")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {jobs.map((job) => (
                    <TableRow key={job.id}>
                      <TableCell className="font-medium">{job.file_name}</TableCell>
                      <TableCell>
                        {IMPORT_TYPE_KEYS[job.import_type]
                          ? t(IMPORT_TYPE_KEYS[job.import_type])
                          : job.import_type}
                      </TableCell>
                      <TableCell>
                        <Badge variant="secondary" className={statusColors[job.status] || ""}>
                          {STATUS_KEYS[job.status] ? t(STATUS_KEYS[job.status]) : job.status}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <div className="h-2 w-24 overflow-hidden rounded-full bg-muted">
                            <div
                              className="h-full rounded-full bg-primary transition-all"
                              style={{
                                width: `${job.total_rows > 0 ? Math.round((job.processed_rows / job.total_rows) * 100) : 0}%`,
                              }}
                            />
                          </div>
                          <span className="text-xs text-muted-foreground">
                            {job.processed_rows}/{job.total_rows}
                          </span>
                        </div>
                      </TableCell>
                      <TableCell>
                        {job.error_rows > 0 ? (
                          <button
                            type="button"
                            className="text-sm text-destructive underline underline-offset-2"
                            onClick={() => setErrorJob(job)}
                          >
                            {t("importErrorCount", { count: job.error_rows })}
                          </button>
                        ) : (
                          <span className="text-sm text-muted-foreground">—</span>
                        )}
                        {(job.errors?.emails_failed ?? 0) > 0 ? (
                          <div
                            className="text-xs text-muted-foreground"
                            data-testid={`import-job-${job.id}-emails-failed`}
                          >
                            {t("importEmailsFailed", { count: job.errors?.emails_failed ?? 0 })}
                          </div>
                        ) : null}
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {formatDate(job.created_at)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      <Pagination page={page} pageSize={PAGE_SIZE} total={total} onPageChange={setPage} />

      {/* Error details dialog */}
      <Dialog open={!!errorJob} onOpenChange={(open) => !open && setErrorJob(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {t("importErrorsTitle", { name: errorJob?.file_name ?? "" })}
            </DialogTitle>
          </DialogHeader>
          <div className="max-h-80 overflow-y-auto">
            {errorJob?.errors?.rows && errorJob.errors.rows.length > 0 ? (
              <div className="rounded-lg border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-20">{t("importColRow")}</TableHead>
                      <TableHead>{t("importColError")}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {errorJob.errors.rows.map((err, i) => (
                      <TableRow key={i}>
                        <TableCell className="font-mono text-sm">{err.row}</TableCell>
                        <TableCell className="text-sm text-destructive">{err.error}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                {t("importNoErrorDetails", { count: errorJob?.error_rows ?? 0 })}
              </p>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
    </RequireSection>
  );
}
