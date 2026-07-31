"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { Loader2, AlertCircle, Sparkles, X } from "lucide-react";
import { toast } from "sonner";
import type {
  CompetenceItem,
  Vacancy,
  VacancyProfile,
} from "@/lib/types";
import {
  CompetenceTreeView,
  findUnnamedCompetence,
} from "./competence-tree-view";
import {
  sessionHasPendingResult,
  type ProfileSessionPayload,
} from "./profile-generation-status";

// HRP-134 / HRP-235 REDO: matrix-style generation dialog.
//
// Three stages:
//   confirm    — vacancy context + clarification textarea + Start
//   processing — banner with ETA + steps + Cancel; the dialog stays
//                open but the user can close it; the in-page banner
//                keeps polling the active session row.
//   review     — after the session lands "ready", the generated payload
//                (parked on the session row server-side — QA case 4: it
//                is NOT saved to the profile yet) is rendered with
//                checkbox selection + inline edit/delete.
//                Previously-saved competences are locked (only on the
//                regenerate path; the bare Edit entry point unlocks
//                everything). Apply persists the kept + edited
//                selection plus any locked rows that the LLM dropped;
//                Discard drops the generated payload — the saved
//                profile is never touched either way until Apply.
//
// The dialog can also resume a session started earlier: the parent
// passes the banner-polled session and the open-transition effect jumps
// straight to processing (running) or review (ready) — that is what the
// banner's "Review for save" button rides on.

interface ProfileGenerationDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  vacancy: Vacancy;
  initialProfile: VacancyProfile | null;
  // Session already polled by the in-page banner, used to resume into
  // the processing/review stage instead of starting from scratch.
  activeSession?: ProfileSessionPayload | null;
  // Fired after Apply or Discard so the parent can re-fetch.
  onProfileChange?: () => void | Promise<void>;
}

type Stage = "confirm" | "processing" | "review";

const ESTIMATE_SECONDS = 75;
const POLL_INTERVAL_MS = 3000;
// After this many consecutive null responses from /sessions/active we
// assume another tab (or an admin) cancelled the run — the endpoint
// filters cancelled rows out, so a sustained null is indistinguishable
// from a dismissed session. Stops the spinner from spinning forever.
const NULL_POLL_TOLERATED = 3;
// i18n keys in the `recruitment` namespace — the module constant cannot
// call `useTranslations`, so the step list stores keys and the component
// resolves them with its own `t`.
const GENERATION_STEP_KEYS = [
  "profileGenStepGroups",
  "profileGenStepCompetences",
  "profileGenStepIndicators",
  "profileGenStepQuestions",
];

function nonEmpty(value: string | null | undefined): string | null {
  const trimmed = (value || "").trim();
  return trimmed.length > 0 ? trimmed : null;
}

function profileCompetences(
  profile: VacancyProfile | null,
): CompetenceItem[] {
  if (!profile?.profile_data) return [];
  const list = (profile.profile_data as { competences?: unknown }).competences;
  if (!Array.isArray(list)) return [];
  return list as CompetenceItem[];
}

function competenceKey(comp: CompetenceItem): string {
  return comp.id || comp.name;
}

function sessionProfileData(
  session: ProfileSessionPayload | null | undefined,
): Record<string, unknown> | null {
  const data = session?.result_payload?.profile_data;
  return data && typeof data === "object" ? data : null;
}

export function ProfileGenerationDialog({
  open,
  onOpenChange,
  vacancy,
  initialProfile,
  activeSession = null,
  onProfileChange,
}: ProfileGenerationDialogProps) {
  const [stage, setStage] = useState<Stage>("confirm");
  const [clarification, setClarification] = useState("");
  const [session, setSession] = useState<ProfileSessionPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Starts as the generated (unsaved) payload from the ready session and
  // accumulates the recruiter's inline edits — the review base and the
  // apply base are the same object on purpose.
  const [editedData, setEditedData] = useState<Record<string, unknown> | null>(
    null,
  );
  const [selectedIds, setSelectedIds] = useState<string[] | null>(null);
  const [busy, setBusy] = useState(false);
  // Snapshot of the profile BEFORE this generation run — captured once
  // on open transition (not on every re-render) so a parent that hands
  // us a new initialProfile reference cannot move the goalposts mid
  // session. Drives the locked-list on the regenerate path and the
  // merge-back of locked rows the LLM dropped. With the deferred-save
  // flow (QA case 4) the saved profile is untouched during generation,
  // so this snapshot always equals the persisted truth.
  const [preSnapshot, setPreSnapshot] = useState<VacancyProfile | null>(
    initialProfile,
  );
  const prevOpenRef = useRef(false);
  const nullCountRef = useRef(0);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const t = useTranslations("recruitment");

  const lockedIds = useMemo(() => {
    return profileCompetences(preSnapshot).map(competenceKey).filter(Boolean);
  }, [preSnapshot]);

  // Reset only on the false → true transition: a sibling re-render
  // that flips the initialProfile reference must not clobber the
  // user's in-flight edits. Resumes into processing/review when the
  // parent hands us a session the banner already knows about.
  useEffect(() => {
    if (open && !prevOpenRef.current) {
      setPreSnapshot(initialProfile);
      setError(null);
      setClarification("");
      nullCountRef.current = 0;
      const resumeData = sessionProfileData(activeSession);
      if (activeSession?.status === "running") {
        setSession(activeSession);
        setEditedData(null);
        setSelectedIds(null);
        setStage("processing");
      } else if (
        activeSession &&
        sessionHasPendingResult(activeSession) &&
        resumeData
      ) {
        setSession(activeSession);
        setEditedData(resumeData);
        setSelectedIds(null);
        setStage("review");
      } else {
        setSession(null);
        setEditedData(null);
        setSelectedIds(null);
        setStage("confirm");
      }
    }
    prevOpenRef.current = open;
    if (!open) {
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = null;
      const t = setTimeout(() => {
        setSession(null);
      }, 200);
      return () => clearTimeout(t);
    }
  }, [open, initialProfile, activeSession]);

  // Polling during processing.
  useEffect(() => {
    if (stage !== "processing") return;
    const tick = async () => {
      try {
        const data = await api.get<ProfileSessionPayload | null>(
          `/recruitment/vacancies/${vacancy.id}/profile/sessions/active`,
        );
        if (!data) {
          nullCountRef.current += 1;
          if (nullCountRef.current >= NULL_POLL_TOLERATED) {
            if (pollRef.current) clearInterval(pollRef.current);
            pollRef.current = null;
            toast.info(t("profileGenDismissed"));
            await onProfileChange?.();
            onOpenChange(false);
          }
          return;
        }
        nullCountRef.current = 0;
        setSession(data);
        if (data.status === "ready") {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
          // QA case 4: the generated payload lives on the session row,
          // not in the saved profile — read it from the poll response.
          const generated = sessionProfileData(data);
          if (generated) {
            setEditedData(generated);
          } else {
            setError(t("profileGenNotFound"));
          }
          setStage("review");
        } else if (data.status === "failed") {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
          setError(data.error_message || t("profileGenFailed"));
          setStage("review");
        }
        // "running" — keep polling. (Cancelled rows never come back from
        // /sessions/active; that case surfaces as the null-poll path.)
      } catch {
        // best-effort; network blip doesn't change state
      }
    };
    void tick();
    pollRef.current = setInterval(tick, POLL_INTERVAL_MS);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = null;
    };
  }, [stage, vacancy.id, onOpenChange, onProfileChange, t]);

  const handleStart = useCallback(async () => {
    nullCountRef.current = 0;
    setError(null);
    setStage("processing");
    try {
      const result = await api.post<{
        cancelled?: boolean;
        status?: string;
        session_id?: string;
        profile_data?: Record<string, unknown> | null;
      }>(
        `/recruitment/vacancies/${vacancy.id}/profile/generate`,
        nonEmpty(clarification) ? { clarification: clarification.trim() } : {},
      );
      // Backend may respond with ``{cancelled: true}`` when a parallel
      // cancel beat the save (see service.generate_profile_now). Treat
      // it like a confirmed dismiss — the polling loop will not see a
      // ``ready`` row, so we short-circuit here to close the dialog.
      if (result?.cancelled === true) {
        toast.info(t("profileGenCancelled"));
        await onProfileChange?.();
        onOpenChange(false);
        return;
      }
      // The synchronous endpoint resolves exactly when the LLM finishes
      // and already carries the parked payload — jump straight to review
      // instead of waiting for the next poll to deliver the same data.
      if (result?.status === "ready" && result.session_id && result.profile_data) {
        setSession({
          id: result.session_id,
          status: "ready",
          started_at: new Date().toISOString(),
          completed_at: null,
          error_message: null,
          result_payload: { profile_data: result.profile_data },
          has_pending_result: true,
        });
        setEditedData(result.profile_data);
        setStage("review");
      }
    } catch (err) {
      setError(
        err instanceof Error ? err.message : t("profileGenStartFailed"),
      );
      setStage("review");
    }
  }, [vacancy.id, clarification, onOpenChange, onProfileChange, t]);

  const handleCancel = useCallback(async () => {
    setBusy(true);
    try {
      // Pin the cancel to the polled running session when we know it —
      // a bodyless cancel falls back to latest-match server-side and
      // could hit a session started from another tab (HRP-134 REDO).
      // No profile rollback is needed any more: with deferred save (QA
      // case 4) the generation result never touches the saved profile,
      // so cancelling the session is the whole job.
      await api.post(
        `/recruitment/vacancies/${vacancy.id}/profile/sessions/cancel`,
        session?.id ? { session_id: session.id } : {},
      );
      toast.info(t("profileGenCancelled"));
      await onProfileChange?.();
      onOpenChange(false);
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("profileGenCancelFailed"),
      );
    } finally {
      setBusy(false);
    }
  }, [vacancy.id, session?.id, onOpenChange, onProfileChange, t]);

  const handleApply = useCallback(async () => {
    const baseData = editedData;
    if (!baseData) {
      onOpenChange(false);
      return;
    }
    setBusy(true);
    try {
      const competences = Array.isArray(
        (baseData as { competences?: unknown }).competences,
      )
        ? ((baseData as { competences: CompetenceItem[] }).competences ?? [])
        : [];
      const lockedSet = new Set(lockedIds);
      // Apply selection only when the recruiter actively flipped at
      // least one checkbox; otherwise keep every competence the tree
      // already shows (deletes already removed unwanted rows).
      const kept =
        selectedIds === null
          ? competences
          : competences.filter((c) => {
              const key = competenceKey(c);
              return selectedIds.includes(key) || lockedSet.has(key);
            });
      // Re-attach any locked competences that the regenerated profile
      // dropped — the lock chip promises "stays no matter what", so
      // we must merge them back from the pre-run snapshot if the LLM
      // produced a slug-different replacement.
      const haveKey = new Set(kept.map(competenceKey));
      const merged = [...kept];
      for (const prior of profileCompetences(preSnapshot)) {
        const key = competenceKey(prior);
        if (lockedSet.has(key) && !haveKey.has(key)) {
          merged.push(prior);
          haveKey.add(key);
        }
      }
      const payload = { ...baseData, competences: merged };
      // HRP-318 REDO: names are inline-editable here too — the same
      // nameless-competence guard as the vacancy-page Save, since
      // assessment sheets key their labels off the name.
      if (findUnnamedCompetence(payload)) {
        toast.error(t("vacancyCompetencesUnnamed"));
        return;
      }
      if (session?.id) {
        // Atomic server-side apply: saves the profile (with AI
        // provenance) and retires the ready session in one transaction,
        // so the Review-for-save banner can never outlive the save.
        await api.post(
          `/recruitment/vacancies/${vacancy.id}/profile/sessions/apply`,
          { session_id: session.id, profile_data: payload },
        );
      } else {
        // Defensive fallback — review without a session should not
        // happen, but a plain save is still better than a dead button.
        await api.put(`/recruitment/vacancies/${vacancy.id}/profile`, {
          profile_data: payload,
        });
      }
      toast.success(t("vacancyProfileToastSaved"));
      await onProfileChange?.();
      onOpenChange(false);
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("profileGenSaveFailed"),
      );
    } finally {
      setBusy(false);
    }
  }, [
    editedData,
    selectedIds,
    lockedIds,
    preSnapshot,
    session?.id,
    vacancy.id,
    onOpenChange,
    onProfileChange,
    t,
  ]);

  const handleDiscard = useCallback(async () => {
    setBusy(true);
    try {
      // Drop the pending result by retiring its session — the saved
      // profile was never touched (QA case 4), so there is nothing to
      // roll back. Only terminal sessions are cancelled here: a running
      // session belongs to the explicit Cancel-generation button, and a
      // bodyless cancel could kill a run started from another tab.
      if (
        session?.id &&
        (session.status === "ready" || session.status === "failed")
      ) {
        await api.post(
          `/recruitment/vacancies/${vacancy.id}/profile/sessions/cancel`,
          { session_id: session.id },
        );
      }
      toast.info(t("profileGenDiscarded"));
      await onProfileChange?.();
      onOpenChange(false);
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("profileGenDiscardFailed"),
      );
    } finally {
      setBusy(false);
    }
  }, [
    vacancy.id,
    session?.id,
    session?.status,
    onOpenChange,
    onProfileChange,
    t,
  ]);

  const startedAt = session ? new Date(session.started_at).getTime() : null;
  const elapsed =
    startedAt !== null ? Math.max(0, Math.floor((Date.now() - startedAt) / 1000)) : 0;
  const remaining = Math.max(0, ESTIMATE_SECONDS - elapsed);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-h-[90vh] overflow-hidden sm:max-w-3xl"
        data-testid="recruitment-profile-dialog"
      >
        {stage === "confirm" && (
          <ConfirmStage
            vacancy={vacancy}
            initialProfile={initialProfile}
            clarification={clarification}
            onClarificationChange={setClarification}
            onCancel={() => onOpenChange(false)}
            onStart={handleStart}
          />
        )}

        {stage === "processing" && (
          <>
            <DialogHeader>
              <DialogTitle>{t("profileGenProcessingTitle")}</DialogTitle>
              <DialogDescription>
                {t("profileGenProcessingDescription")}
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-3 py-4">
              <div className="flex items-center gap-3 rounded-md border border-accent/30 bg-accent/5 p-3">
                <Loader2 className="size-5 animate-spin text-accent" />
                <div className="space-y-1">
                  <p className="flex items-center gap-2 text-sm font-medium">
                    <Sparkles className="size-4 text-accent" />
                    {t("profileGenWorking")}
                    <span className="text-xs font-normal text-muted-foreground">
                      (~
                      {remaining > 0
                        ? t("profileGenRemaining", { seconds: remaining })
                        : t("profileGenWrappingUp")}
                      )
                    </span>
                  </p>
                  <ul className="space-y-0.5 text-xs text-muted-foreground">
                    {GENERATION_STEP_KEYS.map((stepKey) => (
                      <li key={stepKey} className="flex items-center gap-1.5">
                        <span className="size-1.5 rounded-full bg-accent/70" />
                        {t(stepKey)}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>
            <DialogFooter className="gap-2">
              <Button
                variant="outline"
                onClick={() => onOpenChange(false)}
                disabled={busy}
                data-testid="recruitment-profile-dialog-close-btn"
              >
                {t("profileGenCloseWindow")}
              </Button>
              <Button
                variant="destructive"
                onClick={handleCancel}
                disabled={busy}
                data-testid="recruitment-profile-dialog-cancel-btn"
              >
                <X className="mr-1 size-4" />
                {t("profileGenCancelGeneration")}
              </Button>
            </DialogFooter>
          </>
        )}

        {stage === "review" && (
          <ReviewStage
            error={error}
            data={editedData}
            lockedIds={lockedIds}
            selectedIds={selectedIds}
            onEditedChange={setEditedData}
            onSelectionChange={setSelectedIds}
            onDiscard={handleDiscard}
            onApply={handleApply}
            busy={busy}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

function ConfirmStage({
  vacancy,
  initialProfile,
  clarification,
  onClarificationChange,
  onCancel,
  onStart,
}: {
  vacancy: Vacancy;
  initialProfile: VacancyProfile | null;
  clarification: string;
  onClarificationChange: (next: string) => void;
  onCancel: () => void;
  onStart: () => void;
}) {
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const hasProfile = Boolean(
    initialProfile?.profile_data &&
      Array.isArray(
        (initialProfile.profile_data as { competences?: unknown }).competences,
      ) &&
      ((initialProfile.profile_data as { competences: unknown[] }).competences
        ?.length ?? 0) > 0,
  );

  return (
    <>
      <DialogHeader>
        <DialogTitle>{t("profileGenConfirmTitle")}</DialogTitle>
        <DialogDescription>
          {hasProfile
            ? t("profileGenConfirmDescriptionLocked")
            : t("profileGenConfirmDescription")}
        </DialogDescription>
      </DialogHeader>
      <div
        className="max-h-[55vh] space-y-3 overflow-y-auto pr-1"
        data-testid="recruitment-profile-dialog-context"
      >
        <ContextRow label={tc("vacancy")} value={vacancy.title} />
        {nonEmpty(vacancy.description) && (
          <ContextRow
            label={t("vacancyFieldDescription")}
            value={vacancy.description!}
            multiline
          />
        )}
        {nonEmpty(vacancy.employment_type) && (
          <ContextRow
            label={t("vacancyFieldEmploymentType")}
            value={vacancy.employment_type!}
          />
        )}
        {nonEmpty(vacancy.location) && (
          <ContextRow
            label={t("candidateFieldLocation")}
            value={vacancy.location!}
          />
        )}
        {nonEmpty(vacancy.requirements) && (
          <ContextRow
            label={t("vacancyFieldRequirements")}
            value={vacancy.requirements!}
            multiline
          />
        )}
        {nonEmpty(vacancy.responsibilities) && (
          <ContextRow
            label={t("vacancyFieldResponsibilities")}
            value={vacancy.responsibilities!}
            multiline
          />
        )}
        {nonEmpty(vacancy.conditions) && (
          <ContextRow
            label={t("vacancyFieldConditions")}
            value={vacancy.conditions!}
            multiline
          />
        )}
        <div className="space-y-1">
          <label
            htmlFor="profile-clarification"
            className="text-xs font-medium text-muted-foreground"
          >
            {t("profileGenClarificationLabel")}
          </label>
          <Textarea
            id="profile-clarification"
            value={clarification}
            onChange={(e) => onClarificationChange(e.target.value)}
            placeholder={t("profileGenClarificationPlaceholder")}
            className="min-h-20 text-sm"
            data-testid="recruitment-profile-dialog-clarification"
          />
        </div>
      </div>
      <DialogFooter>
        <Button variant="outline" onClick={onCancel}>
          {tc("cancel")}
        </Button>
        <Button onClick={onStart} data-testid="recruitment-profile-dialog-start-btn">
          <Sparkles className="mr-1 size-4" />
          {t("profileGenStartButton")}
        </Button>
      </DialogFooter>
    </>
  );
}

function ContextRow({
  label,
  value,
  multiline = false,
}: {
  label: string;
  value: string;
  multiline?: boolean;
}) {
  return (
    <div className="space-y-0.5 rounded-md border p-2">
      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <p
        className={multiline ? "whitespace-pre-line text-sm" : "text-sm"}
      >
        {value}
      </p>
    </div>
  );
}

function ReviewStage({
  error,
  data,
  lockedIds,
  selectedIds,
  onEditedChange,
  onSelectionChange,
  onDiscard,
  onApply,
  busy,
}: {
  error: string | null;
  data: Record<string, unknown> | null;
  lockedIds: string[];
  selectedIds: string[] | null;
  onEditedChange: (next: Record<string, unknown>) => void;
  onSelectionChange: (next: string[]) => void;
  onDiscard: () => void;
  onApply: () => void;
  busy: boolean;
}) {
  const t = useTranslations("recruitment");
  if (error) {
    return (
      <>
        <DialogHeader>
          <DialogTitle>{t("profileGenFailed")}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col items-center gap-3 py-6">
          <AlertCircle className="size-8 text-destructive" />
          <p className="text-center text-sm text-destructive">{error}</p>
        </div>
        <DialogFooter>
          <Button onClick={onDiscard} disabled={busy}>
            {t("profileGenClose")}
          </Button>
        </DialogFooter>
      </>
    );
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>{t("profileGenReviewTitle")}</DialogTitle>
        <DialogDescription>
          {lockedIds.length > 0
            ? t("profileGenReviewDescriptionLocked")
            : t("profileGenReviewDescription")}
        </DialogDescription>
      </DialogHeader>
      <div
        className="max-h-[60vh] overflow-y-auto pr-1"
        data-testid="recruitment-profile-dialog-review"
      >
        <CompetenceTreeView
          profileData={data}
          readOnly={false}
          editable
          selectable
          lockedCompetenceIds={lockedIds}
          selectedCompetenceIds={selectedIds ?? undefined}
          onSelectionChange={onSelectionChange}
          onChange={onEditedChange}
        />
      </div>
      <DialogFooter className="gap-2">
        <Button
          variant="outline"
          onClick={onDiscard}
          disabled={busy}
          data-testid="recruitment-profile-dialog-discard-btn"
        >
          {t("profileGenDiscardButton")}
        </Button>
        <Button
          onClick={onApply}
          disabled={busy}
          data-testid="recruitment-profile-dialog-apply-btn"
        >
          {t("profileGenApplyButton")}
        </Button>
      </DialogFooter>
    </>
  );
}
