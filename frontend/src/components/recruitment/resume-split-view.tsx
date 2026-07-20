"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { Resume } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Download, FileText, Loader2, Pencil, Save, X } from "lucide-react";
import { toast } from "sonner";

interface ResumeSplitViewProps {
  resume: Resume;
  onUpdated?: (resume: Resume) => void;
}

interface DownloadResponse {
  url: string;
  mime_type: string;
  filename: string;
}

function formatLabel(key: string) {
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function ParsedFieldEditor({
  field,
  value,
  saving,
  onSave,
}: {
  field: string;
  value: unknown;
  saving: boolean;
  onSave: (next: unknown) => void;
}) {
  const displayValue =
    typeof value === "string" ? value : JSON.stringify(value, null, 2);
  const [draftOverride, setDraftOverride] = useState<string | null>(null);
  const editing = draftOverride !== null;
  const draft = draftOverride ?? displayValue;

  function commit() {
    if (typeof value === "string") {
      onSave(draft);
    } else {
      try {
        const parsed = JSON.parse(draft);
        onSave(parsed);
      } catch {
        toast.error(`Field "${formatLabel(field)}" — invalid JSON`);
        return;
      }
    }
    setDraftOverride(null);
  }

  function cancel() {
    setDraftOverride(null);
  }

  if (!editing) {
    return (
      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-2 space-y-0">
          <CardTitle className="text-sm">{formatLabel(field)}</CardTitle>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => setDraftOverride(displayValue)}
            disabled={saving}
            data-testid={`resume-field-edit-${field}`}
            aria-label={`Edit ${formatLabel(field)}`}
          >
            <Pencil className="size-3.5" />
          </Button>
        </CardHeader>
        <CardContent>
          {typeof value === "string" ? (
            <p className="whitespace-pre-wrap text-sm text-muted-foreground">
              {value || <span className="italic">empty</span>}
            </p>
          ) : Array.isArray(value) ? (
            <ul className="list-inside list-disc space-y-1 text-sm text-muted-foreground">
              {value.map((item, i) => (
                <li key={i}>
                  {typeof item === "string"
                    ? item
                    : JSON.stringify(item)}
                </li>
              ))}
            </ul>
          ) : (
            <pre className="whitespace-pre-wrap text-xs text-muted-foreground font-mono">
              {JSON.stringify(value, null, 2)}
            </pre>
          )}
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2 space-y-0">
        <CardTitle className="text-sm">{formatLabel(field)}</CardTitle>
        <div className="flex items-center gap-1">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={cancel}
            disabled={saving}
            aria-label="Cancel"
          >
            <X className="size-3.5" />
          </Button>
          <Button
            type="button"
            size="sm"
            onClick={commit}
            disabled={saving}
            data-testid={`resume-field-save-${field}`}
          >
            {saving ? <Loader2 className="size-3.5 animate-spin" /> : <Save className="size-3.5" />}
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {typeof value === "string" && (value.length < 80 || !value.includes("\n")) ? (
          <Input
            value={draft}
            onChange={(e) => setDraftOverride(e.target.value)}
            disabled={saving}
            autoFocus
          />
        ) : (
          <Textarea
            value={draft}
            onChange={(e) => setDraftOverride(e.target.value)}
            rows={Math.min(20, Math.max(4, draft.split("\n").length))}
            disabled={saving}
            className="font-mono text-xs"
            autoFocus
          />
        )}
      </CardContent>
    </Card>
  );
}

export function ResumeSplitView({ resume, onUpdated }: ResumeSplitViewProps) {
  const [downloadUrl, setDownloadUrl] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState(false);
  const [saving, setSaving] = useState(false);

  const parsed = useMemo(
    () => (resume.parsed_data as Record<string, unknown>) ?? {},
    [resume.parsed_data],
  );

  useEffect(() => {
    let cancelled = false;
    setDownloadUrl(null);
    setDownloadError(false);
    if (!resume.file_id) {
      setDownloadError(true);
      return;
    }
    api
      .get<DownloadResponse>(`/recruitment/resumes/${resume.id}/download`)
      .then((res) => {
        if (!cancelled) setDownloadUrl(res.url);
      })
      .catch(() => {
        if (!cancelled) setDownloadError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [resume.id, resume.file_id]);

  const isPdf = resume.mime_type === "application/pdf";

  const saveField = useCallback(
    async (key: string, nextValue: unknown) => {
      const nextParsed = { ...parsed, [key]: nextValue };
      setSaving(true);
      try {
        const updated = await api.put<Resume>(
          `/recruitment/resumes/${resume.id}/parsed-data`,
          nextParsed,
        );
        toast.success("Saved");
        onUpdated?.(updated);
      } catch (err) {
        const message =
          err && typeof err === "object" && "message" in err
            ? String((err as { message: unknown }).message)
            : "Failed to save";
        toast.error(message);
      } finally {
        setSaving(false);
      }
    },
    [parsed, resume.id, onUpdated],
  );

  const fieldEntries = useMemo(() => Object.entries(parsed), [parsed]);

  const fileBlock = (
    <Card className="h-full overflow-hidden">
      <CardHeader className="flex flex-row items-center justify-between gap-2 space-y-0">
        <CardTitle className="flex items-center gap-2 text-base">
          <FileText className="size-4" />
          <span className="truncate" title={resume.original_filename}>
            {resume.original_filename}
          </span>
        </CardTitle>
        <div className="flex items-center gap-2">
          <Badge variant="secondary" className="capitalize">
            {resume.parse_status}
          </Badge>
          {downloadUrl && (
            <Button
              variant="ghost"
              size="sm"
              data-testid="resume-download-btn"
              aria-label="Download resume"
              render={
                <a href={downloadUrl} target="_blank" rel="noreferrer">
                  <Download className="size-4" />
                </a>
              }
            />
          )}
        </div>
      </CardHeader>
      <CardContent className="h-[calc(100%-3.5rem)] p-0">
        {downloadError && (
          <div className="flex h-full min-h-[400px] items-center justify-center p-6 text-center text-sm text-muted-foreground">
            Preview is unavailable. {resume.raw_text ? "Raw text below." : "Try downloading the file."}
          </div>
        )}
        {!downloadError && !downloadUrl && (
          <div className="flex h-full min-h-[400px] items-center justify-center p-6">
            <Loader2 className="size-6 animate-spin text-muted-foreground" />
          </div>
        )}
        {!downloadError && downloadUrl && isPdf && (
          <iframe
            src={downloadUrl}
            title={resume.original_filename}
            className="h-full min-h-[600px] w-full border-0"
          />
        )}
        {!downloadError && downloadUrl && !isPdf && (
          <div className="flex h-full min-h-[400px] flex-col items-center justify-center gap-3 p-6 text-sm text-muted-foreground">
            <p>Inline preview not supported for {resume.mime_type}.</p>
            <Button
              variant="outline"
              size="sm"
              render={
                <a href={downloadUrl} target="_blank" rel="noreferrer">
                  Open file
                </a>
              }
            />
            {resume.raw_text && (
              <pre className="max-h-[400px] w-full overflow-auto whitespace-pre-wrap rounded-md bg-muted p-3 text-xs">
                {resume.raw_text}
              </pre>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );

  const fieldsBlock = (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Extracted fields
        </h3>
        {saving && (
          <span className="flex items-center gap-1 text-xs text-muted-foreground">
            <Loader2 className="size-3 animate-spin" />
            Saving
          </span>
        )}
      </div>
      {fieldEntries.length === 0 ? (
        <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
          {resume.parse_status === "pending"
            ? "Resume is being parsed…"
            : "No extracted data yet."}
        </div>
      ) : (
        fieldEntries.map(([key, value]) => (
          <ParsedFieldEditor
            key={key}
            field={key}
            value={value}
            saving={saving}
            onSave={(next) => saveField(key, next)}
          />
        ))
      )}
    </div>
  );

  return (
    <div data-testid="resume-split-view">
      {/* Desktop: 60/40 split */}
      <div className="hidden gap-4 md:grid md:grid-cols-[3fr_2fr]">
        <div className="md:sticky md:top-4 md:h-[calc(100vh-6rem)]">
          {fileBlock}
        </div>
        <div className="space-y-3">{fieldsBlock}</div>
      </div>

      {/* Mobile: tabs */}
      <Tabs defaultValue="file" className="md:hidden">
        <TabsList>
          <TabsTrigger value="file">File</TabsTrigger>
          <TabsTrigger value="extracted">Extracted</TabsTrigger>
        </TabsList>
        <TabsContent value="file" className="space-y-3">
          {fileBlock}
        </TabsContent>
        <TabsContent value="extracted" className="space-y-3">
          {fieldsBlock}
        </TabsContent>
      </Tabs>
    </div>
  );
}
