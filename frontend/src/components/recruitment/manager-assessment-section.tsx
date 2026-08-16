"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import {
  nextInterviewNumber,
  sortRounds,
} from "@/lib/manager-assessment-rounds";
import { useAuth } from "@/context/auth-context";
import {
  clearIndicatorsFor,
  upsertCompetenceComment,
  CompetenceScoreList,
  findCompetenceComment,
  replaceCompetenceRow,
  replaceIndicatorRow,
  toProfileCompetences,
  upsertCompetence,
  upsertIndicator,
  type CompetenceAggregate,
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Loader2, Mail, MoreVertical, Plus, UserPlus, X } from "lucide-react";
import { toast } from "sonner";

type RoundType = "pre_interview" | "interview" | "final";

// HRP-376: round lifecycle transitions offered by the tab kebab.
type RoundAction = "complete" | "reopen" | "archive" | "restore";

const ROUND_ACTION_TOASTS: Record<RoundAction, string> = {
  complete: "managerAssessmentRoundCompleted",
  reopen: "managerAssessmentRoundReopened",
  archive: "managerAssessmentRoundArchived",
  restore: "managerAssessmentRoundRestored",
};

interface RoundDto {
  id: string;
  type: RoundType;
  round_number: number | null;
  status: "in_progress" | "complete" | "archived";
  completed_at: string | null;
  archived_at: string | null;
  invites: InviteDto[];
  evaluators: RoundEvaluator[];
}

// HRP-373: a round can hold several internal evaluators; the header shows
// one avatar per evaluator so it is obvious who else is scoring.
interface RoundEvaluator {
  user_id: string;
  full_name: string | null;
  initials: string;
  submitted: boolean;
}

interface EligibleEvaluator {
  id: string;
  email: string;
  full_name: string;
  already_evaluator: boolean;
}

interface InviteDto {
  id: string;
  email: string;
  evaluator_name: string | null;
  status: string;
  /** HRP-577: set once the evaluator submitted, and it survives a revoke. */
  submitted_at: string | null;
  revoked_at: string | null;
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
  /** HRP-377: lets the recruiter pull one external evaluator's sheet. */
  evaluator_invite_id: string | null;
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

// HRP-374: cross-evaluator roll-up for the active round — the round header
// average plus one entry per scored competence.
interface RoundAggregate {
  average: number | null;
  average_weight: number | null;
  divergence_threshold: number;
  competences: {
    competence_id: string;
    average: number;
    average_weight: number | null;
    diverges: boolean;
    scorers: {
      evaluator: string;
      evaluator_type: "internal" | "external";
      score: number;
    }[];
  }[];
}

// HRP-358: raw invite statuses are machine-codes; the recruiter-facing
// chip needs a readable label and a tone that survives at a glance. The
// map stores i18n keys — the caller resolves them with its own `t`.
const INVITE_STATUS_CHIPS: Record<
  string,
  { labelKey: string; className: string }
> = {
  pending: {
    labelKey: "managerAssessmentInviteStatusPending",
    className: "bg-muted text-muted-foreground",
  },
  opened: {
    labelKey: "managerAssessmentInviteStatusOpened",
    className: "bg-blue-50 text-blue-700",
  },
  in_progress: {
    labelKey: "managerAssessmentInviteStatusInProgress",
    className: "bg-amber-50 text-amber-700",
  },
  submitted: {
    labelKey: "managerAssessmentInviteStatusSubmitted",
    className: "bg-emerald-50 text-emerald-700",
  },
  expired: {
    labelKey: "managerAssessmentInviteStatusExpired",
    className: "bg-rose-50 text-rose-700",
  },
  declined: {
    labelKey: "managerAssessmentInviteStatusDeclined",
    className: "bg-rose-50 text-rose-700",
  },
  revoked: {
    labelKey: "managerAssessmentInviteStatusRevoked",
    className: "bg-muted text-muted-foreground",
  },
};

export function inviteStatusChip(
  t: (key: string) => string,
  status: string,
): {
  label: string;
  className: string;
} {
  const chip = INVITE_STATUS_CHIPS[status];
  return chip
    ? { label: t(chip.labelKey), className: chip.className }
    : { label: status, className: "bg-muted text-muted-foreground" };
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
  // Mirror of activeRoundId readable from inside async callbacks, so a late
  // response for a round the user already tabbed away from can be dropped.
  // Written synchronously by `selectRound` — a state read captured in a
  // `useCallback([])` closure would forever see the first render's value.
  const activeRoundIdRef = useRef<string | null>(null);
  const selectRound = useCallback((roundId: string | null) => {
    activeRoundIdRef.current = roundId;
    setActiveRoundId(roundId);
  }, []);
  const [sheet, setSheet] = useState<AssessmentSheet | null>(null);
  const [scaleLevels, setScaleLevels] = useState<ScaleLevel[]>([]);
  const [profileCompetences, setProfileCompetences] = useState<
    ProfileCompetence[]
  >([]);
  const [aggregate, setAggregate] = useState<RoundAggregate | null>(null);
  // HRP-186 REDO: spec §3 — `+ New round` must surface a confirm dialog
  // ("Add new interview round? This will create Interview {N+1}.") so a
  // recruiter cannot accidentally insert a 4th round during a hectic
  // interview day.
  const [pendingNewRound, setPendingNewRound] = useState(false);
  // HRP-377: the invite whose submitted sheet the recruiter is reading.
  const [viewingInvite, setViewingInvite] = useState<InviteDto | null>(null);
  const [savingState, setSavingState] = useState<"idle" | "saving" | "saved">(
    "idle",
  );
  const [loadingRounds, setLoadingRounds] = useState(false);
  const { user } = useAuth();
  const t = useTranslations("recruitment");

  // HRP-373: the "you were added as an evaluator" email links here with
  // `?round=`. Consumed once — after that the user's tab clicks win, so a
  // later reload of the round list does not yank them back.
  const searchParams = useSearchParams();
  const pendingDeepLinkRound = useRef<string | null>(
    searchParams.get("round"),
  );

  // HRP-348 REDO: one debounce timer per score row — a shared timer would
  // silently drop the previous row's PATCH when the evaluator moves fast
  // between competences/indicators inside the autosave window.
  // The armed save is kept next to its timer (HRP-579) so a vacancy switch
  // can fire it instead of throwing the evaluator's last edit away.
  const debounceTimers = useRef<
    Map<
      string,
      { timer: ReturnType<typeof setTimeout>; run: () => Promise<void> }
    >
  >(new Map());
  const pendingSaves = useRef(0);
  // The "Saved" badge fades on its own timer; it has to die with the
  // component too, or it calls setState on an unmounted tree.
  const savedResetTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Leaving the card mid-edit must not leave PATCHes armed: the timers
  // outlive the component and fire against a sheet nobody is looking at.
  useEffect(() => {
    const timers = debounceTimers.current;
    return () => {
      for (const pending of timers.values()) clearTimeout(pending.timer);
      timers.clear();
      pendingSaves.current = 0;
      if (savedResetTimer.current) clearTimeout(savedResetTimer.current);
    };
  }, []);

  const activeVacancy = useMemo(
    () => vacancies.find((v) => v.id === activeCvId) ?? null,
    [vacancies, activeCvId],
  );
  const activeRound = useMemo(
    () => rounds.find((r) => r.id === activeRoundId) ?? null,
    [rounds, activeRoundId],
  );
  // HRP-377 REDO: the invite list is derived from the round record, never
  // held in a second state. A local copy drifted from `rounds`, so every
  // optimistic write (revoke, resend, send) was rolled back to the stale
  // server row the moment the round list was re-read.
  const invites = activeRound?.invites ?? [];
  // HRP-376: a completed or archived round is read-only end to end — own
  // sheet, new evaluators, new external links.
  const roundClosed =
    activeRound !== null && activeRound.status !== "in_progress";
  // HRP-373: a pre-interview round holds exactly one evaluator (HRP-369),
  // and a completed or archived round takes no new ones at all (HRP-376).
  const canAddEvaluator =
    activeRound !== null &&
    activeRound.type !== "pre_interview" &&
    !roundClosed;

  // ── Load rounds for the active CV ────────────────────────────────────
  const loadRounds = useCallback(
    async (cvId: string) => {
      setLoadingRounds(true);
      try {
        const rows = sortRounds(
          await api.get<RoundDto[]>(
            `/v1/candidate-vacancies/${cvId}/assessment-rounds`,
          ),
        );
        setRounds(rows);
        const deepLink = pendingDeepLinkRound.current;
        // HRP-373 REDO: the current tab is read from the ref, not from a
        // captured state value — every reload (add evaluator, start
        // scoring) used to see `null` here and yank the recruiter to the
        // last round mid-assessment.
        const current = activeRoundIdRef.current;
        if (deepLink && rows.some((r) => r.id === deepLink)) {
          pendingDeepLinkRound.current = null;
          selectRound(deepLink);
        } else if (rows.length === 0) {
          // HRP-550: a vacancy with no rounds left the previous vacancy's
          // round selected, so its sheet stayed on screen — and every
          // autosave from it PATCHed into the round the recruiter had just
          // navigated away from. Dropping the selection clears the form.
          selectRound(null);
        } else if (!rows.some((r) => r.id === current)) {
          // HRP-376: an archived round is read-only, so default to the
          // last live one and only fall back to an archived tab when the
          // candidate has nothing else.
          const live = rows.filter((r) => r.status !== "archived");
          const fallback = live[live.length - 1] ?? rows[rows.length - 1]!;
          selectRound(fallback.id);
        }
      } catch {
        // The failure path needs the same reset as the empty one: keeping
        // the previous vacancy's round selected leaves its sheet on screen
        // and points every autosave at a round on the vacancy the recruiter
        // has already left (HRP-550 review).
        setRounds([]);
        selectRound(null);
      } finally {
        setLoadingRounds(false);
      }
    },
    [selectRound],
  );

  useEffect(() => {
    if (!activeCvId) return;
    // HRP-550: the submission drawer belongs to an invite on the vacancy
    // being left behind — it must not survive the switch either.
    setViewingInvite(null);
    // HRP-579: neither does the autosave state. The armed PATCHes belong to
    // the sheet being left, so fire them now (their closures carry that
    // sheet's id, and the 1.5 s debounce window is long enough to swallow
    // the evaluator's last click otherwise), then reset the indicator —
    // otherwise the previous vacancy's "Saving… / Saved" finishes playing
    // over the new one.
    for (const pending of debounceTimers.current.values()) {
      clearTimeout(pending.timer);
      void pending.run().catch(() => {
        toast.error(t("managerAssessmentScoreSaveFailed"));
      });
    }
    debounceTimers.current.clear();
    pendingSaves.current = 0;
    if (savedResetTimer.current) {
      clearTimeout(savedResetTimer.current);
      savedResetTimer.current = null;
    }
    setSavingState("idle");
    void loadRounds(activeCvId);
  }, [activeCvId, loadRounds, t]);

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
        // A tab switch while this was in flight makes the answer stale —
        // writing it would hand the visible form a foreign assessment id
        // and the autosave would PATCH into the wrong round.
        if (activeRoundIdRef.current !== roundId) return;
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
        if (activeRoundIdRef.current === roundId) setSheet(null);
      }
    },
    [user],
  );

  // HRP-374: the round header average spans every evaluator, so it can only
  // come from the server — a local sheet knows nothing about colleagues or
  // submitted external evaluators.
  const loadAggregate = useCallback(async (roundId: string) => {
    let agg: RoundAggregate | null = null;
    try {
      agg = await api.get<RoundAggregate>(
        `/v1/assessment-rounds/${roundId}/aggregate`,
      );
    } catch {
      agg = null;
    }
    if (activeRoundIdRef.current === roundId) setAggregate(agg);
  }, []);

  // Deliberately keyed on the round alone: `rounds` changes identity on
  // every reload and on every optimistic invite write, and re-running the
  // sheet fetch there would overwrite scores still sitting in the 1.5s
  // autosave debounce. The invite list reads straight off `activeRound`.
  useEffect(() => {
    if (!activeRoundId) {
      // HRP-550: no round means no sheet. Returning early left the last
      // round's form (and its aggregate) rendered under the new vacancy.
      setSheet(null);
      setAggregate(null);
      return;
    }
    void ensureSheet(activeRoundId);
    // Competence ids are stable across rounds, so a leftover aggregate would
    // render the previous round's averages against this round's sheet for a
    // full round-trip.
    setAggregate(null);
    void loadAggregate(activeRoundId);
  }, [activeRoundId, ensureSheet, loadAggregate]);

  const aggregatesByCompetence = useMemo(() => {
    const out: Record<string, CompetenceAggregate> = {};
    for (const c of aggregate?.competences ?? []) {
      out[c.competence_id] = {
        average: c.average,
        diverges: c.diverges,
        scorers: c.scorers,
      };
    }
    return out;
  }, [aggregate]);

  async function createRound(type: RoundType) {
    if (!activeCvId) return;
    try {
      const r = await api.post<RoundDto>(
        `/v1/candidate-vacancies/${activeCvId}/assessment-rounds`,
        { type },
      );
      // HRP-372: a round created now must slot into its place in the strip
      // (a late Pre-interview belongs first), not append to the end.
      setRounds((prev) => sortRounds([...prev, r]));
      selectRound(r.id);
    } catch (err) {
      toast.error(
        err instanceof Error
          ? err.message
          : t("managerAssessmentRoundCreateFailed"),
      );
    }
  }

  // HRP-376: one call for every kebab action. The server decides where
  // `restore` lands (complete vs in_progress), so the response is the only
  // source of truth for the new round state.
  const runRoundAction = useCallback(
    async (roundId: string, action: RoundAction) => {
      try {
        const r = await api.patch<RoundDto>(
          `/v1/assessment-rounds/${roundId}`,
          { action },
        );
        setRounds((prev) => prev.map((x) => (x.id === r.id ? r : x)));
        toast.success(t(ROUND_ACTION_TOASTS[action]));
        // The kebab fires for any tab, so only the round on screen may
        // touch the visible sheet — refetching for a background round
        // would bind the form (and its autosave) to a foreign assessment.
        if (activeRoundIdRef.current !== roundId) return;
        // Completing submits the acting evaluator's own sheet and revokes
        // the round's live external links, and archiving drops the round
        // out of the aggregate — refetch rather than guess.
        void ensureSheet(roundId);
        void loadAggregate(roundId);
      } catch (err) {
        toast.error(
          err instanceof Error ? err.message : t("managerAssessmentFailed"),
        );
      }
    },
    [t, ensureSheet, loadAggregate],
  );

  async function completeRound() {
    if (!activeRoundId) return;
    await runRoundAction(activeRoundId, "complete");
  }

  /** Write an invite change back onto its round — the single place the
   * list lives, so the chip cannot be reverted by the next round read. */
  const patchRoundInvites = useCallback(
    (roundId: string | null, patch: (rows: InviteDto[]) => InviteDto[]) => {
      if (!roundId) return;
      setRounds((prev) =>
        prev.map((r) =>
          r.id === roundId ? { ...r, invites: patch(r.invites ?? []) } : r,
        ),
      );
    },
    [],
  );

  function scheduleAutosave(key: string, fn: () => Promise<void>) {
    setSavingState("saving");
    const existing = debounceTimers.current.get(key);
    if (existing) clearTimeout(existing.timer);
    else pendingSaves.current += 1;
    debounceTimers.current.set(key, {
      run: fn,
      timer: setTimeout(async () => {
        debounceTimers.current.delete(key);
        try {
          await fn();
          if (--pendingSaves.current <= 0) {
            pendingSaves.current = 0;
            setSavingState("saved");
            if (savedResetTimer.current) clearTimeout(savedResetTimer.current);
            savedResetTimer.current = setTimeout(
              () => setSavingState("idle"),
              1200,
            );
          }
        } catch {
          toast.error(t("managerAssessmentScoreSaveFailed"));
          if (--pendingSaves.current <= 0) {
            pendingSaves.current = 0;
            setSavingState("idle");
          }
        }
      }, AUTOSAVE_MS),
    });
  }

  /** Cancel this competence's still-pending indicator saves (HRP-378). */
  function dropPendingIndicatorSaves(competenceId: string) {
    for (const key of [...debounceTimers.current.keys()]) {
      if (!key.startsWith(`ind:${competenceId}:`)) continue;
      clearTimeout(debounceTimers.current.get(key)!.timer);
      debounceTimers.current.delete(key);
      pendingSaves.current = Math.max(0, pendingSaves.current - 1);
    }
  }

  async function setCompetenceScore(competenceId: string, value: number | null) {
    if (!sheet) return;
    const { id: sheetId, round_id: roundId } = sheet;
    // HRP-378: picking an overall by hand makes it authoritative, so the
    // competence's indicator answers are dropped here and on the server.
    // Indicator saves still in flight would re-derive the overall and
    // resurrect those answers on screen, so cancel them first.
    dropPendingIndicatorSaves(competenceId);
    setSheet((prev) =>
      prev
        ? {
            ...prev,
            competence_scores: upsertCompetence(prev.competence_scores, {
              competence_id: competenceId,
              score_value: value,
              comment: findCompetenceComment(prev, competenceId),
            }),
            indicator_scores: clearIndicatorsFor(
              prev.indicator_scores,
              competenceId,
            ),
          }
        : prev,
    );
    // Score and comment hold separate debounce slots and each PATCH carries
    // only its own field, so neither can overwrite the other with a value it
    // captured before the other edit landed.
    scheduleAutosave(`comp:${competenceId}`, async () => {
      await api.patch<CompetenceScore>(
        `/v1/assessments/${sheetId}/competence-scores/${competenceId}`,
        { score_value: value, score_source: "manual" },
      );
      await loadAggregate(roundId);
    });
  }

  async function setCompetenceComment(competenceId: string, comment: string) {
    if (!sheet) return;
    const sheetId = sheet.id;
    setSheet((prev) =>
      prev
        ? {
            ...prev,
            competence_scores: upsertCompetenceComment(
              prev.competence_scores,
              competenceId,
              comment,
            ),
          }
        : prev,
    );
    scheduleAutosave(`note:${competenceId}`, async () => {
      await api.patch<CompetenceScore>(
        `/v1/assessments/${sheetId}/competence-scores/${competenceId}`,
        { comment },
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
    // Key carries the competence so a manual overall can cancel exactly this
    // competence's pending indicator saves (HRP-378).
    scheduleAutosave(`ind:${competenceId}:${indicatorId}`, async () => {
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
        // This save owns the score, never the note: a comment being typed
        // right now is not in the row we just fetched, and echoing that row
        // back verbatim would blank the textarea under the evaluator.
        const merged =
          freshOverall &&
          ({
            ...freshOverall,
            comment: findCompetenceComment(prev, competenceId) || null,
          } as CompetenceScore);
        return {
          ...prev,
          indicator_scores: freshInd
            ? replaceIndicatorRow(prev.indicator_scores, freshInd)
            : prev.indicator_scores,
          competence_scores:
            merged && !overallPending
              ? replaceCompetenceRow(prev.competence_scores, merged)
              : prev.competence_scores,
        };
      });
      await loadAggregate(sheet.round_id);
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
      ? t("managerAssessmentCompleteHintCritical", {
          count: unscoredCritical.length,
          names: unscoredCritical.map((c) => c.name).join(", "),
        })
      : t("managerAssessmentCompleteHintNone")
    : undefined;

  return (
    <Card data-testid="candidate-section-assessments">
      <CardHeader className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
        <CardTitle className="text-base">
          {t("managerAssessmentTitle")}
        </CardTitle>
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
            {t("managerAssessmentNoVacancy")}
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
                <span key={r.id} className="flex items-center gap-0.5">
                  <button
                    type="button"
                    onClick={() => selectRound(r.id)}
                    className={`rounded-full px-3 py-1 text-xs ${
                      r.id === activeRoundId
                        ? "bg-primary text-primary-foreground"
                        : "bg-muted text-muted-foreground"
                    } ${r.status === "archived" ? "line-through opacity-60" : ""}`}
                    data-testid={`assessment-round-tab-${r.id}`}
                  >
                    {labelForRound(t, r)}
                    {r.status === "complete" && <span className="ml-1">·✓</span>}
                  </button>
                  {/* HRP-376: Complete / Reopen / Archive / Restore. */}
                  <RoundKebab
                    round={r}
                    onAction={runRoundAction}
                    // HRP-348: Complete obeys the same gate as the button.
                    // `canComplete` is only knowable for the round whose
                    // sheet is loaded, so any other tab has to be opened
                    // first rather than completed blind from the strip.
                    canComplete={r.id === activeRoundId ? canComplete : false}
                    completeHint={
                      r.id === activeRoundId
                        ? completeHint
                        : t("managerAssessmentRoundCompleteHintInactive")
                    }
                  />
                </span>
              ))}
              <Button
                size="sm"
                variant="outline"
                onClick={() => setPendingNewRound(true)}
                data-testid="assessment-round-new-btn"
              >
                <Plus className="size-3" /> {t("managerAssessmentNewRound")}
              </Button>
              {!rounds.some((r) => r.type === "pre_interview") && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => createRound("pre_interview")}
                >
                  {t("managerAssessmentAddPreInterview")}
                </Button>
              )}
              {!rounds.some((r) => r.type === "final") && rounds.length > 0 && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => createRound("final")}
                >
                  {t("managerAssessmentAddFinal")}
                </Button>
              )}
            </div>

            {/* Evaluators on this round (HRP-373) */}
            <div
              className="flex flex-wrap items-center justify-between gap-2"
              data-testid="assessment-round-evaluators"
            >
              <div className="flex min-h-6 items-center gap-2">
                {!sheet && !roundClosed && (
                  <AddSelfAsEvaluator
                    roundId={activeRoundId}
                    onAdded={(s) => {
                      setSheet(s);
                      if (activeCvId) void loadRounds(activeCvId);
                    }}
                  />
                )}
                {/* HRP-370: the autosave indicator used to be a block of its
                    own right above the scores, so every save nudged the whole
                    sheet down and back. It now rides in the empty left slot of
                    the evaluators row, which already has a settled height. */}
                <span
                  aria-live="polite"
                  className="text-xs text-muted-foreground"
                  data-testid="assessment-autosave-status"
                >
                  {savingState === "saving"
                    ? t("managerAssessmentSaving")
                    : savingState === "saved"
                      ? t("managerAssessmentSaved")
                      : null}
                </span>
              </div>
              <div className="flex flex-wrap items-center gap-1.5">
                {(activeRound?.evaluators ?? []).map((ev) => (
                  <EvaluatorAvatar
                    key={ev.user_id}
                    evaluator={ev}
                    isSelf={ev.user_id === user?.id}
                    t={t}
                  />
                ))}
                {canAddEvaluator && (
                  <AddEvaluatorButton
                    roundId={activeRoundId!}
                    onAdded={() => {
                      if (activeCvId) void loadRounds(activeCvId);
                    }}
                  />
                )}
              </div>
            </div>

            {/* Form */}
            {sheet ? (
              <div className="space-y-3">
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <span data-testid="assessment-progress-counter">
                    {t("managerAssessmentProgress", {
                      completed: completedCount,
                      total: totalCount,
                    })}
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
                  {/* HRP-374: the round's Average score — the same mean the
                      vacancy Candidates block shows, em dash until at least
                      one competence is scored by at least one evaluator. */}
                  <span
                    className="flex items-baseline gap-1"
                    data-testid="assessment-round-average-score"
                  >
                    {t("managerAssessmentAverageScore", {
                      score:
                        aggregate?.average != null
                          ? aggregate.average.toFixed(1)
                          : "—",
                    })}
                    {aggregate?.average_weight != null && (
                      <span
                        className="text-[10px] text-muted-foreground"
                        data-testid="assessment-round-average-weight"
                      >
                        {t("managerAssessmentAverageWeight", {
                          percent: aggregate.average_weight.toFixed(0),
                        })}
                      </span>
                    )}
                  </span>
                  {/* HRP-376: once the round is closed the button is gone
                      and its place is taken by the round's status, so it is
                      obvious why the sheet no longer accepts input. */}
                  {roundClosed ? (
                    <Badge
                      variant="outline"
                      className={
                        activeRound?.status === "archived"
                          ? "bg-muted text-muted-foreground"
                          : "bg-emerald-50 text-emerald-700"
                      }
                      data-testid="assessment-round-status-badge"
                    >
                      {activeRound?.status === "archived"
                        ? t("managerAssessmentRoundArchivedBadge")
                        : t("managerAssessmentRoundCompletedBadge")}
                    </Badge>
                  ) : (
                    // Disabled buttons swallow hover (pointer-events:none),
                    // so the explainer tooltip lives on the wrapper span.
                    <span title={completeHint}>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={completeRound}
                        disabled={!canComplete}
                        data-testid="assessment-round-complete-btn"
                      >
                        {t("managerAssessmentMarkComplete")}
                      </Button>
                    </span>
                  )}
                  {activeRound?.status === "archived" && (
                    <span
                      className="text-[11px] italic"
                      data-testid="assessment-round-excluded-note"
                    >
                      {t("managerAssessmentRoundExcluded")}
                    </span>
                  )}
                </div>
                <CompetenceScoreList
                  competences={profileCompetences}
                  scaleLevels={scaleLevels}
                  competenceScores={sheet.competence_scores}
                  indicatorScores={sheet.indicator_scores}
                  disabled={roundClosed}
                  emptyHint={t("managerAssessmentEmptyHint")}
                  aggregates={aggregatesByCompetence}
                  onCompetenceScore={(compId, value) =>
                    void setCompetenceScore(compId, value)
                  }
                  onCompetenceComment={(compId, comment) =>
                    void setCompetenceComment(compId, comment)
                  }
                  onIndicatorScore={(compId, indId, value) =>
                    void setIndicatorScore(compId, indId, value)
                  }
                />
              </div>
            ) : null}

            {/* Invites */}
            <div className="space-y-2 border-t pt-3">
              <div className="flex items-center justify-between">
                <h4 className="text-xs font-semibold uppercase text-muted-foreground">
                  {t("managerAssessmentExternalEvaluators")}
                </h4>
                <InviteEvaluatorButton
                  cvId={activeCvId}
                  roundId={activeRoundId}
                  roundClosed={roundClosed}
                  hasProfileCompetences={profileCompetences.length > 0}
                  onSent={(rows) =>
                    patchRoundInvites(activeRoundId, (prev) => [
                      ...prev,
                      ...rows,
                    ])
                  }
                />
              </div>
              {invites.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  {t("managerAssessmentNoInvites")}
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
                            label: t(
                              "managerAssessmentInviteStatusDeliveryFailed",
                            ),
                            className: "bg-rose-50 text-rose-700",
                          }
                        : inviteStatusChip(t, inv.status);
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
                        <span className="flex items-center gap-1">
                          <Badge
                            data-testid={`assessment-round-invite-${inv.id}-status-badge`}
                            variant="outline"
                            className={chip.className}
                          >
                            {chip.label}
                          </Badge>
                          {/* HRP-377: Resend / Revoke / View submission. */}
                          <InviteKebab
                            invite={inv}
                            onChanged={(updated) =>
                              patchRoundInvites(activeRoundId, (prev) =>
                                prev.map((x) =>
                                  x.id === updated.id ? updated : x,
                                ),
                              )
                            }
                            onViewSubmission={() => setViewingInvite(inv)}
                          />
                        </span>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          </>
        )}
      </CardContent>
      {viewingInvite && activeRoundId && (
        <SubmissionDrawer
          invite={viewingInvite}
          roundId={activeRoundId}
          competences={profileCompetences}
          scaleLevels={scaleLevels}
          onClose={() => setViewingInvite(null)}
        />
      )}
      <ConfirmDialog
        open={pendingNewRound}
        onOpenChange={setPendingNewRound}
        title={t("managerAssessmentNewRoundConfirmTitle")}
        description={t("managerAssessmentNewRoundConfirmDescription", {
          number: nextInterviewNumber(rounds),
        })}
        confirmLabel={t("managerAssessmentAddRound")}
        onConfirm={() => {
          setPendingNewRound(false);
          void createRound("interview");
        }}
        testId="assessment-round-new-confirm-modal"
      />
    </Card>
  );
}

function labelForRound(
  t: (key: string, values?: Record<string, string | number>) => string,
  r: RoundDto,
): string {
  if (r.type === "pre_interview") return t("managerAssessmentRoundPreInterview");
  if (r.type === "final") return t("managerAssessmentRoundFinal");
  return t("managerAssessmentRoundInterview", {
    number: r.round_number ?? "?",
  });
}

function AddSelfAsEvaluator({
  roundId,
  onAdded,
}: {
  roundId: string | null;
  onAdded: (sheet: AssessmentSheet) => void;
}) {
  const [busy, setBusy] = useState(false);
  const t = useTranslations("recruitment");
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
      toast.error(
        err instanceof Error ? err.message : t("managerAssessmentFailed"),
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <Button onClick={add} disabled={busy || !roundId} size="sm">
      {busy ? <Loader2 className="size-4 animate-spin" /> : <UserPlus className="size-4" />}
      {t("managerAssessmentStartScoring")}
    </Button>
  );
}

/** Invite statuses no action can move any more. */
const TERMINAL_INVITE_STATUSES = new Set([
  "submitted",
  "declined",
  "revoked",
  "expired",
]);

/** HRP-377: per-invite kebab — Resend, Revoke, View submission. */
function InviteKebab({
  invite,
  onChanged,
  onViewSubmission,
}: {
  invite: InviteDto;
  onChanged: (invite: InviteDto) => void;
  onViewSubmission: () => void;
}) {
  const t = useTranslations("recruitment");
  const [busy, setBusy] = useState(false);
  const terminal = TERMINAL_INVITE_STATUSES.has(invite.status);
  // A bounce is worth retrying even once the evaluator has opened nothing:
  // the mail never arrived, so the lifecycle status is not the whole story.
  const canResend =
    !terminal &&
    (invite.status === "pending" ||
      invite.delivery_status === "delivery_failed");
  const canRevoke = !terminal;
  // HRP-577: revoking drops the sheet out of every aggregate, it does not
  // delete it. Keying `View submission` on the current status hid a
  // submitted evaluation the moment it was revoked; key it on the fact
  // that a submission exists instead — the drawer marks it as no longer
  // counted.
  const canView =
    invite.status === "submitted" || Boolean(invite.submitted_at);

  async function run(action: "resend" | "revoke") {
    setBusy(true);
    try {
      const updated = await api.post<InviteDto>(
        `/v1/manager-assessment-invites/${invite.id}/${action}`,
        {},
      );
      onChanged(updated);
      toast.success(
        t(
          action === "resend"
            ? "managerAssessmentInviteResent"
            : "managerAssessmentInviteRevoked",
        ),
      );
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("managerAssessmentFailed"),
      );
    } finally {
      setBusy(false);
    }
  }

  if (!canResend && !canRevoke && !canView) return null;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        data-testid={`assessment-round-invite-${invite.id}-kebab`}
        aria-label={t("managerAssessmentInviteActionsAria")}
        disabled={busy}
        render={<Button variant="ghost" size="sm" className="size-6 px-0" />}
      >
        <MoreVertical className="size-3.5" />
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="end"
        data-testid={`assessment-round-invite-${invite.id}-kebab-menu`}
      >
        {canResend && (
          <DropdownMenuItem
            onClick={() => void run("resend")}
            data-testid={`assessment-round-invite-${invite.id}-resend`}
          >
            {t("managerAssessmentInviteResend")}
          </DropdownMenuItem>
        )}
        {canRevoke && (
          <DropdownMenuItem
            onClick={() => void run("revoke")}
            data-testid={`assessment-round-invite-${invite.id}-revoke`}
          >
            {t("managerAssessmentInviteRevoke")}
          </DropdownMenuItem>
        )}
        {canView && (
          <DropdownMenuItem
            onClick={onViewSubmission}
            data-testid={`assessment-round-invite-${invite.id}-view`}
          >
            {t("managerAssessmentInviteViewSubmission")}
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** HRP-377: read-only panel showing what an external evaluator filled in. */
function SubmissionDrawer({
  invite,
  roundId,
  competences,
  scaleLevels,
  onClose,
}: {
  invite: InviteDto;
  roundId: string;
  competences: ProfileCompetence[];
  scaleLevels: ScaleLevel[];
  onClose: () => void;
}) {
  const t = useTranslations("recruitment");
  const [sheet, setSheet] = useState<AssessmentSheet | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const rows = await api.get<AssessmentSheet[]>(
          `/v1/assessment-rounds/${roundId}/assessments`,
        );
        if (cancelled) return;
        setSheet(
          rows.find((a) => a.evaluator_invite_id === invite.id) ?? null,
        );
      } catch {
        if (!cancelled) setSheet(null);
      } finally {
        if (!cancelled) setLoaded(true);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [roundId, invite.id]);

  return (
    <div
      className="fixed inset-y-0 right-0 z-50 flex w-full max-w-xl flex-col border-l bg-background shadow-xl"
      data-testid="assessment-invite-submission-drawer"
    >
      <div className="flex items-center justify-between border-b p-4">
        <div>
          <h3 className="text-base font-semibold">
            {t("managerAssessmentInviteViewSubmission")}
          </h3>
          <p className="text-xs text-muted-foreground">
            {invite.evaluator_name || invite.email}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="text-muted-foreground"
          data-testid="assessment-invite-submission-drawer-close"
        >
          <X className="size-4" />
        </button>
      </div>
      <div className="flex-1 space-y-3 overflow-y-auto p-4">
        {/* HRP-577: a revoked invitation keeps its submitted sheet
            readable, but the scores stopped counting the moment it was
            revoked — say so where the numbers are being read. */}
        {invite.revoked_at && (
          <p
            className="rounded-md border bg-muted/20 p-2 text-xs italic text-muted-foreground"
            data-testid="assessment-invite-submission-not-counted"
          >
            {t("managerAssessmentInviteSubmissionNotCounted")}
          </p>
        )}
        {!loaded ? (
          <Loader2 className="size-4 animate-spin text-muted-foreground" />
        ) : sheet ? (
          <>
            <CompetenceScoreList
              competences={competences}
              scaleLevels={scaleLevels}
              competenceScores={sheet.competence_scores}
              indicatorScores={sheet.indicator_scores}
              disabled
              emptyHint={t("managerAssessmentEmptyHint")}
              onCompetenceScore={() => undefined}
              onCompetenceComment={() => undefined}
              onIndicatorScore={() => undefined}
            />
            {sheet.final_notes && (
              <div className="rounded-md border bg-muted/20 p-3 text-xs whitespace-pre-wrap">
                {sheet.final_notes}
              </div>
            )}
          </>
        ) : (
          <p className="text-sm text-muted-foreground">
            {t("managerAssessmentInviteNoSubmission")}
          </p>
        )}
      </div>
    </div>
  );
}

/** HRP-376: per-round kebab — Complete/Archive, Reopen/Archive, Restore. */
function RoundKebab({
  round,
  onAction,
  canComplete,
  completeHint,
}: {
  round: RoundDto;
  onAction: (roundId: string, action: RoundAction) => void;
  /** HRP-348: same gate as the `Mark as complete` button. */
  canComplete: boolean;
  /** Why completion is blocked, shown on hover like the button's. */
  completeHint?: string;
}) {
  const t = useTranslations("recruitment");
  const archived = round.status === "archived";
  const complete = round.status === "complete";
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        data-testid={`assessment-round-kebab-${round.id}`}
        aria-label={t("managerAssessmentRoundActionsAria")}
        render={<Button variant="ghost" size="sm" className="size-6 px-0" />}
      >
        <MoreVertical className="size-3.5" />
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="end"
        data-testid={`assessment-round-kebab-menu-${round.id}`}
      >
        {archived ? (
          <DropdownMenuItem
            onClick={() => onAction(round.id, "restore")}
            data-testid={`assessment-round-restore-${round.id}`}
          >
            {t("managerAssessmentRoundRestore")}
          </DropdownMenuItem>
        ) : (
          <>
            {complete ? (
              <DropdownMenuItem
                onClick={() => onAction(round.id, "reopen")}
                data-testid={`assessment-round-reopen-${round.id}`}
              >
                {t("managerAssessmentRoundReopen")}
              </DropdownMenuItem>
            ) : (
              // A disabled item swallows hover (pointer-events:none), so
              // the explainer rides on the wrapper — same as the button.
              <span role="none" title={canComplete ? undefined : completeHint}>
                <DropdownMenuItem
                  disabled={!canComplete}
                  onClick={() => onAction(round.id, "complete")}
                  data-testid={`assessment-round-complete-${round.id}`}
                >
                  {t("managerAssessmentRoundComplete")}
                </DropdownMenuItem>
              </span>
            )}
            <DropdownMenuItem
              onClick={() => onAction(round.id, "archive")}
              data-testid={`assessment-round-archive-${round.id}`}
            >
              {t("managerAssessmentRoundArchive")}
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** HRP-373: one evaluator on the round header. Own avatar is outlined so
 * it stands out from colleagues at a glance. */
function EvaluatorAvatar({
  evaluator,
  isSelf,
  t,
}: {
  evaluator: RoundEvaluator;
  isSelf: boolean;
  t: (key: string, values?: Record<string, string | number>) => string;
}) {
  const name = evaluator.full_name ?? evaluator.initials;
  return (
    <span
      title={
        isSelf
          ? t("managerAssessmentEvaluatorYou", { name })
          : evaluator.submitted
            ? t("managerAssessmentEvaluatorSubmitted", { name })
            : name
      }
      className={`inline-flex size-7 items-center justify-center rounded-full text-[11px] font-medium ${
        isSelf
          ? "bg-primary text-primary-foreground ring-2 ring-primary/40"
          : "bg-muted text-muted-foreground"
      }`}
      data-testid={`assessment-round-evaluator-${evaluator.user_id}`}
    >
      {evaluator.initials}
    </span>
  );
}

/** HRP-373: `+ Add evaluator` — picks a colleague and mails them the link. */
function AddEvaluatorButton({
  roundId,
  onAdded,
}: {
  roundId: string;
  onAdded: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [options, setOptions] = useState<EligibleEvaluator[] | null>(null);
  const [selected, setSelected] = useState("");
  const [busy, setBusy] = useState(false);
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");

  async function openDialog() {
    setOpen(true);
    setSelected("");
    setOptions(null);
    try {
      setOptions(
        await api.get<EligibleEvaluator[]>(
          `/v1/assessment-rounds/${roundId}/eligible-evaluators`,
        ),
      );
    } catch {
      setOptions([]);
    }
  }

  async function submit() {
    if (!selected) return;
    setBusy(true);
    try {
      await api.post(`/v1/assessment-rounds/${roundId}/evaluators`, {
        user_id: selected,
      });
      toast.success(t("managerAssessmentEvaluatorAdded"));
      setOpen(false);
      onAdded();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("managerAssessmentFailed"),
      );
    } finally {
      setBusy(false);
    }
  }

  const selectable = (options ?? []).filter((o) => !o.already_evaluator);

  return (
    <>
      <Button
        size="sm"
        variant="outline"
        onClick={openDialog}
        data-testid="assessment-add-evaluator-btn"
      >
        <UserPlus className="size-3.5" /> {t("managerAssessmentAddEvaluator")}
      </Button>
      {open && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          data-testid="assessment-add-evaluator-modal"
        >
          <div className="w-full max-w-md space-y-3 rounded-lg bg-background p-4 shadow-xl">
            <div className="flex items-center justify-between">
              <h3 className="text-base font-semibold">
                {t("managerAssessmentAddEvaluator")}
              </h3>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="text-muted-foreground"
              >
                <X className="size-4" />
              </button>
            </div>
            {options === null ? (
              <Loader2 className="size-4 animate-spin text-muted-foreground" />
            ) : selectable.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                {t("managerAssessmentNoEligibleEvaluators")}
              </p>
            ) : (
              <select
                className="w-full rounded-md border px-2 py-1 text-sm"
                value={selected}
                onChange={(e) => setSelected(e.target.value)}
                data-testid="assessment-add-evaluator-select"
              >
                <option value="">
                  {t("managerAssessmentSelectEvaluator")}
                </option>
                {selectable.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.full_name} ({o.email})
                  </option>
                ))}
              </select>
            )}
            <div className="flex justify-end gap-2">
              <Button
                variant="ghost"
                onClick={() => setOpen(false)}
                disabled={busy}
              >
                {tc("cancel")}
              </Button>
              <Button
                onClick={submit}
                disabled={busy || !selected}
                data-testid="assessment-add-evaluator-submit"
              >
                {busy ? <Loader2 className="size-4 animate-spin" /> : null}
                {t("managerAssessmentAddEvaluatorConfirm")}
              </Button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

// HRP-350: real format check, not just a length guard — mirrors the
// backend's EmailStr validation so the error surfaces before the POST.
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

function InviteEvaluatorButton({
  cvId,
  roundId,
  roundClosed,
  hasProfileCompetences,
  onSent,
}: {
  cvId: string;
  roundId: string | null;
  /** HRP-376: a completed / archived round issues no new links. */
  roundClosed: boolean;
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
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");

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
      toast.error(t("managerAssessmentInviteeRequired"));
      return;
    }
    const invalid = filtered.filter((e) => !EMAIL_RE.test(e.email));
    if (invalid.length > 0) {
      toast.error(
        t("managerAssessmentInvalidEmail", { email: invalid[0]!.email }),
      );
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
      toast.success(t("managerAssessmentInvitesSent", { count: rows.length }));
      setOpen(false);
      setEmails([{ email: "", name: "" }]);
      setMessage("");
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("managerAssessmentSendFailed"),
      );
    } finally {
      setBusy(false);
    }
  }

  const inviteDisabledHint = !hasProfileCompetences
    ? t("managerAssessmentInviteDisabledNoCompetences")
    : !roundId
      ? t("managerAssessmentInviteDisabledNoRound")
      : roundClosed
        ? t("managerAssessmentInviteDisabledRoundClosed")
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
          disabled={!roundId || !hasProfileCompetences || roundClosed}
          data-testid="invite-evaluator-modal-open"
        >
          <UserPlus className="size-3.5" /> {t("managerAssessmentInviteEvaluator")}
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
              <h3 className="text-base font-semibold">
                {t("managerAssessmentInviteEvaluator")}
              </h3>
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
                    placeholder={t("managerAssessmentEmailPlaceholder")}
                    value={row.email}
                    onChange={(e) => update(i, { email: e.target.value })}
                    data-testid={`invite-evaluator-modal-email-${i}`}
                  />
                  <input
                    type="text"
                    className="rounded-md border px-2 py-1 text-sm"
                    placeholder={t("candidateFieldFullName")}
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
                    {t("managerAssessmentRemove")}
                  </button>
                </div>
              ))}
              <button
                type="button"
                onClick={addRow}
                className="text-xs text-primary underline"
                data-testid="invite-evaluator-modal-add-row-btn"
              >
                {t("managerAssessmentAddAnother")}
              </button>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <label className="space-y-1 text-xs">
                {t("managerAssessmentLinkExpiresIn")}
                <select
                  className="block w-full rounded-md border px-2 py-1"
                  value={expiresIn}
                  onChange={(e) => setExpiresIn(Number(e.target.value))}
                  data-testid="invite-evaluator-modal-expiration-select"
                >
                  {[1, 3, 7, 14, 30].map((d) => (
                    <option key={d} value={d}>
                      {t("managerAssessmentDays", { count: d })}
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
                {t("managerAssessmentAllowReediting")}
              </label>
            </div>
            <textarea
              className="w-full rounded-md border p-2 text-sm"
              placeholder={t("managerAssessmentPersonalMessagePlaceholder")}
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
                {tc("cancel")}
              </Button>
              <Button
                onClick={submit}
                disabled={busy}
                data-testid="invite-evaluator-modal-submit"
              >
                {busy ? <Loader2 className="size-4 animate-spin" /> : null}
                {t("managerAssessmentSendInvitations")}
              </Button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
