"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, CheckCircle2, Loader2, Sparkles, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { toast } from "sonner";

// HRP-134 / HRP-235:
//
// Shows an active profile-generation session for a vacancy. Polls
// ``/profile/sessions/active`` every few seconds so a returning user
// sees "Generating…" with an ETA and the list of items being produced,
// can dismiss the banner with Cancel, and — once the server-side LLM
// call completes — gets a "Review for save" banner instead of a silent
// auto-save (HRP-235 REDO, QA case 4). The generated payload stays on
// the session row until the recruiter applies it from the review
// dialog.
//
// The polling cadence is intentionally generous (4s) — the LLM call
// usually takes 30-90s and the in-flight row is committed before the
// call starts, so we don't need sub-second granularity to render it.

export interface ProfileSessionPayload {
  id: string;
  status: "running" | "ready" | "failed" | "cancelled" | "applied" | null;
  started_at: string;
  completed_at: string | null;
  error_message: string | null;
  result_payload?: {
    profile_data?: Record<string, unknown> | null;
  } | null;
  // Server-derived: status === "ready" with an unreviewed payload parked
  // on the session. Present for every role — the payload itself is only
  // returned to admin/recruiter callers.
  has_pending_result?: boolean;
}

// Single source of truth for "this session still holds an unreviewed
// result" — the banner, the action-button lock in the parent section and
// the dialog resume path must agree on it.
export function sessionHasPendingResult(
  session: ProfileSessionPayload | null | undefined,
): boolean {
  if (!session || session.status !== "ready") return false;
  return session.has_pending_result ?? Boolean(session.result_payload?.profile_data);
}

interface ProfileGenerationStatusProps {
  vacancyId: string;
  // Mirrors every polled session state up to the parent so it can lock
  // the Generate / Regenerate / Edit / Add-from-dictionary buttons while
  // a session is running or a result is pending review (QA cases 2-3).
  onSessionChange?: (session: ProfileSessionPayload | null) => void;
  // Opens the review dialog for a ready session (QA case 4).
  onReview?: () => void;
  // Bump to force an immediate re-poll — the parent increments it after
  // the review dialog closes so the banner reflects apply/discard/cancel
  // without waiting out the polling interval.
  refreshKey?: number;
}

// Rough generation budget (s). The recruiter sees this as a soft ETA
// next to the spinner so the wait feels predictable rather than open
// ended. Matches the typical wall-clock for the GENERATE_PROFILE prompt
// on Claude Sonnet + a 12-competence target.
const ESTIMATE_SECONDS = 75;
const POLL_INTERVAL_MS = 4000;
// A ready (pending-review) session re-polls too, just slower: another
// tab may apply or discard the result, and this tab must drop the
// banner and unlock the action buttons without a manual reload.
const READY_POLL_INTERVAL_MS = 15000;

// Steps the prompt actually drives (see GENERATE_PROFILE template) —
// surfacing them in the banner answers the user's "what is it doing right
// now?" question without needing real server-side progress signals.
const GENERATION_STEPS = [
  "Competence groups",
  "Competences in each group",
  "Indicators per competence (≥ 3 per level)",
  "Interview questions (≥ 3 per competence)",
];

export function ProfileGenerationStatus({
  vacancyId,
  onSessionChange,
  onReview,
  refreshKey = 0,
}: ProfileGenerationStatusProps) {
  const [session, setSession] = useState<ProfileSessionPayload | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [tick, setTick] = useState(0);
  const lastKeyRef = useRef<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await api.get<ProfileSessionPayload | null>(
        `/recruitment/vacancies/${vacancyId}/profile/sessions/active`,
      );
      const next = data ?? null;
      // Only propagate when something observable changed — a fresh
      // object identity on every 4s poll would re-render the whole
      // parent section (and re-run effects keyed on the session) for
      // no visible difference.
      const key = next
        ? `${next.id}:${next.status}:${sessionHasPendingResult(next)}`
        : "none";
      if (key === lastKeyRef.current) return;
      lastKeyRef.current = key;
      setSession(next);
      onSessionChange?.(next);
    } catch {
      // Best-effort polling — a network blip should not blow up the UI.
    }
  }, [vacancyId, onSessionChange]);

  // HRP-134 REDO (Viktoriya 2026-06-26): the banner used to disappear
  // silently on ``failed``, so a recruiter who triggered Save & Generate
  // Profile saw an empty Competences & indicators block and a second
  // Generate-with-AI click that surfaced an error toast — but never
  // understood the run had already crashed. Surfacing the failed run +
  // the LLM error message inline lets them retry or fix the prompt.
  // Pin cancel/dismiss requests to the session the banner is actually
  // showing. A bodyless cancel falls back to latest-match server-side
  // and can kill a newer running session started from another tab or by
  // another recruiter, while the failed row survives and resurrects the
  // banner on the next poll.
  const sessionId = session?.id ?? null;

  const dismissFailure = useCallback(async () => {
    lastKeyRef.current = "none";
    setSession(null);
    onSessionChange?.(null);
    try {
      // Reuse the cancel endpoint to flip the failed session to
      // ``cancelled`` server-side. Without this the next poll re-surfaces
      // the banner because the row stays in the active-session query.
      await api.post(
        `/recruitment/vacancies/${vacancyId}/profile/sessions/cancel`,
        sessionId ? { session_id: sessionId } : {},
      );
    } catch {
      // Best-effort — the local state already hid the banner.
    }
  }, [vacancyId, sessionId, onSessionChange]);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  const pendingReview = sessionHasPendingResult(session);

  useEffect(() => {
    if (!session) return;
    const running = session.status === "running";
    if (!running && !pendingReview) return;
    const intervalId = window.setInterval(
      () => {
        setTick((n) => n + 1);
        void load();
      },
      running ? POLL_INTERVAL_MS : READY_POLL_INTERVAL_MS,
    );
    return () => window.clearInterval(intervalId);
    // ``tick`` only triggers re-renders for the ETA countdown — it is
    // not a dependency for the effect itself.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session?.status, pendingReview, load]);

  const handleCancel = useCallback(async () => {
    setCancelling(true);
    try {
      await api.post(
        `/recruitment/vacancies/${vacancyId}/profile/sessions/cancel`,
        sessionId ? { session_id: sessionId } : {},
      );
      toast.info("Profile generation dismissed");
      lastKeyRef.current = "none";
      setSession(null);
      onSessionChange?.(null);
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to cancel generation",
      );
    } finally {
      setCancelling(false);
    }
  }, [vacancyId, sessionId, onSessionChange]);

  if (!session) return null;

  if (session.status === "failed") {
    return (
      <div
        className="rounded-md border border-destructive/30 bg-destructive/5 p-4"
        data-testid="vacancy-profile-generation-failed"
        role="alert"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <AlertCircle className="mt-0.5 size-5 text-destructive" />
            <div className="space-y-1">
              <p className="text-sm font-medium text-destructive">
                Profile generation failed
              </p>
              <p className="text-xs text-muted-foreground">
                {session.error_message ||
                  "The AI did not return a valid profile. Try again or open the matrix dialog to provide a clarification."}
              </p>
            </div>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={dismissFailure}
            data-testid="vacancy-profile-generation-failed-dismiss-btn"
          >
            Dismiss
          </Button>
        </div>
      </div>
    );
  }

  // HRP-235 REDO (QA case 4): a finished session keeps the banner alive
  // — with a Review for save button instead of Cancel — until the
  // recruiter walks through the review dialog. Sessions from before the
  // deferred-save change have no ``profile_data`` in the payload and are
  // skipped: their result already landed in the profile back then.
  if (session.status === "ready") {
    if (!pendingReview) return null;
    return (
      <div
        className="rounded-md border border-accent/30 bg-accent/5 p-4"
        data-testid="vacancy-profile-generation-ready"
        aria-live="polite"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <CheckCircle2 className="mt-0.5 size-5 text-accent" />
            <div className="space-y-1">
              <p className="flex items-center gap-2 text-sm font-medium">
                <Sparkles className="size-4 text-accent" />
                Competence profile generated
              </p>
              <p className="text-xs text-muted-foreground">
                Nothing is saved yet — review the results to keep, edit or
                discard them.
              </p>
            </div>
          </div>
          <Button
            size="sm"
            onClick={onReview}
            data-testid="vacancy-profile-generation-review-btn"
          >
            Review for save
          </Button>
        </div>
      </div>
    );
  }

  if (session.status !== "running") return null;

  const startedAt = new Date(session.started_at).getTime();
  const elapsed = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
  const remaining = Math.max(0, ESTIMATE_SECONDS - elapsed);

  return (
    <div
      className="rounded-md border border-accent/30 bg-accent/5 p-4"
      data-testid="vacancy-profile-generation-status"
      aria-live="polite"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <Loader2 className="mt-0.5 size-5 animate-spin text-accent" />
          <div className="space-y-1">
            <p className="flex items-center gap-2 text-sm font-medium">
              <Sparkles className="size-4 text-accent" />
              Generating competence profile
              <span className="text-xs font-normal text-muted-foreground">
                (~{remaining > 0 ? `${remaining}s remaining` : "wrapping up"})
              </span>
            </p>
            <p className="text-xs text-muted-foreground">
              You can leave this page — the session keeps running and the
              banner reappears when you return.
            </p>
            <ul className="mt-1 space-y-0.5 text-xs text-muted-foreground">
              {GENERATION_STEPS.map((step) => (
                <li key={step} className="flex items-center gap-1.5">
                  <span className="size-1.5 rounded-full bg-accent/70" />
                  {step}
                </li>
              ))}
            </ul>
          </div>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={handleCancel}
          disabled={cancelling}
          data-testid="vacancy-profile-generation-cancel-btn"
        >
          <X className="mr-1 size-4" />
          Cancel
        </Button>
      </div>
      {/* tick keeps the countdown live without needing a separate timer */}
      <span className="sr-only" aria-hidden>
        tick {tick}
      </span>
    </div>
  );
}
