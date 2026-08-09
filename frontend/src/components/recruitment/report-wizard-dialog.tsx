"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
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
// `credit-cost-badge.tsx` is enterprise-only (excluded from the public
// sync) — the badge is reached through the ee-hooks seam so the
// community build compiles without it.
import { EECreditCostBadge } from "@/lib/ee-hooks";
import type {
  CandidateVacancyEnrichedRow,
  VacancyStage,
} from "@/lib/recruitment-types";
import {
  CANDIDATE_VACANCY_TERMINAL_STATUSES,
  REPORT_SECTION_CODES,
  reportSectionLabel,
  reportStatusLabel,
  type ReportExport,
  type ReportGenerateRequest,
  type ReportGenerateResponse,
  type ReportSectionCode,
  type Vacancy,
} from "@/lib/types";
import { toast } from "sonner";
import { formatDateTime } from "@/lib/date-format";

interface ReportWizardDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  vacancyId: string;
  onCreated?: (exportRow: ReportExport) => void;
}

type WizardStep = "configure" | "submitting" | "result";

/** Include-candidates scope from the HRP-521 mockup. */
type CandidateScope = "all_active" | "finalists" | "custom";

/** Billing action code the Generate button prices. The cost map itself
 *  lives in `ee/billing.py`; recalculating it is HRP-519, not this
 *  dialog's job — we only render the current price. */
const REPORT_ACTION = "recruitment.generate_report";

export function ReportWizardDialog({
  open,
  onOpenChange,
  vacancyId,
  onCreated,
}: ReportWizardDialogProps) {
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const [step, setStep] = useState<WizardStep>("configure");
  const [vacancy, setVacancy] = useState<Vacancy | null>(null);
  const [candidates, setCandidates] = useState<CandidateVacancyEnrichedRow[]>(
    [],
  );
  const [stages, setStages] = useState<VacancyStage[]>([]);
  const [scope, setScope] = useState<CandidateScope>("all_active");
  const [customIds, setCustomIds] = useState<string[]>([]);
  const [sections, setSections] = useState<ReportSectionCode[]>([
    ...REPORT_SECTION_CODES,
  ]);
  // HRP-268 — audience controls Detail-sheet rendering: recruiters see
  // the raw process-findings text, hiring managers see the positive
  // reframe (or a neutral "Recommendation for the next interview").
  const [audience, setAudience] = useState<"recruiter" | "hiring_manager">(
    "recruiter",
  );
  const [latest, setLatest] = useState<ReportExport | null>(null);
  // The poll below runs for up to 5 minutes. Closing the dialog (or
  // unmounting the page) must stop it — otherwise it keeps hitting the
  // API and calls setState / onCreated on a dialog nobody is looking at.
  const pollCancelled = useRef(false);

  useEffect(() => {
    return () => {
      pollCancelled.current = true;
    };
  }, []);

  function handleOpenChange(next: boolean) {
    if (!next) {
      pollCancelled.current = true;
      // Reset wizard state when the dialog closes so reopening starts
      // from a clean slate (otherwise we'd briefly flash the last
      // result). Reset audience back to the safe default — without
      // this a recruiter who generates an HM-audience report once
      // would keep that selection across vacancies and ship sanitised
      // exports when the intent was the recruiter view.
      setStep("configure");
      setLatest(null);
      setAudience("recruiter");
      setScope("all_active");
      setCustomIds([]);
      setSections([...REPORT_SECTION_CODES]);
    }
    onOpenChange(next);
  }

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    api
      .get<Vacancy>(`/recruitment/vacancies/${vacancyId}`)
      .then((row) => {
        if (!cancelled) setVacancy(row);
      })
      .catch(() => {});
    api
      .get<CandidateVacancyEnrichedRow[]>(
        `/recruitment/vacancies/${vacancyId}/candidates/enriched?limit=200`,
      )
      .then((rows) => {
        if (!cancelled) setCandidates(rows);
      })
      .catch(() => {
        if (!cancelled) setCandidates([]);
      });
    api
      .get<VacancyStage[]>(`/recruitment/vacancies/${vacancyId}/funnel-stages`)
      .then((rows) => {
        if (!cancelled) setStages(rows);
      })
      .catch(() => {
        if (!cancelled) setStages([]);
      });
    return () => {
      cancelled = true;
    };
  }, [open, vacancyId]);

  // "Active" is the absence of a terminal outcome, not a stored flag:
  // CandidateVacancy.status starts at "new" and only the funnel's
  // terminal stages drive it to hired / rejected / withdrew. The old
  // `status === "active"` test matched nothing, so every scope counted
  // zero and the custom list rendered empty.
  const activeCandidates = useMemo(
    () =>
      candidates.filter(
        (c) =>
          !CANDIDATE_VACANCY_TERMINAL_STATUSES.has(
            (c.status || "").toLowerCase(),
          ),
      ),
    [candidates],
  );

  // "Finalists" is not a stored flag — it is the tail of the funnel:
  // whoever sits in the last *active* stage (highest sort_order) or has
  // already reached a positive terminal stage (hired). Resolves to an
  // empty set when the vacancy has no stages configured, which is why
  // the radio is disabled at zero. Built on top of `activeCandidates`,
  // so anyone explicitly closed out (status hired/rejected/withdrew) is
  // already gone — the stage is what puts a still-open candidate in the
  // finalist bucket.
  const finalistIds = useMemo(() => {
    const activeStages = stages.filter((s) => s.stage_type === "active");
    const lastActiveOrder =
      activeStages.length > 0
        ? Math.max(...activeStages.map((s) => s.sort_order))
        : null;
    const finalStageIds = new Set(
      stages
        .filter(
          (s) =>
            s.stage_type === "terminal_positive" ||
            (s.stage_type === "active" && s.sort_order === lastActiveOrder),
        )
        .map((s) => s.id),
    );
    return new Set(
      activeCandidates
        .filter((c) => c.stage_id && finalStageIds.has(c.stage_id))
        .map((c) => c.id),
    );
  }, [stages, activeCandidates]);

  const selectedCandidateIds = useMemo(() => {
    if (scope === "all_active") return activeCandidates.map((c) => c.id);
    if (scope === "finalists")
      return activeCandidates
        .filter((c) => finalistIds.has(c.id))
        .map((c) => c.id);
    return customIds;
  }, [scope, activeCandidates, finalistIds, customIds]);

  function toggleSection(code: ReportSectionCode) {
    setSections((prev) =>
      prev.includes(code) ? prev.filter((c) => c !== code) : [...prev, code],
    );
  }

  function toggleCustomCandidate(cvId: string) {
    setCustomIds((prev) =>
      prev.includes(cvId) ? prev.filter((id) => id !== cvId) : [...prev, cvId],
    );
  }

  async function handleGenerate() {
    if (sections.length === 0) {
      toast.error(t("reportWizardSheetRequired"));
      return;
    }
    if (selectedCandidateIds.length === 0) {
      toast.error(t("reportWizardCandidateRequired"));
      return;
    }
    setStep("submitting");
    pollCancelled.current = false;
    try {
      const body: ReportGenerateRequest = {
        sections,
        audience,
        // "All active" omits the whitelist: the worker excludes terminal
        // candidates on its own, and an explicit list would silently cap
        // the report at the picker's 200-row page. Finalists/Custom send
        // the exact ids; an empty list never reaches the API (the server
        // would 400 on it).
        ...(scope === "all_active"
          ? {}
          : { candidate_vacancy_ids: selectedCandidateIds }),
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
      // The dialog was closed (or unmounted) while we were polling —
      // the export keeps generating and the Reports list will show it,
      // but this instance must not touch state or fire onCreated.
      if (pollCancelled.current) return;
      setLatest(exportRow);
      setStep("result");
      onCreated?.(exportRow);
    } catch (err) {
      if (pollCancelled.current) return;
      toast.error(
        err instanceof Error ? err.message : t("reportWizardStartFailed"),
      );
      setStep("configure");
    }
  }

  async function pollExport(exportId: string): Promise<ReportExport> {
    const deadline = Date.now() + 5 * 60_000;
    let last: ReportExport | null = null;
    while (Date.now() < deadline && !pollCancelled.current) {
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
    throw new Error(t("reportWizardNotReady"));
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent
        className="max-h-[85vh] overflow-y-auto sm:max-w-lg"
        data-testid="recruitment-report-wizard"
      >
        <DialogHeader>
          <DialogTitle>{t("reportWizardTitle")}</DialogTitle>
          <DialogDescription>{t("reportWizardDescription")}</DialogDescription>
        </DialogHeader>

        {step !== "result" && (
          <div className="space-y-5">
            <p
              className="text-sm"
              data-testid="recruitment-report-vacancy-title"
            >
              <span className="text-muted-foreground">
                {t("reportWizardVacancyLabel")}
              </span>{" "}
              <span className="font-medium">{vacancy?.title || "—"}</span>
            </p>

            <div className="space-y-2">
              <Label>{t("reportWizardScopeLabel")}</Label>
              <div className="space-y-2" data-testid="recruitment-report-scope">
                <label className="flex items-start gap-2 rounded-md border border-border bg-card p-2 text-sm">
                  <input
                    type="radio"
                    name="report-scope"
                    value="all_active"
                    checked={scope === "all_active"}
                    disabled={activeCandidates.length === 0}
                    onChange={() => setScope("all_active")}
                    data-testid="recruitment-report-scope-all"
                  />
                  <span>
                    {t("reportWizardScopeAllActive", {
                      count: String(activeCandidates.length),
                    })}
                  </span>
                </label>
                <label className="flex items-start gap-2 rounded-md border border-border bg-card p-2 text-sm">
                  <input
                    type="radio"
                    name="report-scope"
                    value="finalists"
                    checked={scope === "finalists"}
                    disabled={finalistIds.size === 0}
                    onChange={() => setScope("finalists")}
                    data-testid="recruitment-report-scope-finalists"
                  />
                  <span>
                    {t("reportWizardScopeFinalists", {
                      count: String(finalistIds.size),
                    })}
                  </span>
                </label>
                <label className="flex items-start gap-2 rounded-md border border-border bg-card p-2 text-sm">
                  <input
                    type="radio"
                    name="report-scope"
                    value="custom"
                    checked={scope === "custom"}
                    onChange={() => setScope("custom")}
                    data-testid="recruitment-report-scope-custom"
                  />
                  <span>{t("reportWizardScopeCustom")}</span>
                </label>
              </div>

              {scope === "custom" && (
                <div
                  className="max-h-48 space-y-1 overflow-y-auto rounded-md border border-border p-2"
                  data-testid="recruitment-report-custom-list"
                >
                  {activeCandidates.length === 0 && (
                    <p className="p-1 text-sm text-muted-foreground">
                      {t("reportWizardNoCandidates")}
                    </p>
                  )}
                  {activeCandidates.map((c) => (
                    <label
                      key={c.id}
                      className="flex items-center gap-2 p-1 text-sm"
                    >
                      <Checkbox
                        checked={customIds.includes(c.id)}
                        onCheckedChange={() => toggleCustomCandidate(c.id)}
                        data-testid={`recruitment-report-custom-candidate-${c.id}`}
                      />
                      <span>{c.candidate_name}</span>
                      {c.stage?.name && (
                        <span className="text-xs text-muted-foreground">
                          {c.stage.name}
                        </span>
                      )}
                    </label>
                  ))}
                </div>
              )}
            </div>

            <div className="space-y-2">
              <Label>{t("reportWizardSheetsLabel")}</Label>
              <div
                className="space-y-2"
                data-testid="recruitment-report-sections"
              >
                {REPORT_SECTION_CODES.map((code, idx) => {
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
                      <span>
                        {idx + 1}. {reportSectionLabel(t, code)}
                      </span>
                    </label>
                  );
                })}
              </div>
            </div>

            <div className="space-y-2">
              <Label>{t("reportWizardAudienceLabel")}</Label>
              <div
                className="space-y-2"
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
                  <span>{t("reportWizardAudienceRecruiter")}</span>
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
                  <span>{t("reportWizardAudienceHiringManager")}</span>
                </label>
              </div>
            </div>
          </div>
        )}

        {step === "submitting" && (
          <div className="flex items-center gap-2 rounded-md border border-border bg-muted/40 p-3 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" />
            {t("reportWizardGeneratingXlsx")}
          </div>
        )}

        {step === "result" && latest && (
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <Badge
                variant={
                  latest.status === "completed" ? "default" : "destructive"
                }
              >
                {reportStatusLabel(t, latest.status)}
              </Badge>
              <span className="text-sm text-muted-foreground">
                {latest.completed_at
                  ? t("reportWizardReadyAt", {
                      date: formatDateTime(latest.completed_at),
                    })
                  : t("reportWizardInProgress")}
              </span>
            </div>
            {latest.status === "completed" && latest.download_url && (
              <Button
                data-testid="recruitment-report-btn-download"
                render={
                  <a href={latest.download_url} target="_blank" rel="noreferrer">
                    <FileSpreadsheet className="size-4" />{" "}
                    {t("reportDownloadXlsx")}
                  </a>
                }
              />
            )}
            {latest.status === "failed" && (
              <p className="text-sm text-red-600">
                {latest.error || t("reportWizardGenerationFailed")}
              </p>
            )}
            {(latest.status === "pending" ||
              latest.status === "processing") && (
              <p className="text-sm text-muted-foreground">
                {t("reportWizardStillInProgress")}
              </p>
            )}
          </div>
        )}

        <DialogFooter>
          {step === "configure" && (
            <>
              <Button variant="outline" onClick={() => handleOpenChange(false)}>
                {tc("cancel")}
              </Button>
              <Button
                onClick={handleGenerate}
                disabled={selectedCandidateIds.length === 0}
                data-testid="recruitment-report-btn-submit"
              >
                {t("vacancyCompetencesGenerate")}
                <EECreditCostBadge action={REPORT_ACTION} />
              </Button>
            </>
          )}
          {step === "submitting" && (
            <Button disabled>
              <Loader2 className="size-4 animate-spin" />
              {t("reportWizardGenerating")}
            </Button>
          )}
          {step === "result" && (
            <Button onClick={() => handleOpenChange(false)}>
              {t("reportWizardClose")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
