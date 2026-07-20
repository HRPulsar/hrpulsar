"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/context/auth-context";
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
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Loader2, Mail, Plus, UserPlus, X } from "lucide-react";
import { toast } from "sonner";

type RoundType = "pre_interview" | "interview" | "final";

interface RoundDto {
  id: string;
  type: RoundType;
  round_number: number | null;
  status: "in_progress" | "complete" | "archived";
  completed_at: string | null;
  archived_at: string | null;
  invites: InviteDto[];
  evaluators: { user_id: string }[];
}

interface InviteDto {
  id: string;
  email: string;
  evaluator_name: string | null;
  status: string;
  expires_at: string;
  allow_reediting: boolean;
  delivery_status: string;
  delivery_error: string | null;
  delivery_retry_count: number;
}

interface AssessmentSheet {
  id: string;
  round_id: string;
  evaluator_type: "user" | "invited";
  evaluator_user_id: string | null;
  evaluator_display_name: string | null;
  status: "draft" | "submitted";
  final_notes: string | null;
  competence_scores: CompetenceScore[];
  indicator_scores: IndicatorScore[];
}

interface VacancyOption {
  id: string;
  vacancy_id: string;
  vacancy_title: string | null;
}

// HRP-358: raw invite statuses are machine-codes; the recruiter-facing
// chip needs a readable label and a tone that survives at a glance.
const INVITE_STATUS_CHIPS: Record<
  string,
  { label: string; className: string }
> = {
  pending: { label: "pending", className: "bg-muted text-muted-foreground" },
  opened: { label: "opened", className: "bg-blue-50 text-blue-700" },
  in_progress: {
    label: "in progress",
    className: "bg-amber-50 text-amber-700",
  },
  submitted: {
    label: "submitted",
    className: "bg-emerald-50 text-emerald-700",
  },
  expired: { label: "expired", className: "bg-rose-50 text-rose-700" },
  declined: { label: "declined", className: "bg-rose-50 text-rose-700" },
  revoked: { label: "revoked", className: "bg-muted text-muted-foreground" },
};

export function inviteStatusChip(status: string): {
  label: string;
  className: string;
} {
  return (
    INVITE_STATUS_CHIPS[status] ?? {
      label: status,
      className: "bg-muted text-muted-foreground",
    }
  );
}

interface Props {
  vacancies: VacancyOption[];
  /** HRP-361/366: the vacancy the user navigated from — it becomes the
   * default tab instead of the most recent application. */
  initialVacancyId?: string;
}

const AUTOSAVE_MS = 1500;

export function ManagerAssessmentSection({
  vacancies,
  initialVacancyId,
}: Props) {
  const [activeCvId, setActiveCvId] = useState<string | null>(
    vacancies.find((v) => v.vacancy_id === initialVacancyId)?.id ??
      vacancies[0]?.id ??
      null,
  );
  const [rounds, setRounds] = useState<RoundDto[]>([]);
  const [activeRoundId, setActiveRoundId] = useState<string | null>(null);
  const [sheet, setSheet] = useState<AssessmentSheet | null>(null);
  const [scaleLevels, setScaleLevels] = useState<ScaleLevel[]>([]);
  const [profileCompetences, setProfileCompetences] = useState<
    ProfileCompetence[]
  >([]);
  const [invites, setInvites] = useState<InviteDto[]>([]);
  // HRP-186 REDO: spec §3 — `+ New round` must surface a confirm dialog
  // ("Add new interview round? This will create Interview {N+1}.") so a
  // recruiter cannot accidentally insert a 4th round during a hectic
  // interview day.
  const [pendingNewRound, setPendingNewRound] = useState(false);
  const [savingState, setSavingState] = useState<"idle" | "saving" | "saved">(
    "idle",
  );
  const [loadingRounds, setLoadingRounds] = useState(false);
  const { user } = useAuth();

  // HRP-348 REDO: one debounce timer per score row — a shared timer would
  // silently drop the previous row's PATCH when the evaluator moves fast
  // between competences/indicators inside the autosave window.
  const debounceTimers = useRef<Map<string, ReturnType<typeof setTimeout>>>(
    new Map(),
  );
  const pendingSaves = useRef(0);

  const activeVacancy = useMemo(
    () => vacancies.find((v) => v.id === activeCvId) ?? null,
    [vacancies, activeCvId],
  );

  // ── Load rounds for the active CV ────────────────────────────────────
  const loadRounds = useCallback(async (cvId: string) => {
    setLoadingRounds(true);
    try {
      const rows = await api.get<RoundDto[]>(
        `/v1/candidate-vacancies/${cvId}/assessment-rounds`,
      );
      setRounds(rows);
      if (rows.length && !rows.find((r) => r.id === activeRoundId)) {
        setActiveRoundId(rows[rows.length - 1]!.id);
      }
    } catch {
      setRounds([]);
    } finally {
      setLoadingRounds(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!activeCvId) return;
    void loadRounds(activeCvId);
  }, [activeCvId, loadRounds]);

  // ── Load vacancy snapshot + profile ──────────────────────────────────
  useEffect(() => {
    if (!activeVacancy) return;
    let cancelled = false;
    async function load() {
      try {
        // HRP-348: the vacancy read strips the profile — competences live
        // behind the dedicated /profile endpoint, so fetch both.
        const [vac, prof] = await Promise.all([
          api.get<{
            assessment_scale_id?: string | null;
            assessment_scale_snapshot?: { levels?: ScaleLevel[] } | null;
          }>(`/recruitment/vacancies/${activeVacancy!.vacancy_id}`),
          api
            .get<
              | { profile: null }
              | { profile_data?: { competences?: RawProfileCompetence[] } }
            >(`/recruitment/vacancies/${activeVacancy!.vacancy_id}/profile`)
            .catch(() => null),
        ]);
        if (cancelled) return;
        const levels = vac.assessment_scale_snapshot?.levels;
        if (levels?.length) {
          setScaleLevels(levels);
        } else {
          const scales = await api.get<
            {
              id: string;
              is_default: boolean;
              archived_at: string | null;
              levels: ScaleLevel[];
            }[]
          >("/v1/tenants/me/assessment-scales");
          if (cancelled) return;
          // The vacancy-bound scale wins over the tenant default — the
          // snapshot only exists once the first score is written.
          const bound = vac.assessment_scale_id
            ? scales.find((s) => s.id === vac.assessment_scale_id)
            : undefined;
          const def = scales.find((s) => s.is_default && !s.archived_at);
          setScaleLevels(bound?.levels ?? def?.levels ?? []);
        }
        const compsRaw =
          prof && "profile_data" in prof
            ? (prof.profile_data?.competences ?? [])
            : [];
        const comps = await toProfileCompetences(compsRaw);
        if (cancelled) return;
        setProfileCompetences(comps);
      } catch {
        if (!cancelled) {
          setScaleLevels([]);
          setProfileCompetences([]);
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [activeVacancy]);

  // ── Load active sheet ────────────────────────────────────────────────
  const ensureSheet = useCallback(
    async (roundId: string) => {
      try {
        const list = await api.get<AssessmentSheet[]>(
          `/v1/assessment-rounds/${roundId}/assessments`,
        );
        // HRP-348 REDO: sheets are per evaluator — pick the one owned by
        // the signed-in user, never a colleague's. Falling back to any
        // "user" sheet would show (and let us PATCH into) foreign scores.
        const mine = list.find(
          (a) =>
            a.evaluator_type === "user" &&
            (user ? a.evaluator_user_id === user.id : false),
        );
        if (mine) {
          setSheet(mine);
          return;
        }
        // No sheet for current evaluator yet — request creation by adding self as evaluator.
        // We surface a placeholder so the user can still start scoring.
        setSheet(null);
      } catch {
        setSheet(null);
      }
    },
    [user],
  );

  useEffect(() => {
    if (!activeRoundId) return;
    void ensureSheet(activeRoundId);
    const round = rounds.find((r) => r.id === activeRoundId);
    setInvites(round?.invites ?? []);
  }, [activeRoundId, rounds, ensureSheet]);

  async function createRound(type: RoundType) {
    if (!activeCvId) return;
    try {
      const r = await api.post<RoundDto>(
        `/v1/candidate-vacancies/${activeCvId}/assessment-rounds`,
        { type },
      );
      setRounds((prev) => [...prev, r]);
      setActiveRoundId(r.id);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Round create failed");
    }
  }

  async function completeRound() {
    if (!activeRoundId) return;
    try {
      const r = await api.patch<RoundDto>(
        `/v1/assessment-rounds/${activeRoundId}`,
        { status: "complete" },
      );
      setRounds((prev) => prev.map((x) => (x.id === r.id ? r : x)));
      toast.success("Round marked complete");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed");
    }
  }

  function scheduleAutosave(key: string, fn: () => Promise<void>) {
    setSavingState("saving");
    const existing = debounceTimers.current.get(key);
    if (existing) clearTimeout(existing);
    else pendingSaves.current += 1;
    debounceTimers.current.set(
      key,
      setTimeout(async () => {
        debounceTimers.current.delete(key);
        try {
          await fn();
          if (--pendingSaves.current <= 0) {
            pendingSaves.current = 0;
            setSavingState("saved");
            setTimeout(() => setSavingState("idle"), 1200);
          }
        } catch {
          toast.error("Failed to save a score — please retry");
          if (--pendingSaves.current <= 0) {
            pendingSaves.current = 0;
            setSavingState("idle");
          }
        }
      }, AUTOSAVE_MS),
    );
  }

  async function setCompetenceScore(
    competenceId: string,
    value: number | null,
    comment?: string,
  ) {
    if (!sheet) return;
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
    scheduleAutosave(`comp:${competenceId}`, async () => {
      await api.patch<CompetenceScore>(
        `/v1/assessments/${sheet.id}/competence-scores/${competenceId}`,
        {
          score_value: value,
          score_source: "manual",
          comment: comment ?? findCompetenceComment(sheet, competenceId),
        },
      );
    });
  }

  async function setIndicatorScore(
    competenceId: string,
    indicatorId: string,
    value: number | null,
  ) {
    if (!sheet) return;
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
    scheduleAutosave(`ind:${indicatorId}`, async () => {
      await api.patch<IndicatorScore>(
        `/v1/assessments/${sheet.id}/indicator-scores/${indicatorId}`,
        {
          competence_id: competenceId,
          score_value: value,
        },
      );
      // The backend recomputes the competence overall from its indicators
      // (score_source=computed_from_indicators) — refetch so the overall
      // row and the progress bar reflect it without a manual reload.
      const fresh = await api.get<AssessmentSheet>(
        `/v1/assessments/${sheet.id}`,
      );
      // Merge only the rows this save owns: replacing the whole sheet
      // would clobber optimistic edits still waiting in other debounce
      // slots, and a late response after a round switch would resurrect
      // the previous round's sheet.
      setSheet((prev) => {
        if (!prev || prev.id !== fresh.id) return prev;
        const freshInd = fresh.indicator_scores.find(
          (s) => s.indicator_id === indicatorId,
        );
        const freshOverall = fresh.competence_scores.find(
          (c) => c.competence_id === competenceId,
        );
        // A pending manual overall edit on this competence wins over the
        // server-computed value — its own PATCH lands right after ours.
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

  const completedCount = sheet
    ? profileCompetences.filter((comp) =>
        sheet.competence_scores.some(
          (c) => c.competence_id === comp.id && c.score_value !== null,
        ),
      ).length
    : 0;
  const totalCount = profileCompetences.length;

  // HRP-348 REDO: `Mark as complete` unlocks only once every competence
  // with the Critical chip has an overall score (manual or computed).
  const unscoredCritical = profileCompetences.filter(
    (comp) =>
      comp.criticality === "critical" &&
      !sheet?.competence_scores.some(
        (c) => c.competence_id === comp.id && c.score_value !== null,
      ),
  );
  const canComplete =
    completedCount > 0 && unscoredCritical.length === 0;
  const completeHint = !canComplete
    ? unscoredCritical.length > 0
      ? `Assess all critical competences first — ${unscoredCritical.length} left: ${unscoredCritical
          .map((c) => c.name)
          .join(", ")}`
      : "Assess at least one competence first"
    : undefined;

  return (
    <Card data-testid="candidate-section-assessments">
      <CardHeader className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
        <CardTitle className="text-base">Manager assessments</CardTitle>
        {vacancies.length > 1 && (
          <select
            className="rounded-md border px-2 py-1 text-xs"
            value={activeCvId ?? ""}
            onChange={(e) => setActiveCvId(e.target.value)}
          >
            {vacancies.map((v) => (
              <option key={v.id} value={v.id}>
                {v.vacancy_title || v.vacancy_id}
              </option>
            ))}
          </select>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        {!activeCvId && (
          <p className="text-sm text-muted-foreground">
            Attach this candidate to a vacancy first.
          </p>
        )}

        {activeCvId && (
          <>
            {/* Round tabs */}
            <div
              className="flex flex-wrap items-center gap-2"
              data-testid="assessment-round-tabs"
            >
              {loadingRounds && (
                <Loader2 className="size-4 animate-spin text-muted-foreground" />
              )}
              {rounds.map((r) => (
                <button
                  key={r.id}
                  type="button"
                  onClick={() => setActiveRoundId(r.id)}
                  className={`rounded-full px-3 py-1 text-xs ${
                    r.id === activeRoundId
                      ? "bg-primary text-primary-foreground"
                      : "bg-muted text-muted-foreground"
                  }`}
                  data-testid={`assessment-round-tab-${r.id}`}
                >
                  {labelForRound(r)}
                  {r.status === "complete" && <span className="ml-1">·✓</span>}
                </button>
              ))}
              <Button
                size="sm"
                variant="outline"
                onClick={() => setPendingNewRound(true)}
                data-testid="assessment-round-new-btn"
              >
                <Plus className="size-3" /> New round
              </Button>
              {!rounds.some((r) => r.type === "pre_interview") && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => createRound("pre_interview")}
                >
                  + Pre-interview
                </Button>
              )}
              {!rounds.some((r) => r.type === "final") && rounds.length > 0 && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => createRound("final")}
                >
                  + Final
                </Button>
              )}
            </div>

            {/* Autosave indicator */}
            <div
              aria-live="polite"
              className="text-xs text-muted-foreground"
              data-testid="assessment-autosave-status"
            >
              {savingState === "saving"
                ? "Saving…"
                : savingState === "saved"
                  ? "Saved"
                  : null}
            </div>

            {/* Form */}
            {sheet ? (
              <div className="space-y-3">
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <span data-testid="assessment-progress-counter">
                    {completedCount} / {totalCount} competences assessed
                  </span>
                  <div
                    role="progressbar"
                    aria-valuenow={completedCount}
                    aria-valuemin={0}
                    aria-valuemax={totalCount || 1}
                    className="h-1.5 w-32 overflow-hidden rounded bg-muted"
                    data-testid="assessment-progress-bar"
                  >
                    <div
                      className="h-full bg-emerald-500"
                      style={{
                        width: `${
                          totalCount > 0
                            ? (completedCount * 100) / totalCount
                            : 0
                        }%`,
                      }}
                    />
                  </div>
                  {/* Disabled buttons swallow hover (pointer-events:none),
                      so the explainer tooltip lives on the wrapper span. */}
                  <span title={completeHint}>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={completeRound}
                      disabled={!canComplete}
                      data-testid="assessment-round-complete-btn"
                    >
                      Mark as complete
                    </Button>
                  </span>
                </div>
                <CompetenceScoreList
                  competences={profileCompetences}
                  scaleLevels={scaleLevels}
                  competenceScores={sheet.competence_scores}
                  indicatorScores={sheet.indicator_scores}
                  emptyHint="Vacancy profile has no competences yet. Open the vacancy profile to add them, then come back here to assess."
                  onCompetenceScore={(compId, value, comment) =>
                    void setCompetenceScore(compId, value, comment)
                  }
                  onIndicatorScore={(compId, indId, value) =>
                    void setIndicatorScore(compId, indId, value)
                  }
                />
              </div>
            ) : (
              <AddSelfAsEvaluator
                roundId={activeRoundId}
                onAdded={(s) => setSheet(s)}
              />
            )}

            {/* Invites */}
            <div className="space-y-2 border-t pt-3">
              <div className="flex items-center justify-between">
                <h4 className="text-xs font-semibold uppercase text-muted-foreground">
                  External evaluators
                </h4>
                <InviteEvaluatorButton
                  cvId={activeCvId}
                  roundId={activeRoundId}
                  hasProfileCompetences={profileCompetences.length > 0}
                  onSent={(rows) => setInvites((prev) => [...prev, ...rows])}
                />
              </div>
              {invites.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  No external evaluators invited yet.
                </p>
              ) : (
                <ul className="space-y-1">
                  {invites.map((inv) => {
                    // A bounced email trumps the lifecycle status — the
                    // evaluator never received the link, so "pending"
                    // would be misleading.
                    const chip =
                      inv.delivery_status === "delivery_failed" &&
                      inv.status === "pending"
                        ? {
                            label: "delivery failed",
                            className: "bg-rose-50 text-rose-700",
                          }
                        : inviteStatusChip(inv.status);
                    return (
                      <li
                        key={inv.id}
                        className="flex items-center justify-between rounded-md border px-2 py-1 text-xs"
                        data-testid={`assessment-round-invite-${inv.id}`}
                      >
                        <span className="flex items-center gap-2">
                          <Mail className="size-3 text-muted-foreground" />
                          {inv.evaluator_name || inv.email}
                        </span>
                        <Badge
                          data-testid={`assessment-round-invite-${inv.id}-status-badge`}
                          variant="outline"
                          className={chip.className}
                        >
                          {chip.label}
                        </Badge>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          </>
        )}
      </CardContent>
      <ConfirmDialog
        open={pendingNewRound}
        onOpenChange={setPendingNewRound}
        title="Add new interview round?"
        description={`This will create Interview ${nextInterviewNumber(rounds)}.`}
        confirmLabel="Add round"
        onConfirm={() => {
          setPendingNewRound(false);
          void createRound("interview");
        }}
        testId="assessment-round-new-confirm-modal"
      />
    </Card>
  );
}

function nextInterviewNumber(rounds: RoundDto[]): number {
  const highest = rounds
    .filter((r) => r.type === "interview" && r.round_number !== null)
    .reduce((acc, r) => Math.max(acc, r.round_number ?? 0), 0);
  return highest + 1;
}

function labelForRound(r: RoundDto): string {
  if (r.type === "pre_interview") return "Pre-interview";
  if (r.type === "final") return "Final";
  return `Interview ${r.round_number ?? "?"}`;
}

function AddSelfAsEvaluator({
  roundId,
  onAdded,
}: {
  roundId: string | null;
  onAdded: (sheet: AssessmentSheet) => void;
}) {
  const [busy, setBusy] = useState(false);
  async function add() {
    if (!roundId) return;
    setBusy(true);
    try {
      const me = await api.get<{ id: string }>("/auth/me");
      await api.post(`/v1/assessment-rounds/${roundId}/evaluators`, {
        user_id: me.id,
      });
      const list = await api.get<AssessmentSheet[]>(
        `/v1/assessment-rounds/${roundId}/assessments`,
      );
      const mine = list.find((a) => a.evaluator_user_id === me.id);
      if (mine) onAdded(mine);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed");
    } finally {
      setBusy(false);
    }
  }
  return (
    <Button onClick={add} disabled={busy || !roundId} size="sm">
      {busy ? <Loader2 className="size-4 animate-spin" /> : <UserPlus className="size-4" />}
      Start scoring this round
    </Button>
  );
}

// HRP-350: real format check, not just a length guard — mirrors the
// backend's EmailStr validation so the error surfaces before the POST.
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

function InviteEvaluatorButton({
  cvId,
  roundId,
  hasProfileCompetences,
  onSent,
}: {
  cvId: string;
  roundId: string | null;
  hasProfileCompetences: boolean;
  onSent: (invites: InviteDto[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [emails, setEmails] = useState<{ email: string; name: string }[]>([
    { email: "", name: "" },
  ]);
  const [expiresIn, setExpiresIn] = useState(7);
  const [allowRe, setAllowRe] = useState(true);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  function update(i: number, patch: Partial<{ email: string; name: string }>) {
    setEmails((prev) => prev.map((e, idx) => (idx === i ? { ...e, ...patch } : e)));
  }
  function addRow() {
    setEmails((prev) => [...prev, { email: "", name: "" }]);
  }
  function removeRow(i: number) {
    // HRP-350: removing the last (or only) row resets it to placeholders
    // instead of silently doing nothing.
    setEmails((prev) =>
      prev.length === 1
        ? [{ email: "", name: "" }]
        : prev.filter((_, idx) => idx !== i),
    );
  }

  async function submit() {
    const filtered = emails
      .map((e) => ({ email: e.email.trim(), name: e.name.trim() }))
      .filter((e) => e.email && e.name);
    if (filtered.length === 0) {
      toast.error("Add at least one invitee with email and name");
      return;
    }
    const invalid = filtered.filter((e) => !EMAIL_RE.test(e.email));
    if (invalid.length > 0) {
      toast.error(`Invalid email address: ${invalid[0]!.email}`);
      return;
    }
    setBusy(true);
    try {
      const rows = await api.post<InviteDto[]>(
        `/v1/candidate-vacancies/${cvId}/manager-assessment-invites`,
        {
          invitees: filtered,
          round_id: roundId,
          expires_in_days: expiresIn,
          allow_reediting: allowRe,
          personal_message: message || null,
        },
      );
      onSent(rows);
      toast.success(`${rows.length} invitation(s) sent`);
      setOpen(false);
      setEmails([{ email: "", name: "" }]);
      setMessage("");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to send");
    } finally {
      setBusy(false);
    }
  }

  const inviteDisabledHint = !hasProfileCompetences
    ? "Vacancy profile has no competences yet. Open the vacancy profile to add them, then come back here to invite external evaluator."
    : !roundId
      ? "Create an assessment round first."
      : undefined;

  return (
    <>
      {/* Disabled buttons swallow hover (pointer-events:none), so the
          explainer tooltip lives on the wrapper span. */}
      <span title={inviteDisabledHint}>
        <Button
          size="sm"
          variant="outline"
          onClick={() => setOpen(true)}
          disabled={!roundId || !hasProfileCompetences}
          data-testid="invite-evaluator-modal-open"
        >
          <UserPlus className="size-3.5" /> Invite external evaluator
        </Button>
      </span>
      {open && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          data-testid="invite-evaluator-modal"
        >
          {/* HRP-350: wide enough that the Remove button stays inside the
              modal; long invitee lists scroll instead of overflowing. */}
          <div className="max-h-[90vh] w-full max-w-2xl space-y-3 overflow-y-auto rounded-lg bg-background p-4 shadow-xl">
            <div className="flex items-center justify-between">
              <h3 className="text-base font-semibold">Invite external evaluator</h3>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="text-muted-foreground"
              >
                <X className="size-4" />
              </button>
            </div>
            <div className="space-y-2">
              {emails.map((row, i) => (
                <div key={i} className="grid grid-cols-[1fr_1fr_auto] gap-2">
                  <input
                    type="email"
                    className="rounded-md border px-2 py-1 text-sm"
                    placeholder="email@example.com"
                    value={row.email}
                    onChange={(e) => update(i, { email: e.target.value })}
                    data-testid={`invite-evaluator-modal-email-${i}`}
                  />
                  <input
                    type="text"
                    className="rounded-md border px-2 py-1 text-sm"
                    placeholder="Full name"
                    value={row.name}
                    onChange={(e) => update(i, { name: e.target.value })}
                    data-testid={`invite-evaluator-modal-name-${i}`}
                  />
                  <button
                    type="button"
                    onClick={() => removeRow(i)}
                    className="rounded-md border px-2 text-xs"
                    data-testid={`invite-evaluator-modal-remove-${i}`}
                  >
                    Remove
                  </button>
                </div>
              ))}
              <button
                type="button"
                onClick={addRow}
                className="text-xs text-primary underline"
                data-testid="invite-evaluator-modal-add-row-btn"
              >
                + Add another
              </button>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <label className="space-y-1 text-xs">
                Link expires in
                <select
                  className="block w-full rounded-md border px-2 py-1"
                  value={expiresIn}
                  onChange={(e) => setExpiresIn(Number(e.target.value))}
                  data-testid="invite-evaluator-modal-expiration-select"
                >
                  {[1, 3, 7, 14, 30].map((d) => (
                    <option key={d} value={d}>
                      {d} days
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex items-center gap-2 text-xs">
                <input
                  type="checkbox"
                  checked={allowRe}
                  onChange={(e) => setAllowRe(e.target.checked)}
                  data-testid="invite-evaluator-modal-reediting-toggle"
                />
                Allow re-editing after submit
              </label>
            </div>
            <textarea
              className="w-full rounded-md border p-2 text-sm"
              placeholder="Personal message (optional)"
              maxLength={500}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              data-testid="invite-evaluator-modal-message"
              rows={3}
            />
            <div className="flex justify-end gap-2">
              <Button
                variant="ghost"
                onClick={() => setOpen(false)}
                disabled={busy}
              >
                Cancel
              </Button>
              <Button
                onClick={submit}
                disabled={busy}
                data-testid="invite-evaluator-modal-submit"
              >
                {busy ? <Loader2 className="size-4 animate-spin" /> : null}
                Send invitations
              </Button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
