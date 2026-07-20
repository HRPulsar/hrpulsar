"use client";

import { useState } from "react";
import { toast } from "sonner";
import { ArrowRight, Loader2, Sparkles } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { competenceGenerationApi } from "@/lib/api/competence-generation";
import {
  activeSessionRoute,
  type ActiveSessionRef,
} from "@/lib/active-ai-session-route";

const SCOPE_LABEL: Record<ActiveSessionRef["scope"], string> = {
  whole_base: "competence library",
  group: "competence group",
  competence_indicators: "competence indicators",
  specialization_matrix: "specialization matrix",
};

const STATUS_LABEL: Record<ActiveSessionRef["status"], string> = {
  pending: "queued",
  running: "in progress",
  ready: "ready for review",
  applied: "applied",
  cancelled: "cancelled",
  error: "errored",
};

export interface ActiveSessionConflictDialogProps {
  /** Conflict session returned by the backend on 409, or null to close. */
  session: ActiveSessionRef | null;
  /** Called when the dialog closes for any reason (esc, backdrop, action). */
  onClose: () => void;
  /** Called after the active session is cancelled successfully; the caller
   * should retry the original "Start generation" action. */
  onRetry: () => void;
}

/**
 * HRP-168: surface a visible decision when the create-session API returns
 * 409 active_session_exists. Replaces the previous silent
 * `window.location.href` redirect, which made it look like the page just
 * refreshed and "Start generation" did nothing.
 *
 * Two explicit choices:
 * - Open active session → navigate the user to wherever the existing
 *   session lives (mirrors `activeSessionRoute`).
 * - Cancel and try again → DELETE the existing session and replay the
 *   original Start action via the `onRetry` callback.
 */
export function ActiveSessionConflictDialog({
  session,
  onClose,
  onRetry,
}: ActiveSessionConflictDialogProps) {
  const [busy, setBusy] = useState(false);
  const open = session !== null;

  async function handleOpen() {
    if (!session) return;
    window.location.href = activeSessionRoute(session);
  }

  async function handleCancelAndRetry() {
    if (!session || busy) return;
    setBusy(true);
    try {
      await competenceGenerationApi.cancel(session.id);
      toast.success("Active session cancelled. Starting a new one…");
      onClose();
      onRetry();
    } catch (err) {
      toast.error(
        err instanceof Error
          ? err.message
          : "Failed to cancel active session",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next && !busy) onClose();
      }}
    >
      <DialogContent
        data-testid="compgen-conflict-dialog"
        className="sm:max-w-md"
      >
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-primary" />
            AI generation already in progress
          </DialogTitle>
          <DialogDescription className="text-sm text-muted-foreground">
            You already have an in-flight AI generation session. Only one
            session at a time per user — open it to continue, or cancel it to
            start fresh.
          </DialogDescription>
        </DialogHeader>
        {session && (
          <div
            data-testid="compgen-conflict-dialog-details"
            className="space-y-1 rounded-md border bg-muted/30 p-3 text-sm"
          >
            <p>
              <span className="font-medium">Scope:</span>{" "}
              {SCOPE_LABEL[session.scope] ?? session.scope}
            </p>
            <p>
              <span className="font-medium">Status:</span>{" "}
              {STATUS_LABEL[session.status] ?? session.status}
            </p>
          </div>
        )}
        <DialogFooter className="flex flex-col gap-2 sm:flex-row sm:justify-end">
          <Button
            variant="outline"
            data-testid="compgen-conflict-dialog-cancel-active"
            onClick={handleCancelAndRetry}
            disabled={busy}
          >
            {busy ? (
              <>
                <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                Cancelling…
              </>
            ) : (
              "Cancel active and try again"
            )}
          </Button>
          <Button
            data-testid="compgen-conflict-dialog-open"
            onClick={handleOpen}
            disabled={busy}
          >
            Open active session
            <ArrowRight className="ml-1 h-4 w-4" />
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
