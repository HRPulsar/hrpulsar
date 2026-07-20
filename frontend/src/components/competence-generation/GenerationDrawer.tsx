"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AlertTriangle, Loader2, Sparkles } from "lucide-react";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import {
  ActiveQuery,
  useGenerationSession,
} from "@/hooks/use-generation-session";
import { useCeleryHealth } from "@/hooks/use-celery-health";
import { useDisableAutoTranslate } from "@/hooks/use-disable-auto-translate";
import { useWebSocketState } from "@/lib/ws";
import type { SessionScope } from "@/lib/api/competence-generation";
import { GeneratedTree } from "./GeneratedTree";
import { IndicatorsList } from "./IndicatorsList";
import { ErrorScreen } from "./ErrorScreen";
import { RefinementPanel } from "./RefinementPanel";
import { ApplyDialog } from "./ApplyDialog";

export interface GenerationDrawerProps {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  query?: ActiveQuery;
  /** Map of target_id -> human title for breadcrumbs (group/competence). */
  targetTitleResolver?: (targetId: string | null) => string | null;
  /** Callback fired after a successful apply, used by callers to refresh
   * the tree. The session metadata is forwarded so the caller can route the
   * user to the newly-populated entity (competence detail / specialization
   * matrix / competences tree) — HRP-93 Part 2. */
  onApplied?: (info: { scope: SessionScope; target_id: string | null }) => void;
  /** HRP-102: optional warning node forwarded to ApplyDialog (e.g. usage
   * banner shown when the target competence is already referenced). */
  applyWarning?: React.ReactNode;
  /** HRP-102: optional pre-apply guard forwarded to ApplyDialog so the
   * caller can show a blocking confirm before AI suggestions land on a
   * competence that's already in active use. Resolving false aborts the
   * apply silently. */
  applyGuard?: (publish: boolean) => Promise<boolean>;
}

export function GenerationDrawer({
  open,
  onOpenChange,
  query = "active",
  targetTitleResolver,
  onApplied,
  applyWarning,
  applyGuard,
}: GenerationDrawerProps) {
  const {
    session,
    loading,
    refresh,
    cancel,
    clear,
    refine,
    regenerate,
    apply,
    updateSelection,
  } = useGenerationSession(query);
  const router = useRouter();
  const wsState = useWebSocketState();
  const isPendingOrRunning =
    session?.status === "pending" || session?.status === "running";
  const celeryHealth = useCeleryHealth(open && Boolean(isPendingOrRunning));
  // HRP-133: scope the auto-translate guard from HRP-46 to the drawer
  // lifetime so the rest of the dashboard stays translatable for users
  // who rely on Google Translate. The SheetContent below also carries a
  // static `translate="no"` for defense in depth — if the host page was
  // already translated before the drawer opened, the drawer subtree
  // still stays unmodified.
  useDisableAutoTranslate(open);
  const [refining, setRefining] = useState(false);
  const [applyOpen, setApplyOpen] = useState(false);
  const [confirmCloseOpen, setConfirmCloseOpen] = useState(false);
  const [confirmCancelOpen, setConfirmCancelOpen] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [cancelling, setCancelling] = useState(false);

  // HRP-97: persisted refinement form snapshot — `refine_session` writes
  // it into `params.refinement_form` so the panel can re-hydrate on
  // drawer reopen / page refresh / Try again instead of forcing the user
  // to retype.
  const refinementForm = (session?.params?.refinement_form ?? null) as
    | {
        general?: string | null;
        add?: string | null;
        change?: string | null;
        exclude?: string | null;
      }
    | null;
  const hasSavedRefinement = Boolean(
    refinementForm &&
      (refinementForm.general ||
        refinementForm.add ||
        refinementForm.change ||
        refinementForm.exclude),
  );

  // Once the session leaves the active state, drop our local "cancelling" flag.
  useEffect(() => {
    if (
      session &&
      session.status !== "pending" &&
      session.status !== "running"
    ) {
      setCancelling(false);
    }
  }, [session]);

  // HRP-97: auto-open the refinement panel when the session already has
  // saved refinement input. Mirrors the spec's "refinement fields
  // expanded" requirement so the user lands on what they last submitted.
  useEffect(() => {
    if (open && session?.status === "ready" && hasSavedRefinement) {
      setRefining(true);
    }
  }, [open, session?.id, session?.status, hasSavedRefinement]);

  // Auto-close drawer once the session has been applied/cancelled.
  useEffect(() => {
    if (!open) return;
    if (session && (session.status === "applied" || session.status === "cancelled")) {
      onOpenChange(false);
    }
  }, [session, open, onOpenChange]);

  // HRP-122 re-spec: when the drawer is opened and we don't yet have a
  // session locally (typical right after Start → setDrawerOpen(true) →
  // commit race), trigger an immediate refresh so the empty "No active
  // AI generation session" copy doesn't flash. `useGenerationSession`
  // also short-poll-retries for ~30 s on its own, which guards the
  // POST-not-yet-committed race; this just keeps the open click prompt.
  useEffect(() => {
    if (!open) return;
    if (loading) return;
    if (session) return;
    void refresh();
  }, [open, loading, session, refresh]);

  function attemptClose(next: boolean) {
    if (!next && session?.status === "ready" && hasSelection(session.selection_state)) {
      setConfirmCloseOpen(true);
      return;
    }
    onOpenChange(next);
  }

  const scope = session?.scope ?? "whole_base";
  const targetId = session?.target_id ?? null;
  const targetTitle = targetId
    ? (targetTitleResolver?.(targetId) ?? null)
    : null;
  const breadcrumbPrefix =
    scope === "whole_base"
      ? "AI generation → competence library"
      : scope === "group"
        ? "AI generation → group"
        : "AI generation → competence";
  const competenceLinkHref =
    scope === "competence_indicators" && targetId
      ? `/competences/${targetId}`
      : null;

  return (
    <>
      <Sheet open={open} onOpenChange={attemptClose}>
        <SheetContent
          data-testid="compgen-drawer"
          className="w-full max-w-2xl"
          translate="no"
        >
          <SheetHeader>
            <SheetTitle className="flex flex-wrap items-center gap-1.5">
              <Sparkles className="h-4 w-4 text-primary" />
              <span>{breadcrumbPrefix}</span>
              {targetTitle ? (
                <>
                  <span>:</span>
                  {competenceLinkHref ? (
                    <Link
                      href={competenceLinkHref}
                      data-testid="compgen-drawer-target-link"
                      className="text-primary underline-offset-2 hover:underline"
                      onClick={() => onOpenChange(false)}
                    >
                      {targetTitle}
                    </Link>
                  ) : (
                    <span data-testid="compgen-drawer-target-name">
                      {targetTitle}
                    </span>
                  )}
                </>
              ) : null}
            </SheetTitle>
            {wsState !== "open" && (
              <p className="text-xs text-muted-foreground">
                Realtime connection:{" "}
                {wsState === "reconnecting"
                  ? "reconnecting…"
                  : wsState === "connecting"
                    ? "connecting…"
                    : "unavailable — status refreshes every 5s"}
              </p>
            )}
            <p
              data-testid="compgen-drawer-breadcrumb"
              className="sr-only"
            >
              {breadcrumbPrefix}
              {targetTitle ? `: ${targetTitle}` : ""}
            </p>
          </SheetHeader>

          {loading && !session && (
            <div
              data-testid="ai-active-session-modal-skeleton"
              className="flex items-center gap-2 py-8 text-sm text-muted-foreground"
              aria-busy="true"
            >
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading session…
            </div>
          )}

          {!loading && !session && (
            // HRP-122 re-spec: keep a tight "still waiting" frame instead of
            // the old "No active AI generation session" copy — the typical
            // path here is a session that was just kicked off but hasn't
            // been committed yet, not a truly empty state. The hook keeps
            // short-polling for 30 s; this surface stays calm meanwhile.
            <div
              data-testid="compgen-drawer-empty"
              className="space-y-2 py-8 text-center text-sm text-muted-foreground"
              aria-busy="true"
            >
              <Loader2 className="mx-auto h-4 w-4 animate-spin" />
              <p>Waiting for the session to start…</p>
              <p className="text-xs">
                If nothing appears within a minute, refresh the page or close
                this panel and try again.
              </p>
            </div>
          )}

          {session && (session.status === "pending" || session.status === "running") && (
            <div data-testid="compgen-drawer-state-running" className="space-y-3">
              <div className="flex items-center gap-2 rounded-md border bg-muted/40 px-3 py-2 text-sm">
                <Loader2 className="h-4 w-4 animate-spin text-primary" />
                <span>
                  {session.status === "pending"
                    ? "Queued — waiting for a worker…"
                    : "Generating — this usually takes 20–60 seconds."}
                </span>
              </div>
              {celeryHealth === "unavailable" && (
                <div
                  data-testid="compgen-drawer-worker-offline"
                  className="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-sm"
                >
                  <AlertTriangle className="mt-0.5 h-4 w-4 text-amber-500" />
                  <div className="space-y-0.5">
                    <p className="font-medium">Background worker offline</p>
                    <p className="text-xs text-muted-foreground">
                      The Celery worker is not reporting heartbeats. The job
                      will resume as soon as a worker comes back online — or
                      cancel and try again later.
                    </p>
                  </div>
                </div>
              )}
              <SkeletonTree testId="compgen-drawer-skeleton" />
            </div>
          )}

          {session && session.status === "error" && (
            <ErrorScreen
              errorCode={session.error_code}
              errorMessage={session.error_message}
              retrying={retrying}
              onRetry={async () => {
                setRetrying(true);
                try {
                  await regenerate();
                } catch (err) {
                  toast.error(
                    err instanceof Error ? err.message : "Failed to restart",
                  );
                } finally {
                  setRetrying(false);
                }
              }}
            />
          )}

          {session && session.status === "ready" && session.payload && (
            // HRP-96: keep the scroll container and the Refine panel as
            // siblings inside a flex column so the panel sits below the list
            // and stays in its own DOM subtree. Previously the panel was
            // nested inside the scroll area where the IndicatorsList's
            // `sticky bottom-0` counter overlaid it, hiding the
            // "Expand to detailed form" button (and triggering reconciler
            // crashes when the expand toggle remounted nodes the sticky
            // overlay had already painted over).
            <div className="flex min-h-0 flex-1 flex-col">
              <div className="min-h-0 flex-1 overflow-y-auto pr-1">
                {scope === "competence_indicators" ? (
                  <IndicatorsList
                    payload={session.payload}
                    selection={session.selection_state}
                    onToggle={async (id, val) => {
                      try {
                        await updateSelection(id, val);
                      } catch (err) {
                        toast.error(
                          err instanceof Error
                            ? err.message
                            : "Failed to update selection",
                        );
                      }
                    }}
                    existingIndicators={session.existing_indicators ?? null}
                  />
                ) : (
                  <GeneratedTree
                    payload={session.payload}
                    selection={session.selection_state}
                    onToggle={async (id, val) => {
                      try {
                        await updateSelection(id, val);
                      } catch (err) {
                        toast.error(
                          err instanceof Error
                            ? err.message
                            : "Failed to update selection",
                        );
                      }
                    }}
                    existingTree={
                      scope === "group" ? session.existing_tree ?? null : null
                    }
                  />
                )}
              </div>

              {refining ? (
                <div
                  className="mt-3 max-h-[60%] overflow-y-auto rounded-md border bg-background p-3"
                  data-testid="compgen-refine-panel"
                >
                  <RefinementPanel
                    initialValues={refinementForm}
                    onCancel={() => setRefining(false)}
                    onSubmit={async (input) => {
                      try {
                        await refine(input);
                        setRefining(false);
                      } catch (err) {
                        toast.error(
                          err instanceof Error
                            ? err.message
                            : "Failed to refine request",
                        );
                      }
                    }}
                  />
                </div>
              ) : null}
            </div>
          )}

          {session && session.status === "ready" && (
            <div className="-mx-5 -mb-5 mt-auto flex flex-wrap gap-2 border-t bg-muted/50 p-4">
              <Button
                data-testid="compgen-footer-btn-regenerate"
                variant="outline"
                onClick={async () => {
                  try {
                    await regenerate();
                  } catch (err) {
                    toast.error(
                      err instanceof Error ? err.message : "Failed",
                    );
                  }
                }}
              >
                Try again
              </Button>
              <Button
                data-testid="compgen-footer-btn-clear"
                variant="outline"
                onClick={async () => {
                  try {
                    await clear();
                  } catch (err) {
                    toast.error(
                      err instanceof Error ? err.message : "Failed",
                    );
                  }
                }}
              >
                Clear data
              </Button>
              <Button
                data-testid="compgen-footer-btn-refine"
                variant="outline"
                onClick={() => setRefining((v) => !v)}
              >
                {refining ? "Hide" : "Refine request"}
              </Button>
              <Button
                data-testid="compgen-footer-btn-apply"
                onClick={() => setApplyOpen(true)}
                disabled={!hasSelection(session.selection_state)}
                className="ml-auto"
              >
                Add to library
              </Button>
            </div>
          )}

          {session &&
            (session.status === "pending" ||
              session.status === "running" ||
              session.status === "ready") && (
              <div className="-mx-5 -mb-5 mt-auto flex justify-end gap-2 border-t bg-muted/50 p-4">
                <Button
                  data-testid="compgen-btn-cancel-generation"
                  variant="outline"
                  disabled={cancelling}
                  onClick={() => setConfirmCancelOpen(true)}
                >
                  {cancelling
                    ? "Cancelling…"
                    : session.status === "ready"
                      ? "Cancel session"
                      : "Cancel generation"}
                </Button>
              </div>
            )}
        </SheetContent>
      </Sheet>

      {session?.payload && (
        <ApplyDialog
          open={applyOpen}
          onOpenChange={setApplyOpen}
          scope={session.scope}
          payload={session.payload}
          selection={session.selection_state}
          warning={applyWarning}
          applyGuard={applyGuard}
          onApply={async (body) => {
            try {
              await apply(body);
              toast.success("Items added to the library");
              onApplied?.({
                scope: session.scope,
                target_id: session.target_id,
              });
              onOpenChange(false);
              // HRP-93 Part 2 / HRP-94: send the user back to the entity that
              // owns the just-applied output so they can see it in context.
              if (
                session.scope === "competence_indicators" &&
                session.target_id
              ) {
                router.push(`/competences/${session.target_id}`);
              } else if (
                session.scope === "specialization_matrix" &&
                session.target_id
              ) {
                router.push(`/company/specializations/${session.target_id}`);
              } else if (session.scope === "group" || session.scope === "whole_base") {
                router.push("/competences");
              }
            } catch (err) {
              toast.error(
                err instanceof Error ? err.message : "Failed to apply",
              );
            }
          }}
        />
      )}

      <Dialog open={confirmCloseOpen} onOpenChange={setConfirmCloseOpen}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Close without applying?</DialogTitle>
            <DialogDescription>
              You have items selected but haven&apos;t added them to the library.
              The session will be preserved — you can come back to it later.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setConfirmCloseOpen(false)}
            >
              Stay
            </Button>
            <Button
              onClick={() => {
                setConfirmCloseOpen(false);
                onOpenChange(false);
              }}
            >
              Close
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={confirmCancelOpen} onOpenChange={setConfirmCancelOpen}>
        <DialogContent
          data-testid="compgen-cancel-confirm"
          className="sm:max-w-sm"
        >
          <DialogHeader>
            <DialogTitle>Cancel this AI generation session?</DialogTitle>
            <DialogDescription>
              The generated suggestions will be discarded and you&apos;ll be
              able to start a new AI generation right away.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              data-testid="compgen-cancel-confirm-keep"
              onClick={() => setConfirmCancelOpen(false)}
              disabled={cancelling}
            >
              Keep session
            </Button>
            <Button
              variant="destructive"
              data-testid="compgen-cancel-confirm-discard"
              disabled={cancelling}
              onClick={async () => {
                setCancelling(true);
                try {
                  await cancel();
                  await refresh();
                  setConfirmCancelOpen(false);
                } catch (err) {
                  setCancelling(false);
                  toast.error(
                    err instanceof Error ? err.message : "Cancel failed",
                  );
                }
              }}
            >
              {cancelling ? "Cancelling…" : "Discard and cancel"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function SkeletonTree({ testId }: { testId: string }) {
  return (
    <div data-testid={testId} className="space-y-2 py-4">
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="flex items-center gap-3 rounded-md border bg-muted/30 p-3"
        >
          <div className="h-4 w-4 animate-pulse rounded-sm bg-muted" />
          <div className="h-3 flex-1 animate-pulse rounded bg-muted" />
        </div>
      ))}
      <p className="pt-2 text-center text-xs text-muted-foreground">
        AI is generating the competence tree. This may take up to a minute.
      </p>
    </div>
  );
}

function hasSelection(state: Record<string, boolean>): boolean {
  for (const k in state) if (state[k]) return true;
  return false;
}
