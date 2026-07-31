"use client";

// HRP-359: standalone evaluation page for an invited external evaluator.
// Token-only access (no tenant JWT), two-pane layout: candidate context
// (resume, individual questions) on the left, the HRP-348 competence
// sheet on the right. Autosave mirrors the internal section (1.5 s).

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { Loader2, Pencil } from "lucide-react";
import { api } from "@/lib/api";
import {
  CompetenceScoreList,
  findCompetenceComment,
  replaceCompetenceRow,
  replaceIndicatorRow,
  toProfileCompetences,
  upsertCompetence,
  upsertIndicator,
  type CompetenceScore,
  type IndicatorScore,
  type ProfileCompetence,
  type RawProfileCompetence,
  type ScaleLevel,
} from "@/components/recruitment/evaluation-sheet-form";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { toast } from "sonner";

interface PublicQuestion {
  id: string;
  question_text: string;
  resume_fragment: string | null;
  purpose: string | null;
  sort_order: number;
}

interface PublicAssessment {
  id: string;
  status: "draft" | "submitted";
  final_notes: string | null;
  competence_scores: CompetenceScore[];
  indicator_scores: IndicatorScore[];
}

type PublicContext = {
  invite_id: string;
  status: string;
  expires_at: string;
  evaluator_name: string | null;
  allow_reediting: boolean;
  candidate_vacancy_id: string;
  round_id: string | null;
  assessment_id: string | null;
  personal_message: string | null;
  consent_accepted: boolean;
  tenant_name: string | null;
  // Everything below is withheld by the server until consent is accepted
  // (the payload carries candidate PII and a presigned resume URL).
  candidate_name?: string;
  vacancy_title?: string | null;
  resume_url?: string | null;
  resume_filename?: string | null;
  resume_mime_type?: string | null;
  questions?: PublicQuestion[];
  recruiter_name?: string | null;
  recruiter_email?: string | null;
  scale_levels?: ScaleLevel[];
  competences?: RawProfileCompetence[];
  critical_submit_threshold?: number;
  assessment?: PublicAssessment | null;
};

type Phase =
  | "loading"
  | "expired"
  | "revoked"
  | "invalid"
  | "consent"
  | "form";

const AUTOSAVE_MS = 1500;

/** `auth` namespace translator, threaded into module-level helpers. */
type Translator = ReturnType<typeof useTranslations>;

function formatTimeLeft(expiresAt: string, t: Translator): string {
  const ms = new Date(expiresAt).getTime() - Date.now();
  if (ms <= 0) return t("timeLeftExpired");
  const totalHours = Math.floor(ms / 3_600_000);
  const days = Math.floor(totalHours / 24);
  const hours = totalHours % 24;
  if (days > 0) return t("timeLeftDaysHours", { days, hours });
  if (totalHours > 0) return t("timeLeftHours", { hours: totalHours });
  return t("timeLeftMinutes", {
    minutes: Math.max(1, Math.floor(ms / 60_000)),
  });
}

export default function PublicAssessmentPage() {
  const t = useTranslations("auth");
  const locale = useLocale();
  const { token } = useParams<{ token: string }>();
  const [phase, setPhase] = useState<Phase>("loading");
  const [ctx, setCtx] = useState<PublicContext | null>(null);
  const [competences, setCompetences] = useState<ProfileCompetence[]>([]);
  const [sheet, setSheet] = useState<PublicAssessment | null>(null);
  const [editingName, setEditingName] = useState(false);
  const [nameDraft, setNameDraft] = useState("");
  const [finalNotes, setFinalNotes] = useState("");
  const [submitWarning, setSubmitWarning] = useState(false);
  const [savingState, setSavingState] = useState<"idle" | "saving" | "saved">(
    "idle",
  );

  // One debounce timer per score row — same rationale as the internal
  // section: a shared timer would drop the previous row's PATCH. The
  // save fns are kept alongside so submit can flush them early.
  const debounceTimers = useRef<Map<string, ReturnType<typeof setTimeout>>>(
    new Map(),
  );
  const pendingFns = useRef<Map<string, () => Promise<void>>>(new Map());
  const pendingSaves = useRef(0);
  const savedNoticeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const timers = debounceTimers.current;
    return () => {
      timers.forEach((t) => clearTimeout(t));
      if (savedNoticeTimer.current) clearTimeout(savedNoticeTimer.current);
    };
  }, []);

  const load = useCallback(async () => {
    try {
      const data = await api.get<PublicContext>(
        `/v1/public/assessments/${token}`,
      );
      setCtx(data);
      setNameDraft(data.evaluator_name ?? "");
      setSheet(data.assessment ?? null);
      setFinalNotes(data.assessment?.final_notes ?? "");
      setCompetences(await toProfileCompetences(data.competences ?? []));
      setPhase(data.consent_accepted ? "form" : "consent");
    } catch (err: unknown) {
      const e = err as { status?: number; message?: string };
      if (e.status === 410) {
        const m = (e.message || "").toLowerCase();
        if (m.includes("revoked")) setPhase("revoked");
        else if (m.includes("expired")) setPhase("expired");
        else setPhase("invalid");
      } else {
        setPhase("invalid");
      }
    }
  }, [token]);

  useEffect(() => {
    const handle = window.setTimeout(() => {
      void load();
    }, 0);
    return () => window.clearTimeout(handle);
  }, [load]);

  const submitted = ctx?.status === "submitted";
  const readOnly = submitted && !ctx?.allow_reediting;

  async function acceptConsent() {
    try {
      await api.post(`/v1/public/assessments/${token}/consent/accept`);
      // The pre-consent context is deliberately slim (no candidate data);
      // reload to get the full evaluation payload.
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("actionFailed"));
    }
  }
  async function decline() {
    try {
      await api.post(`/v1/public/assessments/${token}/consent/decline`);
      setPhase("invalid");
    } catch {
      // no-op
    }
  }

  async function saveName() {
    try {
      await api.patch(`/v1/public/assessments/${token}/name`, {
        name: nameDraft,
      });
      setCtx((prev) => (prev ? { ...prev, evaluator_name: nameDraft } : prev));
      setEditingName(false);
      toast.success(t("nameUpdated"));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("actionFailed"));
    }
  }

  function scheduleAutosave(key: string, fn: () => Promise<void>) {
    setSavingState("saving");
    if (savedNoticeTimer.current) {
      clearTimeout(savedNoticeTimer.current);
      savedNoticeTimer.current = null;
    }
    const existing = debounceTimers.current.get(key);
    if (existing) clearTimeout(existing);
    else pendingSaves.current += 1;
    pendingFns.current.set(key, fn);
    debounceTimers.current.set(
      key,
      setTimeout(async () => {
        debounceTimers.current.delete(key);
        pendingFns.current.delete(key);
        try {
          await fn();
          if (--pendingSaves.current <= 0) {
            pendingSaves.current = 0;
            setSavingState("saved");
            savedNoticeTimer.current = setTimeout(() => {
              setSavingState("idle");
              savedNoticeTimer.current = null;
            }, 1200);
          }
        } catch {
          toast.error(t("autosaveFailed"));
          if (--pendingSaves.current <= 0) {
            pendingSaves.current = 0;
            setSavingState("idle");
          }
        }
      }, AUTOSAVE_MS),
    );
  }

  function markInProgress() {
    setCtx((prev) =>
      prev && (prev.status === "pending" || prev.status === "opened")
        ? { ...prev, status: "in_progress" }
        : prev,
    );
  }

  function setCompetenceScore(
    competenceId: string,
    value: number | null,
    comment?: string,
  ) {
    if (readOnly) return;
    setSheet((prev) =>
      prev
        ? {
            ...prev,
            competence_scores: upsertCompetence(prev.competence_scores, {
              competence_id: competenceId,
              score_value: value,
              comment: comment ?? findCompetenceComment(prev, competenceId),
            }),
          }
        : prev,
    );
    if (value !== null) markInProgress();
    scheduleAutosave(`comp:${competenceId}`, async () => {
      await api.patch<CompetenceScore>(
        `/v1/public/assessments/${token}/competence-scores/${competenceId}`,
        {
          score_value: value,
          score_source: "manual",
          comment: comment ?? findCompetenceComment(sheet, competenceId),
        },
      );
    });
  }

  function setIndicatorScore(
    competenceId: string,
    indicatorId: string,
    value: number | null,
  ) {
    if (readOnly) return;
    setSheet((prev) =>
      prev
        ? {
            ...prev,
            indicator_scores: upsertIndicator(prev.indicator_scores, {
              indicator_id: indicatorId,
              competence_id: competenceId,
              score_value: value,
            }),
          }
        : prev,
    );
    if (value !== null) markInProgress();
    scheduleAutosave(`ind:${indicatorId}`, async () => {
      await api.patch<IndicatorScore>(
        `/v1/public/assessments/${token}/indicator-scores/${indicatorId}`,
        {
          competence_id: competenceId,
          score_value: value,
        },
      );
      // The backend recomputes the competence overall from indicators —
      // refetch the context and merge just the rows this save owns.
      const fresh = await api.get<PublicContext>(
        `/v1/public/assessments/${token}`,
      );
      const freshSheet = fresh.assessment;
      if (!freshSheet) return;
      setSheet((prev) => {
        if (!prev || prev.id !== freshSheet.id) return prev;
        const freshInd = freshSheet.indicator_scores.find(
          (s) => s.indicator_id === indicatorId,
        );
        const freshOverall = freshSheet.competence_scores.find(
          (c) => c.competence_id === competenceId,
        );
        const overallPending = debounceTimers.current.has(
          `comp:${competenceId}`,
        );
        return {
          ...prev,
          indicator_scores: freshInd
            ? replaceIndicatorRow(prev.indicator_scores, freshInd)
            : prev.indicator_scores,
          competence_scores:
            freshOverall && !overallPending
              ? replaceCompetenceRow(prev.competence_scores, freshOverall)
              : prev.competence_scores,
        };
      });
    });
  }

  const saveFinalNotes = useCallback(
    async (notes: string) => {
      await api.patch(`/v1/public/assessments/${token}/notes`, {
        final_notes: notes,
      });
    },
    [token],
  );

  const scoredCount = useMemo(
    () =>
      sheet
        ? competences.filter((comp) =>
            sheet.competence_scores.some(
              (c) => c.competence_id === comp.id && c.score_value !== null,
            ),
          ).length
        : 0,
    [sheet, competences],
  );
  const criticalCompetences = useMemo(
    () => competences.filter((c) => c.criticality === "critical"),
    [competences],
  );
  const unscoredCritical = useMemo(
    () =>
      criticalCompetences.filter(
        (comp) =>
          !sheet?.competence_scores.some(
            (c) => c.competence_id === comp.id && c.score_value !== null,
          ),
      ),
    [criticalCompetences, sheet],
  );

  // Run every debounced save immediately — a score clicked right before
  // Submit must land before the invite turns read-only.
  async function flushPendingSaves() {
    const entries = Array.from(pendingFns.current.entries());
    pendingFns.current.clear();
    for (const [key, fn] of entries) {
      const timer = debounceTimers.current.get(key);
      if (timer) clearTimeout(timer);
      debounceTimers.current.delete(key);
      try {
        await fn();
      } catch {
        toast.error(t("scoreSaveFailed"));
      }
    }
    pendingSaves.current = 0;
    setSavingState("idle");
  }

  async function doSubmit() {
    try {
      await flushPendingSaves();
      await api.post(`/v1/public/assessments/${token}/submit`, {
        final_notes: finalNotes,
      });
      setCtx((prev) => (prev ? { ...prev, status: "submitted" } : prev));
      toast.success(t("submittedThanks"));
      window.scrollTo({ top: 0 });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("actionFailed"));
    }
  }

  function submitClicked() {
    // HRP-359: warn when fewer than the threshold share of critical
    // competences are scored; the server never hard-blocks the submit.
    const threshold = ctx?.critical_submit_threshold ?? 0.5;
    const total = criticalCompetences.length;
    const scored = total - unscoredCritical.length;
    if (total > 0 && scored < total * threshold) {
      setSubmitWarning(true);
      return;
    }
    void doSubmit();
  }

  if (phase === "loading") {
    return (
      <div className="flex items-center justify-center py-16 text-sm text-muted-foreground">
        <Loader2 className="mr-2 size-4 animate-spin" />
        {t("loadingEllipsis")}
      </div>
    );
  }
  if (phase === "expired") {
    return (
      <ErrorPage
        title={t("expiredTitle")}
        testid="public-error-expired-token-page"
        body={t("expiredBody")}
      />
    );
  }
  if (phase === "revoked") {
    return (
      <ErrorPage
        title={t("revokedTitle")}
        testid="public-error-revoked-token-page"
        body={t("revokedBody")}
      />
    );
  }
  if (phase === "invalid") {
    return (
      <ErrorPage
        title={t("invalidLinkTitle")}
        testid="public-error-invalid-token-page"
        body={t("invalidLinkBody")}
      />
    );
  }

  if (phase === "consent") {
    return (
      <Card
        className="mx-auto max-w-xl"
        data-testid="public-assessment-consent-modal"
      >
        <CardHeader>
          <CardTitle className="text-base">
            {t("consentBeforeYouBegin")}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <p>{t("consentIntro")}</p>
          <ul className="list-disc space-y-1 pl-5 text-sm">
            <li>{t("consentItemPersonalData")}</li>
            <li>{t("consentItemNoShare")}</li>
            <li>{t("consentItemShared")}</li>
            <li>
              {t("consentItemName", { name: ctx?.evaluator_name ?? "—" })}
            </li>
          </ul>
          <div className="flex justify-between gap-2">
            <Button
              variant="ghost"
              onClick={decline}
              data-testid="public-assessment-consent-decline-btn"
            >
              {t("decline")}
            </Button>
            <Button
              onClick={acceptConsent}
              data-testid="public-assessment-consent-accept-btn"
            >
              {t("iUnderstand")}
            </Button>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <div data-testid="public-assessment-page" className="space-y-4">
      <header className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
        <div>
          {ctx?.tenant_name && (
            <p
              className="text-xs uppercase tracking-wide text-muted-foreground"
              data-testid="public-assessment-tenant-line"
            >
              {t("evaluationForTenant", { tenant: ctx.tenant_name })}
            </p>
          )}
          <h1 className="text-xl font-semibold">
            {t("welcomeEvaluator", {
              name: ctx?.evaluator_name || t("evaluatorFallback"),
            })}
          </h1>
          <p className="text-sm text-muted-foreground">
            {t.rich(
              ctx?.vacancy_title
                ? "evaluatingCandidateForVacancy"
                : "evaluatingCandidate",
              {
                candidate: ctx?.candidate_name || t("unnamedCandidate"),
                vacancy: ctx?.vacancy_title ?? "",
                name: (chunks) => (
                  <strong data-testid="public-assessment-candidate-name">
                    {chunks}
                  </strong>
                ),
              },
            )}
          </p>
        </div>
        <div className="flex items-center gap-2 text-sm">
          {editingName ? (
            <>
              <input
                value={nameDraft}
                onChange={(e) => setNameDraft(e.target.value)}
                className="rounded-md border px-2 py-1 text-sm"
                data-testid="public-assessment-evaluator-name-input"
              />
              <Button size="sm" onClick={saveName}>
                {t("save")}
              </Button>
            </>
          ) : (
            <>
              <span data-testid="public-assessment-evaluator-name-display">
                {ctx?.evaluator_name ?? t("unnamed")}
              </span>
              {!readOnly && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setEditingName(true)}
                  data-testid="public-assessment-evaluator-name-edit-btn"
                >
                  <Pencil className="size-3.5" />
                </Button>
              )}
            </>
          )}
        </div>
      </header>

      {submitted && (
        <Card
          className="border-emerald-200 bg-emerald-50/50"
          data-testid="public-assessment-submitted-banner"
        >
          <CardContent className="space-y-1 py-4 text-sm">
            <p className="font-medium">
              {t("submittedBanner", {
                recruiter: ctx?.recruiter_name ?? t("theRecruiter"),
              })}
            </p>
            {ctx?.allow_reediting ? (
              <p
                className="text-muted-foreground"
                data-testid="public-assessment-reedit-note"
              >
                {t("reeditNote", {
                  date: ctx
                    ? new Date(ctx.expires_at).toLocaleDateString(locale)
                    : "—",
                })}
              </p>
            ) : (
              <p className="text-muted-foreground">{t("readOnlyNote")}</p>
            )}
          </CardContent>
        </Card>
      )}

      {ctx?.personal_message && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">{t("fromRecruiter")}</CardTitle>
          </CardHeader>
          <CardContent className="whitespace-pre-wrap text-sm">
            {ctx.personal_message}
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        {/* Pane A — candidate context */}
        <div className="space-y-4" data-testid="public-assessment-context-pane">
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">{t("resume")}</CardTitle>
            </CardHeader>
            <CardContent>
              {ctx?.resume_url ? (
                <iframe
                  src={ctx.resume_url}
                  title={ctx.resume_filename ?? t("resume")}
                  className="h-[480px] w-full rounded-md border"
                  data-testid="public-assessment-resume-frame"
                />
              ) : (
                <p className="text-sm text-muted-foreground">
                  {t("noResumeUploaded")}
                </p>
              )}
            </CardContent>
          </Card>
          {(ctx?.questions?.length ?? 0) > 0 && (
            <Card data-testid="public-assessment-questions">
              <CardHeader>
                <CardTitle className="text-sm">
                  {t("individualQuestions")}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ol className="list-decimal space-y-2 pl-5 text-sm">
                  {(ctx?.questions ?? []).map((q) => (
                    <li key={q.id}>
                      {q.question_text}
                      {q.resume_fragment && (
                        <p className="mt-0.5 text-xs text-muted-foreground">
                          {t("questionBasedOn", {
                            fragment: q.resume_fragment,
                          })}
                        </p>
                      )}
                    </li>
                  ))}
                </ol>
              </CardContent>
            </Card>
          )}
        </div>

        {/* Pane B — evaluation form */}
        <Card data-testid="public-assessment-form-pane">
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-sm">
              {t("competencyEvaluation")}
            </CardTitle>
            <span
              className="text-xs text-muted-foreground"
              data-testid="public-assessment-progress"
            >
              {t("progressAssessed", {
                scored: scoredCount,
                total: competences.length,
              })}
            </span>
          </CardHeader>
          <CardContent className="space-y-3">
            <CompetenceScoreList
              competences={competences}
              scaleLevels={ctx?.scale_levels ?? []}
              competenceScores={sheet?.competence_scores ?? []}
              indicatorScores={sheet?.indicator_scores ?? []}
              disabled={readOnly}
              emptyHint={t("sheetNotReady")}
              onCompetenceScore={setCompetenceScore}
              onIndicatorScore={setIndicatorScore}
            />
            <textarea
              placeholder={t("finalNotesPlaceholder")}
              value={finalNotes}
              readOnly={readOnly}
              onChange={(e) => {
                const next = e.target.value;
                setFinalNotes(next);
                scheduleAutosave("notes", () => saveFinalNotes(next));
              }}
              rows={4}
              className="w-full rounded-md border p-2 text-sm"
              data-testid="public-assessment-final-notes"
            />
            <div className="flex items-center justify-between">
              <div
                aria-live="polite"
                className="text-xs text-muted-foreground"
                data-testid="assessment-autosave-status"
              >
                {savingState === "saving"
                  ? t("saving")
                  : savingState === "saved"
                    ? t("saved")
                    : t("savedAutomatically")}
              </div>
              {!readOnly && (
                <Button
                  onClick={submitClicked}
                  data-testid="public-assessment-submit-btn"
                >
                  {submitted ? t("resubmitEvaluation") : t("submitEvaluation")}
                </Button>
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      <footer className="flex flex-col gap-1 border-t pt-3 text-xs text-muted-foreground md:flex-row md:items-center md:justify-between">
        <span data-testid="public-assessment-expiration-countdown">
          {t("linkExpiresIn", {
            time: ctx ? formatTimeLeft(ctx.expires_at, t) : "—",
          })}
        </span>
        {ctx?.recruiter_email && (
          <span>
            {t("needHelp")}{" "}
            <a className="underline" href={`mailto:${ctx.recruiter_email}`}>
              {ctx.recruiter_email}
            </a>
          </span>
        )}
      </footer>

      <ConfirmDialog
        open={submitWarning}
        onOpenChange={setSubmitWarning}
        title={t("submitWarningTitle")}
        description={t("submitWarningBody", {
          count: unscoredCritical.length,
        })}
        confirmLabel={t("submitAnyway")}
        cancelLabel={t("continueEditing")}
        onConfirm={() => {
          setSubmitWarning(false);
          void doSubmit();
        }}
        testId="public-assessment-submit-warning-modal"
      />
    </div>
  );
}

function ErrorPage({
  title,
  body,
  testid,
}: {
  title: string;
  body: string;
  testid: string;
}) {
  return (
    <Card className="mx-auto max-w-md" data-testid={testid}>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent className="text-sm text-muted-foreground">{body}</CardContent>
    </Card>
  );
}
