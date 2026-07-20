"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { ImportJob, ImportJobList } from "@/lib/types";
import { formatDate } from "@/lib/date-format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { RequireRole } from "@/components/require-role";
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
import { toast } from "sonner";
import { Pagination } from "@/components/pagination";
import { AlertTriangle, CheckCircle2, Download, Upload, X } from "lucide-react";
import { BADGE_COLOR } from "@/lib/badge-tones";

const PAGE_SIZE = 20;

const importTypes = [
  { value: "employees", label: "Employees", description: "Import employees from Excel file" },
  { value: "dictionaries", label: "Dictionaries", description: "Import dictionary items from Excel file" },
];

const statusColors: Record<string, string> = {
  pending: BADGE_COLOR.yellow,
  processing: BADGE_COLOR.blue,
  completed: BADGE_COLOR.green,
  failed: BADGE_COLOR.red,
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

function downloadTemplate(type: string) {
  const tmpl = templates[type];
  if (!tmpl) return;
  const rows = [tmpl.columns, ...tmpl.example];
  const csv = rows.map((r) => r.map((c) => `"${c}"`).join(",")).join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${type}_template.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

function parseCSV(text: string): string[][] {
  const rows: string[][] = [];
  let current = "";
  let inQuotes = false;
  let row: string[] = [];

  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (inQuotes) {
      if (ch === '"' && text[i + 1] === '"') {
        current += '"';
        i++;
      } else if (ch === '"') {
        inQuotes = false;
      } else {
        current += ch;
      }
    } else if (ch === '"') {
      inQuotes = true;
    } else if (ch === ",") {
      row.push(current.trim());
      current = "";
    } else if (ch === "\n" || (ch === "\r" && text[i + 1] === "\n")) {
      row.push(current.trim());
      if (row.some((c) => c !== "")) rows.push(row);
      row = [];
      current = "";
      if (ch === "\r") i++;
    } else {
      current += ch;
    }
  }
  row.push(current.trim());
  if (row.some((c) => c !== "")) rows.push(row);
  return rows;
}

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

interface CellError {
  row: number;
  col: number;
  message: string;
}

function validatePreview(
  rows: string[][],
  headers: string[],
  type: string,
): CellError[] {
  const tmpl = templates[type];
  if (!tmpl) return [];
  const errors: CellError[] = [];

  for (let r = 0; r < rows.length; r++) {
    for (let c = 0; c < headers.length; c++) {
      const col = headers[c];
      const val = rows[r]?.[c] ?? "";

      if (tmpl.required.includes(col) && !val) {
        errors.push({ row: r, col: c, message: `${col} is required` });
        continue;
      }

      if (!val) continue;

      if (col === "email" && !EMAIL_RE.test(val)) {
        errors.push({ row: r, col: c, message: "Invalid email format" });
      }
      if (col === "hire_date" && !DATE_RE.test(val)) {
        errors.push({ row: r, col: c, message: "Date must be YYYY-MM-DD" });
      }
    }
  }

  return errors;
}

export default function ImportPage() {
  const [jobs, setJobs] = useState<ImportJob[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [importType, setImportType] = useState("employees");
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [errorJob, setErrorJob] = useState<ImportJob | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // GF9: Preview state
  const [previewFile, setPreviewFile] = useState<File | null>(null);
  const [previewHeaders, setPreviewHeaders] = useState<string[]>([]);
  const [previewRows, setPreviewRows] = useState<string[][]>([]);
  const [previewErrors, setPreviewErrors] = useState<CellError[]>([]);

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

  function handleFilePreview(file: File) {
    const reader = new FileReader();
    reader.onload = (e) => {
      const text = e.target?.result;
      if (typeof text !== "string") return;
      const parsed = parseCSV(text);
      if (parsed.length < 2) {
        toast.error("File must have a header row and at least one data row");
        return;
      }
      const headers = parsed[0];
      const dataRows = parsed.slice(1);
      const errors = validatePreview(dataRows, headers, importType);
      setPreviewFile(file);
      setPreviewHeaders(headers);
      setPreviewRows(dataRows);
      setPreviewErrors(errors);
    };
    reader.readAsText(file);
  }

  function clearPreview() {
    setPreviewFile(null);
    setPreviewHeaders([]);
    setPreviewRows([]);
    setPreviewErrors([]);
  }

  async function confirmImport() {
    if (!previewFile) return;
    setUploading(true);
    try {
      await api.upload<ImportJob>(`/import/${importType}`, previewFile);
      toast.success("Import started");
      clearPreview();
      setPage(1);
      await loadJobs(1);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to start import");
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

  function getCellError(row: number, col: number): string | undefined {
    return previewErrors.find((e) => e.row === row && e.col === col)?.message;
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">
        Loading...
      </div>
    );
  }

  const errorCount = previewErrors.length;
  const hasErrors = errorCount > 0;

  return (
    <RequireRole admin>
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Data Import</h1>
        <p className="text-sm text-muted-foreground">
          Import employees and dictionaries from Excel or CSV files
        </p>
      </div>

      {/* Upload section */}
      <Card>
        <CardHeader>
          <CardTitle>Upload file</CardTitle>
          <CardDescription>
            Select import type, download a template, then upload your file
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center gap-4">
            <Select value={importType} onValueChange={(val) => { setImportType(val); clearPreview(); }}>
              <SelectTrigger className="w-48">
                <SelectValue>
                  {importTypes.find((t) => t.value === importType)?.label ?? ""}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {importTypes.map((t) => (
                  <SelectItem key={t.value} value={t.value}>
                    {t.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button variant="outline" size="sm" onClick={() => downloadTemplate(importType)}>
              <Download className="mr-1 h-4 w-4" />
              Download template
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
                Drag and drop your file here, or{" "}
                <button
                  type="button"
                  className="text-primary underline underline-offset-2"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={uploading}
                >
                  browse
                </button>
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                Supports .xlsx and .csv files
              </p>
              <input
                ref={fileInputRef}
                type="file"
                accept=".xlsx,.csv,.xls"
                className="hidden"
                onChange={onFileSelect}
                disabled={uploading}
              />
            </div>
          ) : null}

          <div className="rounded-md bg-muted/50 p-3">
            <p className="text-xs font-medium text-muted-foreground">
              Expected columns for {importTypes.find((t) => t.value === importType)?.label}:
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              {templates[importType]?.columns.join(", ")}
            </p>
          </div>
        </CardContent>
      </Card>

      {/* GF9: Preview section */}
      {previewFile && (
        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <div>
              <CardTitle>Preview: {previewFile.name}</CardTitle>
              <CardDescription>
                {previewRows.length} row{previewRows.length !== 1 ? "s" : ""} found
                {hasErrors ? (
                  <span className="ml-2 text-destructive">
                    <AlertTriangle className="mr-1 inline h-3.5 w-3.5" />
                    {errorCount} error{errorCount !== 1 ? "s" : ""} detected
                  </span>
                ) : (
                  <span className="ml-2 text-green-600">
                    <CheckCircle2 className="mr-1 inline h-3.5 w-3.5" />
                    All rows valid
                  </span>
                )}
              </CardDescription>
            </div>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={clearPreview} disabled={uploading}>
                <X className="mr-1 h-4 w-4" />
                Cancel
              </Button>
              <Button size="sm" onClick={confirmImport} disabled={uploading}>
                <Upload className="mr-1 h-4 w-4" />
                {uploading ? "Importing..." : "Import"}
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            <div className="max-h-96 overflow-auto rounded-lg border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-12 text-center">#</TableHead>
                    {previewHeaders.map((h, i) => (
                      <TableHead key={i}>
                        {h}
                        {templates[importType]?.required.includes(h) && (
                          <span className="ml-0.5 text-destructive">*</span>
                        )}
                      </TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {previewRows.map((row, ri) => {
                    const rowHasError = previewErrors.some((e) => e.row === ri);
                    return (
                      <TableRow key={ri} className={rowHasError ? "bg-destructive/5" : ""}>
                        <TableCell className="text-center text-xs text-muted-foreground">
                          {ri + 2}
                        </TableCell>
                        {previewHeaders.map((_, ci) => {
                          const cellErr = getCellError(ri, ci);
                          return (
                            <TableCell
                              key={ci}
                              className={cellErr ? "relative" : ""}
                            >
                              <span className={cellErr ? "text-destructive font-medium" : ""}>
                                {row[ci] || ""}
                              </span>
                              {cellErr && (
                                <span className="block text-xs text-destructive mt-0.5">
                                  {cellErr}
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
            {hasErrors && (
              <p className="mt-3 text-xs text-muted-foreground">
                Rows with errors will likely fail during import. You can still proceed — the server will report detailed errors after processing.
              </p>
            )}
          </CardContent>
        </Card>
      )}

      {/* Import history */}
      <Card>
        <CardHeader>
          <CardTitle>Import history</CardTitle>
          <CardDescription>
            {total} import job{total !== 1 ? "s" : ""}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {jobs.length === 0 ? (
            <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground">
              No import jobs yet
            </div>
          ) : (
            <div className="rounded-lg border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>File</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Progress</TableHead>
                    <TableHead>Errors</TableHead>
                    <TableHead>Date</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {jobs.map((job) => (
                    <TableRow key={job.id}>
                      <TableCell className="font-medium">{job.file_name}</TableCell>
                      <TableCell className="capitalize">{job.import_type}</TableCell>
                      <TableCell>
                        <Badge variant="secondary" className={statusColors[job.status] || ""}>
                          {job.status}
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
                            {job.error_rows} error{job.error_rows !== 1 ? "s" : ""}
                          </button>
                        ) : (
                          <span className="text-sm text-muted-foreground">—</span>
                        )}
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
            <DialogTitle>Import errors — {errorJob?.file_name}</DialogTitle>
          </DialogHeader>
          <div className="max-h-80 overflow-y-auto">
            {errorJob?.errors?.rows && errorJob.errors.rows.length > 0 ? (
              <div className="rounded-lg border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-20">Row</TableHead>
                      <TableHead>Error</TableHead>
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
                {errorJob?.error_rows} row(s) failed but no detailed error info is available.
              </p>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
    </RequireRole>
  );
}
