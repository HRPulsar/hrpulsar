"use client";

// HRP-204 — AI Insights section on the candidate card.
//
// One section per (candidate, vacancy) pair. The vacancy selector at
// the top picks which application's analysis to display; the
// split-button kicks off resume-only (always available when parsed
// resume + profile exist) or a top-up to full (when the prior
// resume-only run is still inside the 30-day window and a
// transcribed interview is available).

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  History,
  Loader2,
  RefreshCw,
  Sparkles,
  X,
} from "lucide-react";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { toast } from "sonner";
import { useLocale, useTranslations } from "next-intl";
import { useAuth } from "@/context/auth-context";
import { ApiError, api } from "@/lib/api";
import {
  AI_ANALYSIS_PRICING,
  AI_ANALYSIS_STAGES,
  aiAnalysisStageLabel,
  extractResumeExcerpts,
} from "@/lib/recruitment-types";
import { ALERT_TONE, BADGE_COLOR } from "@/lib/badge-tones";
import type {
  AiAnalysisRun,
  AiAnalysisStage,
  CandidateVacancyApplication,
  ResumeExcerpt,
  ResumeExcerptSection,
  TopupEligibility,
} from "@/lib/recruitment-types";
import { dispatchResumeExcerptFocus } from "@/lib/resume-excerpt-focus";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

type ModeOption = "resume_only" | "topup_to_full" | "full";

interface Props {
  candidateId: string;
  vacancyApplications: CandidateVacancyApplication[];
  /** HRP-361/366: the vacancy the user navigated from — it becomes the
   * default selection instead of the most recent application. */
  initialVacancyId?: string;
}

export function AiInsightsSection({
  candidateId,
  vacancyApplications,
  initialVacancyId,
}: Props) {
  const t = useTranslations("recruitment");
  // Credit pricing copy is SaaS-only; on-prem (community) builds have no
  // billing, so they must not render dead "N cr" labels. See project-review #24.
  const { user } = useAuth();
  const showCredits = user?.deployment_mode === "saas";
  const [selectedCvId, setSelectedCvId] = useState<string | null>(
    () =>
      vacancyApplications.find((a) => a.vacancy_id === initialVacancyId)
        ?.cv_id ??
      vacancyApplications[0]?.cv_id ??
      null,
  );
  const [runs, setRuns] = useState<AiAnalysisRun[]>([]);
  const [eligibility, setEligibility] = useState<TopupEligibility | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  // HRP-269 (review): React state updates are async, so two rapid
  // clicks both see ``busy === false`` and both fire the POST. A
  // synchronous ref latch closes the window — the second click is
  // discarded before it can spend a second 20/40 credits.
  const busyLatchRef = useRef(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  // HRP-270: cancel-flow state + confirm modal.
  const [cancelling, setCancelling] = useState(false);
  const [confirmCancelOpen, setConfirmCancelOpen] = useState(false);

  useEffect(() => {
    if (
      selectedCvId &&
      !vacancyApplications.some((a) => a.cv_id === selectedCvId)
    ) {
      setSelectedCvId(vacancyApplications[0]?.cv_id ?? null);
    } else if (!selectedCvId && vacancyApplications.length > 0) {
      setSelectedCvId(vacancyApplications[0].cv_id);
    }
  }, [vacancyApplications, selectedCvId]);

  const refresh = useCallback(async () => {
    if (!selectedCvId) {
      setRuns([]);
      setEligibility(null);
      return;
    }
    setLoading(true);
    try {
      const [runsRes, eligRes] = await Promise.all([
        api.get<AiAnalysisRun[]>(
          `/recruitment/candidate-vacancies/${selectedCvId}/ai-analyses`,
        ),
        api.get<TopupEligibility>(
          `/recruitment/candidate-vacancies/${selectedCvId}/ai-analyses/topup-eligibility`,
        ),
      ]);
      setRuns(runsRes);
      setEligibility(eligRes);
    } catch (err) {
      toast.error(
        err instanceof ApiError ? err.message : t("aiInsightsLoadFailed"),
      );
    } finally {
      setLoading(false);
    }
  }, [selectedCvId, t]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const activeRun = useMemo(
    () => runs.find((r) => r.archived_at === null && r.status === "completed"),
    [runs],
  );
  const inFlightRun = useMemo(
    () =>
      runs.find(
        (r) => r.status === "pending" || r.status === "processing",
      ),
    [runs],
  );

  const trigger = useCallback(
    async (mode: ModeOption) => {
      if (!selectedCvId || busyLatchRef.current) return;
      // HRP-269: ``full`` mode needs the transcribed interview id;
      // ``resume_only`` and ``topup_to_full`` are derived server-side
      // from the candidate-vacancy alone.
      const interviewId =
        mode === "full" ? (eligibility?.transcribed_interview_id ?? null) : null;
      if (mode === "full" && !interviewId) return;
      busyLatchRef.current = true;
      setBusy(true);
      try {
        const res = await api.post<{
          status?: "queued" | "completed";
          mode?: string;
        }>(
          `/recruitment/candidate-vacancies/${selectedCvId}/ai-analyses`,
          mode === "full"
            ? { mode, interview_id: interviewId }
            : { mode },
        );
        // HRP-269 (review): mode='full' cache hit returns
        // ``status='completed'`` synchronously without billing or
        // creating an AIAnalysisRun row. A "queued (40 cr)" toast
        // would lie in that case — branch on the response.
        const cached = mode === "full" && res?.status === "completed";
        const queuedMessage = cached
          ? showCredits
            ? t("aiInsightsCacheCredits")
            : t("aiInsightsCache")
          : mode === "resume_only"
            ? showCredits
              ? t("aiInsightsQueuedResumeOnlyCr", {
                  cost: AI_ANALYSIS_PRICING.resume_only,
                })
              : t("aiInsightsQueuedResumeOnly")
            : mode === "topup_to_full"
              ? showCredits
                ? t("aiInsightsQueuedTopupCr", {
                    cost: AI_ANALYSIS_PRICING.topup_to_full,
                  })
                : t("aiInsightsQueuedTopup")
              : showCredits
                ? t("aiInsightsQueuedFullCr", {
                    cost: AI_ANALYSIS_PRICING.full,
                  })
                : t("aiInsightsQueuedFull");
        toast.success(queuedMessage);
        await refresh();
      } catch (err) {
        toast.error(
          err instanceof ApiError ? err.message : t("aiInsightsStartFailed"),
        );
      } finally {
        busyLatchRef.current = false;
        setBusy(false);
      }
    },
    [
      eligibility?.transcribed_interview_id,
      refresh,
      selectedCvId,
      showCredits,
      t,
    ],
  );

  // HRP-270: while a run is in flight, poll the eligibility +
  // run list every 3 s so the InFlightCard stepper ticks forward
  // without forcing the recruiter to hit Refresh.
  const inFlightRunId = inFlightRun?.id ?? null;
  useEffect(() => {
    if (!inFlightRunId) return;
    const handle = window.setInterval(() => {
      void refresh();
    }, 3000);
    return () => window.clearInterval(handle);
  }, [inFlightRunId, refresh]);

  const handleCancel = useCallback(async () => {
    if (!inFlightRun || cancelling) return;
    setCancelling(true);
    try {
      const res = await api.post<{
        status: string;
        refunded: number;
        refund_eligible: boolean;
      }>(`/recruitment/ai-analyses/${inFlightRun.id}/cancel`, {});
      toast.success(
        !showCredits
          ? t("aiInsightsCancelled")
          : res.refunded > 0
            ? t("aiInsightsCancelledRefunded", { credits: res.refunded })
            : t("aiInsightsCancelledNoRefund"),
      );
      setConfirmCancelOpen(false);
      await refresh();
    } catch (err) {
      toast.error(
        err instanceof ApiError ? err.message : t("aiInsightsCancelFailed"),
      );
    } finally {
      setCancelling(false);
    }
  }, [cancelling, inFlightRun, refresh, showCredits, t]);

  if (vacancyApplications.length === 0) {
    return null;
  }

  return (
    <Card data-testid="candidate-section-ai-insights">
      <CardHeader className="flex flex-row items-center justify-between gap-3 space-y-0">
        <div className="flex items-center gap-2">
          <Sparkles className="size-4 text-amber-600" />
          <CardTitle className="text-base">{t("aiInsightsTitle")}</CardTitle>
        </div>
        <div className="flex items-center gap-2">
          {vacancyApplications.length > 1 && (
            <select
              value={selectedCvId ?? ""}
              onChange={(e) => setSelectedCvId(e.target.value || null)}
              className="h-8 rounded-md border bg-background px-2 text-xs"
              data-testid="candidate-section-ai-insights-vacancy-selector"
            >
              {vacancyApplications.map((app) => (
                <option key={app.cv_id} value={app.cv_id}>
                  {app.vacancy_title ?? "—"}
                </option>
              ))}
            </select>
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setHistoryOpen(true)}
            disabled={runs.length === 0}
            aria-label={t("aiInsightsHistoryAria")}
            data-testid="ai-analysis-history-btn"
          >
            <History className="size-4" aria-hidden />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => void refresh()}
            disabled={loading}
            aria-label={t("actionRefresh")}
          >
            <RefreshCw
              className={cn("size-4", loading && "animate-spin")}
              aria-hidden
            />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {inFlightRun ? (
          <InFlightCard
            run={inFlightRun}
            onCancel={() => setConfirmCancelOpen(true)}
            cancelling={cancelling}
          />
        ) : activeRun ? (
          <ActiveRunCard
            run={activeRun}
            candidateId={candidateId}
            eligibility={eligibility}
            showCredits={showCredits}
            onTopup={() => void trigger("topup_to_full")}
            onReanalyze={() => void trigger("resume_only")}
            busy={busy}
            inFlight={!!inFlightRun}
          />
        ) : (
          <EmptyState />
        )}

        <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-3">
          <p className="text-xs text-muted-foreground">
            {activeRun
              ? t("aiInsightsFooterActive")
              : showCredits
                ? t("aiInsightsFooterCredits", {
                    resumeOnly: AI_ANALYSIS_PRICING.resume_only,
                    full: AI_ANALYSIS_PRICING.full,
                  })
                : t("aiInsightsFooterNoCredits")}
          </p>
          <AnalyzeSplitButton
            disabled={!selectedCvId || busy || !!inFlightRun}
            busy={busy}
            showCredits={showCredits}
            hasTranscribedInterview={
              !!eligibility?.transcribed_interview_id
            }
            topupEligible={!!eligibility?.eligible}
            onResumeOnly={() => void trigger("resume_only")}
            onFullMode={() => void trigger("full")}
          />
        </div>
      </CardContent>

      <HistoryDialog
        open={historyOpen}
        onOpenChange={setHistoryOpen}
        runs={runs}
      />

      <Dialog
        open={confirmCancelOpen}
        onOpenChange={(next) => {
          if (cancelling) return;
          setConfirmCancelOpen(next);
        }}
      >
        <DialogContent
          className="max-w-md"
          data-testid="ai-analysis-cancel-modal"
        >
          <DialogTitle className="text-base font-semibold">
            {t("aiInsightsCancelTitle")}
          </DialogTitle>
          <DialogDescription className="text-sm text-muted-foreground">
            {showCredits
              ? t("aiInsightsCancelDescriptionCredits")
              : t("aiInsightsCancelDescription")}
          </DialogDescription>
          <div className="mt-4 flex justify-end gap-2">
            <DialogClose
              render={
                <Button
                  variant="outline"
                  size="sm"
                  disabled={cancelling}
                  data-testid="ai-analysis-cancel-modal-keep"
                >
                  {t("aiInsightsKeepRunning")}
                </Button>
              }
            />

            <Button
              variant="destructive"
              size="sm"
              onClick={() => void handleCancel()}
              disabled={cancelling}
              data-testid="ai-analysis-cancel-modal-confirm"
            >
              {cancelling ? (
                <Loader2 className="size-3.5 animate-spin" aria-hidden />
              ) : null}
              <span className="ml-1">{t("aiInsightsCancelAction")}</span>
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function EmptyState() {
  const t = useTranslations("recruitment");
  return (
    <div
      className="rounded-md border border-dashed bg-muted/40 p-4 text-center text-sm text-muted-foreground"
      data-testid="candidate-section-ai-insights-empty-state"
    >
      <p className="font-medium text-foreground">
        {t("aiInsightsEmptyTitle")}
      </p>
      <p className="mt-1">
        {t.rich("aiInsightsEmptyHint", {
          strong: (chunks) => <span className="font-medium">{chunks}</span>,
        })}
      </p>
    </div>
  );
}

function InFlightCard({
  run,
  onCancel,
  cancelling,
}: {
  run: AiAnalysisRun;
  onCancel: () => void;
  cancelling: boolean;
}) {
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const locale = useLocale();
  // HRP-270: render all six pipeline stages so a recruiter sees which
  // ones the resume-only mode skips and how far the worker has got.
  // Stages are derived from a static list to match the backend tax-
  // onomy in ``app.modules.recruitment.ai_analysis_stages``.
  const SKIPPED_FOR_RESUME_ONLY: ReadonlySet<AiAnalysisStage> = new Set([
    "process_findings",
    "citations",
  ]);
  const activeIdx = run.current_stage
    ? AI_ANALYSIS_STAGES.indexOf(run.current_stage)
    : -1;
  return (
    <div
      className={`space-y-3 rounded-md p-3 text-sm ${ALERT_TONE.amber}`}
      data-testid="ai-analysis-inflight-card"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <Loader2
            className="size-4 animate-spin text-amber-700 dark:text-amber-300"
            aria-hidden
          />
          <div>
            <p className="font-medium">
              {run.mode === "resume_only"
                ? t("aiInsightsInProgressResumeOnly")
                : t("aiInsightsInProgressFull")}
            </p>
            <p className="text-xs text-amber-800">
              {t("aiInsightsStarted", {
                date: new Date(run.created_at).toLocaleString(locale),
              })}
            </p>
          </div>
        </div>
        <Button
          size="sm"
          variant="outline"
          onClick={onCancel}
          disabled={cancelling}
          data-testid="ai-analysis-cancel-btn"
        >
          {cancelling ? (
            <Loader2 className="size-3.5 animate-spin" aria-hidden />
          ) : (
            <X className="size-3.5" aria-hidden />
          )}
          <span className="ml-1">{tc("cancel")}</span>
        </Button>
      </div>
      <ol
        className="grid grid-cols-2 gap-1.5 text-xs sm:grid-cols-3"
        data-testid="ai-analysis-stages"
      >
        {AI_ANALYSIS_STAGES.map((s, i) => {
          const skipped =
            run.mode === "resume_only" && SKIPPED_FOR_RESUME_ONLY.has(s);
          const active = !skipped && i === activeIdx;
          const done = !skipped && activeIdx > -1 && i < activeIdx;
          return (
            <li
              key={s}
              className={cn(
                "flex items-center gap-1.5 rounded border px-2 py-1",
                skipped &&
                  "border-muted bg-muted/40 text-muted-foreground line-through",
                active && "border-amber-400 bg-amber-100/60 font-medium",
                done && "border-emerald-300 bg-emerald-50 text-emerald-900",
                !skipped &&
                  !active &&
                  !done &&
                  "border-amber-200 bg-white/60 text-amber-900",
              )}
              data-testid={`ai-analysis-stage-${s}`}
              data-state={
                skipped
                  ? "skipped"
                  : active
                    ? "active"
                    : done
                      ? "done"
                      : "pending"
              }
              title={
                skipped
                  ? s === "citations"
                    ? t("aiInsightsSkippedNoTranscript")
                    : t("aiInsightsSkippedNoInterview")
                  : aiAnalysisStageLabel(t, s)
              }
            >
              {skipped ? (
                <span aria-hidden>·</span>
              ) : done ? (
                <CheckCircle2
                  className="size-3 text-emerald-700"
                  aria-hidden
                />
              ) : active ? (
                <Loader2
                  className="size-3 animate-spin text-amber-700"
                  aria-hidden
                />
              ) : (
                <span
                  className="block size-1.5 rounded-full bg-amber-300"
                  aria-hidden
                />
              )}
              <span>{aiAnalysisStageLabel(t, s)}</span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function ActiveRunCard({
  run,
  candidateId,
  eligibility,
  showCredits,
  onTopup,
  onReanalyze,
  busy,
  inFlight,
}: {
  run: AiAnalysisRun;
  candidateId: string;
  eligibility: TopupEligibility | null;
  showCredits: boolean;
  onTopup: () => void;
  onReanalyze: () => void;
  busy: boolean;
  inFlight: boolean;
}) {
  const t = useTranslations("recruitment");
  const locale = useLocale();
  const isResumeOnly = run.mode === "resume_only";
  // HRP-271: resume-only runs ship per-competence ``resume_excerpts``
  // pre-flattened by the backend. Each renders as a click-to-locate
  // chip that focuses the matching block in ParsedResumeEditor.
  const excerpts = useMemo(() => extractResumeExcerpts(run), [run]);
  // HRP-272: backend flips ``resume_outdated`` on when the candidate
  // uploaded a fresh resume after this run was enqueued. The banner is
  // resume-only-only — full runs and legacy rows without a stamped
  // snapshot hash keep the flag at False.
  const showOutdatedBanner = isResumeOnly && run.resume_outdated;
  return (
    <div className="space-y-3">
      {showOutdatedBanner && (
        <OutdatedResumeBanner
          onReanalyze={onReanalyze}
          showCredits={showCredits}
          // Review #2 (HRP-272): mirror AnalyzeSplitButton's
          // ``disabled={busy || !!inFlight}`` so a future refactor
          // that decouples ``setBusy(false)`` from the post-trigger
          // refresh cannot re-open a double-click 409 race.
          busy={busy || inFlight}
        />
      )}
      <div className="flex flex-wrap items-center gap-2">
        <VerdictPill
          verdict={run.verdict ?? "needs_check"}
          score={run.ai_score}
        />
        <ModeBadge mode={run.mode} />
        {run.data_completeness && (
          <Badge variant="outline" className="text-[10px]">
            {t("aiInsightsDataCompleteness", {
              value: run.data_completeness,
            })}
          </Badge>
        )}
        <span className="ml-auto text-xs text-muted-foreground">
          {new Date(run.created_at).toLocaleDateString(locale)}
        </span>
      </div>
      {run.verdict_summary && (
        <p className="text-sm text-foreground/90">{run.verdict_summary}</p>
      )}
      <dl className="grid gap-2 text-xs sm:grid-cols-2">
        {run.key_strength && (
          <div>
            <dt className="font-medium">{t("aiInsightsKeyStrength")}</dt>
            <dd className="text-muted-foreground">{run.key_strength}</dd>
          </div>
        )}
        {run.key_risk && (
          <div>
            <dt className="font-medium">{t("aiInsightsKeyRisk")}</dt>
            <dd className="text-muted-foreground">{run.key_risk}</dd>
          </div>
        )}
        {run.risk_mitigation && (
          <div className="sm:col-span-2">
            <dt className="font-medium">{t("aiInsightsMitigation")}</dt>
            <dd className="text-muted-foreground">{run.risk_mitigation}</dd>
          </div>
        )}
        {run.recommendation_for_next_step && (
          <div className="sm:col-span-2">
            <dt className="font-medium">{t("aiInsightsNextStep")}</dt>
            <dd className="text-muted-foreground capitalize">
              {run.recommendation_for_next_step.replaceAll("_", " ")}
            </dd>
          </div>
        )}
      </dl>

      {isResumeOnly && excerpts.length > 0 && (
        <ResumeExcerptList candidateId={candidateId} excerpts={excerpts} />
      )}

      {isResumeOnly && eligibility && (
        <TopupCallout
          eligibility={eligibility}
          onTopup={onTopup}
          showCredits={showCredits}
          busy={busy}
        />
      )}
    </div>
  );
}

// HRP-272 — "Resume updated — re-analyze" banner. Shown above the
// active resume-only run when the backend has flagged
// ``run.resume_outdated`` because the candidate uploaded a fresh CV
// after the run was enqueued. Re-analyze re-uses the same billable
// entry point as the primary analyze split-button — the worker
// archives the prior active run on success.
function OutdatedResumeBanner({
  onReanalyze,
  showCredits,
  busy,
}: {
  onReanalyze: () => void;
  showCredits: boolean;
  busy: boolean;
}) {
  const t = useTranslations("recruitment");
  return (
    <div
      className={`flex flex-wrap items-center justify-between gap-3 rounded-md p-3 text-sm ${ALERT_TONE.amber}`}
      data-testid="ai-analysis-outdated-banner"
    >
      <div className="flex items-start gap-2">
        <AlertCircle
          className="size-4 shrink-0 text-amber-700 dark:text-amber-300"
          aria-hidden
        />
        <p>
          {t.rich("aiInsightsOutdatedBanner", {
            strong: (chunks) => <span className="font-medium">{chunks}</span>,
          })}
        </p>
      </div>
      <Button
        size="sm"
        onClick={onReanalyze}
        disabled={busy}
        data-testid="ai-analysis-reanalyze-btn"
      >
        {busy ? (
          <Loader2 className="size-3.5 animate-spin" aria-hidden />
        ) : (
          <RefreshCw className="size-3.5" aria-hidden />
        )}
        <span className="ml-1">
          {showCredits
            ? t("aiInsightsReanalyzeCr", {
                cost: AI_ANALYSIS_PRICING.resume_only,
              })
            : t("aiInsightsReanalyze")}
        </span>
      </Button>
    </div>
  );
}

// HRP-271 — resume_excerpts grouped by section. Each excerpt is a
// button: click → dispatch the focus event that ParsedResumeEditor
// listens for (auto-expand + scroll + 2 s ring highlight).
//
// HRP-476: the map owns the section → i18n key relation; the wording
// lives in the `recruitment` namespace and is resolved by the component.
const SECTION_LABEL_KEYS: Record<ResumeExcerptSection, string> = {
  experience: "aiInsightsSectionExperience",
  education: "aiInsightsSectionEducation",
  skills: "aiInsightsSectionSkills",
  projects: "aiInsightsSectionProjects",
  summary: "aiInsightsSectionSummary",
};
const SECTION_ORDER: ResumeExcerptSection[] = [
  "experience",
  "skills",
  "education",
  "projects",
  "summary",
];

function ResumeExcerptList({
  candidateId,
  excerpts,
}: {
  candidateId: string;
  excerpts: ResumeExcerpt[];
}) {
  const t = useTranslations("recruitment");
  const groups = useMemo(() => {
    const map = new Map<ResumeExcerptSection, ResumeExcerpt[]>();
    for (const e of excerpts) {
      const bucket = map.get(e.section) ?? [];
      bucket.push(e);
      map.set(e.section, bucket);
    }
    return SECTION_ORDER.flatMap((s) => {
      const items = map.get(s);
      return items && items.length > 0 ? [{ section: s, items }] : [];
    });
  }, [excerpts]);

  return (
    <div
      className="space-y-2 rounded-md border bg-muted/30 p-3"
      data-testid="ai-analysis-resume-excerpts"
    >
      <p className="text-xs font-medium text-muted-foreground">
        {t("aiInsightsResumeCitations")}
      </p>
      <div className="space-y-2">
        {groups.map(({ section, items }) => (
          <div key={section} className="space-y-1">
            <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
              {t(SECTION_LABEL_KEYS[section])}
            </p>
            <div className="flex flex-wrap gap-1.5">
              {items.map((e, idx) => (
                <button
                  key={`${section}-${idx}`}
                  type="button"
                  onClick={() =>
                    dispatchResumeExcerptFocus({
                      ...e,
                      candidate_id: candidateId,
                    })
                  }
                  className="inline-flex max-w-full items-start rounded-md border border-border bg-background px-2 py-1 text-left text-xs text-foreground/90 hover:border-primary/60 hover:bg-primary/5 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                  title={
                    e.source_company || e.source_period
                      ? [e.source_company, e.source_period]
                          .filter(Boolean)
                          .join(" · ")
                      : t("aiInsightsFocusInResume")
                  }
                  data-testid={`ai-analysis-resume-excerpt-${section}-${idx}`}
                >
                  <span className="line-clamp-2">{e.excerpt_text}</span>
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function TopupCallout({
  eligibility,
  onTopup,
  showCredits,
  busy,
}: {
  eligibility: TopupEligibility;
  onTopup: () => void;
  showCredits: boolean;
  busy: boolean;
}) {
  const t = useTranslations("recruitment");
  if (eligibility.eligible) {
    return (
      <div className={`flex items-center justify-between gap-3 rounded-md p-3 text-sm ${ALERT_TONE.emerald}`}>
        <div className="flex items-center gap-2">
          <CheckCircle2
            className="size-4 text-emerald-700 dark:text-emerald-300"
            aria-hidden
          />
          <p>{t("aiInsightsTopupAvailable")}</p>
        </div>
        <Button
          size="sm"
          onClick={onTopup}
          disabled={busy}
          data-testid="ai-analysis-upgrade-to-full-btn"
        >
          {showCredits
            ? t("aiInsightsUpgradeToFullCr", {
                cost: AI_ANALYSIS_PRICING.topup_to_full,
              })
            : t("aiInsightsUpgradeToFull")}
        </Button>
      </div>
    );
  }

  // Resume-only run exists, but top-up is blocked — surface the reason
  // so the recruiter knows whether the answer is "schedule an
  // interview", "rerun from scratch" or "wait for a profile freeze".
  const reasonMap: Record<string, string> = {
    no_transcribed_interview: t("aiInsightsReasonNoInterview"),
    resume_only_too_old: t("aiInsightsReasonTooOld", {
      days: eligibility.window_days ?? 30,
    }),
    profile_changed: t("aiInsightsReasonProfileChanged"),
    profile_missing: t("aiInsightsReasonProfileMissing"),
    no_active_resume_only_run: "",
  };
  const text = reasonMap[eligibility.reason ?? ""] ?? "";
  if (!text) return null;
  return (
    <div className="flex items-start gap-2 rounded-md bg-muted/60 p-3 text-xs text-muted-foreground">
      <AlertCircle className="size-4 shrink-0" aria-hidden />
      <p>{text}</p>
    </div>
  );
}

function VerdictPill({
  verdict,
  score,
}: {
  verdict: string;
  score: number | null;
}) {
  const map: Record<string, string> = {
    recommended: BADGE_COLOR.emerald,
    needs_check: BADGE_COLOR.amber,
    not_recommended: BADGE_COLOR.rose,
    pending: BADGE_COLOR.neutral,
  };
  const label = verdict.replaceAll("_", " ");
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
        map[verdict] ?? map.pending,
      )}
    >
      <span className="capitalize">{label}</span>
      {score !== null && (
        <span className="tabular-nums opacity-70">
          {Math.round(score * 100)}%
        </span>
      )}
    </span>
  );
}

function ModeBadge({ mode }: { mode: AiAnalysisRun["mode"] }) {
  const t = useTranslations("recruitment");
  const isResumeOnly = mode === "resume_only";
  return (
    <Badge
      variant="outline"
      className={cn(
        "text-[10px] uppercase tracking-wide",
        isResumeOnly
          ? "border-amber-300 text-amber-800"
          : "border-emerald-300 text-emerald-800",
      )}
      data-testid={`ai-analysis-mode-badge-${mode}`}
      title={
        isResumeOnly
          ? t("aiInsightsModeBadgeResumeOnlyTitle")
          : t("aiInsightsModeBadgeFullTitle")
      }
    >
      {isResumeOnly
        ? t("aiInsightsModeBadgeResumeOnly")
        : t("aiInsightsModeBadgeFull")}
    </Badge>
  );
}

function AnalyzeSplitButton({
  disabled,
  busy,
  showCredits,
  hasTranscribedInterview,
  topupEligible,
  onResumeOnly,
  onFullMode,
}: {
  disabled: boolean;
  busy: boolean;
  showCredits: boolean;
  hasTranscribedInterview: boolean;
  topupEligible: boolean;
  onResumeOnly: () => void;
  onFullMode: () => void;
}) {
  const t = useTranslations("recruitment");
  // HRP-269: split-button — primary fires resume-only as before, the
  // chevron dropdown exposes ``Resume + interview`` (full mode, 40 cr).
  // The full-mode item stays visible even without a transcribed
  // interview but renders disabled with a tooltip explaining why —
  // recruiters still discover the option instead of wondering whether
  // it exists.
  //
  // ``topupEligible`` also forces the item disabled: when a prior
  // resume-only baseline is still inside the 30-day top-up window the
  // recruiter should take the +20-cr upgrade in TopupCallout instead
  // of paying full price here.
  const fullModeBlocked = !hasTranscribedInterview || topupEligible;
  const fullModeReason = !hasTranscribedInterview
    ? t("aiInsightsFullBlockedNoInterview")
    : topupEligible
      ? showCredits
        ? t("aiInsightsFullBlockedTopupCr", {
            topup: AI_ANALYSIS_PRICING.topup_to_full,
            full: AI_ANALYSIS_PRICING.full,
          })
        : t("aiInsightsFullBlockedTopup")
      : showCredits
        ? t("aiInsightsFullReasonCr", { cost: AI_ANALYSIS_PRICING.full })
        : t("aiInsightsFullReason");

  return (
    <div className="inline-flex items-stretch">
      <Button
        size="sm"
        onClick={onResumeOnly}
        disabled={disabled}
        title={
          showCredits
            ? t("aiInsightsResumeOnlyTitleCr", {
                cost: AI_ANALYSIS_PRICING.resume_only,
              })
            : t("aiInsightsResumeOnlyTitle")
        }
        className="rounded-r-none"
        data-testid="candidate-section-ai-insights-analyze-resume-only"
      >
        {busy ? (
          <Loader2 className="size-3.5 animate-spin" aria-hidden />
        ) : (
          <Sparkles className="size-3.5" aria-hidden />
        )}
        <span className="ml-1">
          {showCredits
            ? t("aiInsightsResumeOnlyBtnCr", {
                cost: AI_ANALYSIS_PRICING.resume_only,
              })
            : t("aiInsightsResumeOnlyBtn")}
        </span>
      </Button>
      <DropdownMenu>
        <DropdownMenuTrigger
          disabled={disabled}
          render={
            <Button
              size="sm"
              disabled={disabled}
              className="rounded-l-none border-l border-l-primary-foreground/20 px-2"
              aria-label={t("aiInsightsMoreOptionsAria")}
              data-testid="candidate-section-ai-insights-analyze-menu-trigger"
            />
          }
        >
          <ChevronDown className="size-3.5" aria-hidden />
        </DropdownMenuTrigger>
        <DropdownMenuContent
          align="end"
          data-testid="candidate-section-ai-insights-analyze-menu"
        >
          <DropdownMenuItem
            onClick={() => {
              if (fullModeBlocked) return;
              onFullMode();
            }}
            disabled={fullModeBlocked}
            title={fullModeReason}
            data-testid="candidate-section-ai-insights-analyze-full"
          >
            <Sparkles className="mr-2 size-3.5" aria-hidden />
            <span>
              {showCredits
                ? t("aiInsightsFullBtnCr", { cost: AI_ANALYSIS_PRICING.full })
                : t("aiInsightsFullBtn")}
            </span>
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

function HistoryDialog({
  open,
  onOpenChange,
  runs,
}: {
  open: boolean;
  onOpenChange: (next: boolean) => void;
  runs: AiAnalysisRun[];
}) {
  const t = useTranslations("recruitment");
  const locale = useLocale();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-w-2xl"
        data-testid="ai-analysis-history-modal"
      >
        <DialogTitle className="text-base font-semibold">
          {t("aiInsightsHistoryTitle")}
        </DialogTitle>
        <DialogDescription className="text-xs text-muted-foreground">
          {t("aiInsightsHistoryDescription")}
        </DialogDescription>
        <div className="mt-3 max-h-[60vh] space-y-2 overflow-y-auto">
          {runs.length === 0 && (
            <p className="text-sm text-muted-foreground">
              {t("aiInsightsHistoryEmpty")}
            </p>
          )}
          {runs.map((r) => (
            <div
              key={r.id}
              className={cn(
                "rounded-md border p-3 text-xs",
                r.archived_at && "bg-muted/30 text-muted-foreground",
              )}
              data-testid={`ai-analysis-history-entry-${r.id}`}
            >
              <div className="flex items-center gap-2">
                <ModeBadge mode={r.mode} />
                <span className="font-medium">{r.verdict ?? "—"}</span>
                {r.archived_at && (
                  <span className="text-[10px] uppercase tracking-wide opacity-70">
                    {t("aiInsightsArchived")}
                  </span>
                )}
                <span className="ml-auto">
                  {new Date(r.created_at).toLocaleString(locale)}
                </span>
              </div>
              {r.verdict_summary && <p className="mt-1">{r.verdict_summary}</p>}
            </div>
          ))}
        </div>
        <div className="mt-4 flex justify-end">
          <DialogClose
            render={
              <Button variant="outline" size="sm">
                {t("aiInsightsClose")}
              </Button>
            }
          />
        </div>
      </DialogContent>
    </Dialog>
  );
}
