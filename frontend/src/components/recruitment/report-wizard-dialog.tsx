"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Loader2, FileSpreadsheet } from "lucide-react";
import { api } from "@/lib/api";
import {
  REPORT_SECTION_CODES,
  REPORT_SECTION_LABELS,
  type ReportExport,
  type ReportGenerateRequest,
  type ReportGenerateResponse,
  type ReportSectionCode,
  type ReportTemplate,
} from "@/lib/types";
import { toast } from "sonner";
import { formatDateTime } from "@/lib/date-format";

interface ReportWizardDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  vacancyId: string;
  onCreated?: (exportRow: ReportExport) => void;
}

const DEFAULT_SECTIONS: ReportSectionCode[] = [
  "vacancy_summary",
  "competence_profile",
  "candidates_summary",
  "comparison_grid",
  "interview_analysis",
];

type WizardStep = "configure" | "submitting" | "result";

export function ReportWizardDialog({
  open,
  onOpenChange,
  vacancyId,
  onCreated,
}: ReportWizardDialogProps) {
  const [step, setStep] = useState<WizardStep>("configure");
  const [templates, setTemplates] = useState<ReportTemplate[]>([]);
  const [templateId, setTemplateId] = useState<string>("");
  const [sections, setSections] = useState<ReportSectionCode[]>(
    DEFAULT_SECTIONS,
  );
  // HRP-268 — audience controls Detail-sheet rendering: recruiters see
  // the raw process-findings text, hiring managers see the positive
  // reframe (or a neutral "Recommendation for the next interview").
  const [audience, setAudience] = useState<"recruiter" | "hiring_manager">(
    "recruiter",
  );
  const [latest, setLatest] = useState<ReportExport | null>(null);

  function handleOpenChange(next: boolean) {
    if (!next) {
      // Reset wizard state when the dialog closes so reopening starts
      // from a clean slate (otherwise we'd briefly flash the last
      // result). Reset audience back to the safe default — without
      // this a recruiter who generates an HM-audience report once
      // would keep that selection across vacancies and ship sanitised
      // exports when the intent was the recruiter view.
      setStep("configure");
      setLatest(null);
      setAudience("recruiter");
    }
    onOpenChange(next);
  }

  useEffect(() => {
    if (!open) return;
    api
      .get<ReportTemplate[]>("/recruitment/report-templates")
      .then((rows) => {
        const active = rows.filter((r) => r.is_active);
        setTemplates(active);
        const def = active.find((r) => r.is_default) || active[0];
        if (def) {
          setTemplateId(def.id);
          if (def.sections.length > 0) setSections(def.sections);
        } else {
          setTemplateId("");
          setSections(DEFAULT_SECTIONS);
        }
      })
      .catch(() => setTemplates([]));
  }, [open]);

  const selectedTemplate = useMemo(
    () => templates.find((t) => t.id === templateId) || null,
    [templates, templateId],
  );

  function toggleSection(code: ReportSectionCode) {
    setSections((prev) =>
      prev.includes(code) ? prev.filter((c) => c !== code) : [...prev, code],
    );
  }

  async function handleGenerate() {
    if (sections.length === 0) {
      toast.error("Select at least one section");
      return;
    }
    setStep("submitting");
    try {
      const body: ReportGenerateRequest = {
        template_id: templateId || null,
        sections,
        audience,
      };
      const created = await api.post<ReportGenerateResponse>(
        `/recruitment/vacancies/${vacancyId}/reports`,
        body,
      );
      // Polling for up to 5 minutes — large vacancies with many
      // candidates and interviews can legitimately take longer than the
      // single-second cases tests cover. If we time out, surface the
      // last-known row instead of throwing the export id away — the
      // user can keep an eye on the Reports list once they close.
      const exportRow = await pollExport(created.export_id);
      setLatest(exportRow);
      setStep("result");
      onCreated?.(exportRow);
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to start report",
      );
      setStep("configure");
    }
  }

  async function pollExport(exportId: string): Promise<ReportExport> {
    const deadline = Date.now() + 5 * 60_000;
    let last: ReportExport | null = null;
    while (Date.now() < deadline) {
      const row = await api.get<ReportExport>(
        `/recruitment/reports/${exportId}`,
      );
      last = row;
      if (row.status === "completed" || row.status === "failed") return row;
      await new Promise((res) => setTimeout(res, 2000));
    }
    // Soft timeout: hand back whatever the latest snapshot is and let
    // the result step explain the state. Reports list keeps polling.
    if (last) return last;
    throw new Error(
      "Report is not ready yet. Check status in the Reports tab.",
    );
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent
        className="sm:max-w-lg"
        data-testid="recruitment-report-wizard"
      >
        <DialogHeader>
          <DialogTitle>Generate report</DialogTitle>
          <DialogDescription>
            XLSX with aggregated vacancy data. Pick a template or check the
            sections you need manually.
          </DialogDescription>
        </DialogHeader>

        {step !== "result" && (
          <div className="space-y-4">
            <div className="space-y-1">
              <Label htmlFor="rep-tpl">Template</Label>
              <select
                id="rep-tpl"
                className="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm"
                data-testid="recruitment-report-input-template"
                value={templateId}
                onChange={(e) => {
                  const id = e.target.value;
                  setTemplateId(id);
                  const tpl = templates.find((t) => t.id === id);
                  if (tpl && tpl.sections.length > 0) {
                    setSections(tpl.sections);
                  }
                }}
              >
                <option value="">No template (custom)</option>
                {templates.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                    {t.is_default ? " — default" : ""}
                  </option>
                ))}
              </select>
              {selectedTemplate && (
                <p className="text-xs text-muted-foreground">
                  Template contains {selectedTemplate.sections.length} sections.
                </p>
              )}
            </div>

            <div className="space-y-2">
              <Label>Sections</Label>
              <div
                className="grid grid-cols-1 gap-2 sm:grid-cols-2"
                data-testid="recruitment-report-sections"
              >
                {REPORT_SECTION_CODES.map((code) => {
                  const checked = sections.includes(code);
                  return (
                    <label
                      key={code}
                      className="flex items-start gap-2 rounded-md border border-border bg-card p-2 text-sm"
                    >
                      <Checkbox
                        checked={checked}
                        onCheckedChange={() => toggleSection(code)}
                        data-testid={`recruitment-report-section-${code}`}
                      />
                      <span>{REPORT_SECTION_LABELS[code]}</span>
                    </label>
                  );
                })}
              </div>
            </div>

            <div className="space-y-2">
              <Label>Audience</Label>
              <div
                className="grid grid-cols-1 gap-2 sm:grid-cols-2"
                data-testid="recruitment-report-audience"
              >
                <label className="flex items-start gap-2 rounded-md border border-border bg-card p-2 text-sm">
                  <input
                    type="radio"
                    name="report-audience"
                    value="recruiter"
                    checked={audience === "recruiter"}
                    onChange={() => setAudience("recruiter")}
                    data-testid="recruitment-report-audience-recruiter"
                  />
                  <span>
                    Recruiter / HR — full process findings on the Detail
                    sheet.
                  </span>
                </label>
                <label className="flex items-start gap-2 rounded-md border border-border bg-card p-2 text-sm">
                  <input
                    type="radio"
                    name="report-audience"
                    value="hiring_manager"
                    checked={audience === "hiring_manager"}
                    onChange={() => setAudience("hiring_manager")}
                    data-testid="recruitment-report-audience-hiring-manager"
                  />
                  <span>
                    Hiring Manager — process findings are replaced by a
                    positive reframe for the next interview.
                  </span>
                </label>
              </div>
            </div>
          </div>
        )}

        {step === "submitting" && (
          <div className="flex items-center gap-2 rounded-md border border-border bg-muted/40 p-3 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" />
            Generating XLSX, usually 5–15 seconds…
          </div>
        )}

        {step === "result" && latest && (
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <Badge
                variant={latest.status === "completed" ? "default" : "destructive"}
              >
                {latest.status}
              </Badge>
              <span className="text-sm text-muted-foreground">
                {latest.completed_at
                  ? `Ready ${formatDateTime(latest.completed_at)}`
                  : "In progress"}
              </span>
            </div>
            {latest.status === "completed" && latest.download_url && (
              <Button
                data-testid="recruitment-report-btn-download"
                render={
                  <a
                    href={latest.download_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <FileSpreadsheet className="size-4" /> Download XLSX
                  </a>
                }
              />
            )}
            {latest.status === "failed" && (
              <p className="text-sm text-red-600">
                {latest.error || "Generation failed — please try again."}
              </p>
            )}
            {(latest.status === "pending" ||
              latest.status === "processing") && (
              <p className="text-sm text-muted-foreground">
                Generation is still in progress. Close this dialog and follow
                the status in the Reports tab.
              </p>
            )}
          </div>
        )}

        <DialogFooter>
          {step === "configure" && (
            <>
              <Button
                variant="outline"
                onClick={() => handleOpenChange(false)}
              >
                Cancel
              </Button>
              <Button
                onClick={handleGenerate}
                data-testid="recruitment-report-btn-submit"
              >
                Generate
              </Button>
            </>
          )}
          {step === "submitting" && (
            <Button disabled>
              <Loader2 className="size-4 animate-spin" />
              Generating…
            </Button>
          )}
          {step === "result" && (
            <Button onClick={() => handleOpenChange(false)}>
              Close
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
