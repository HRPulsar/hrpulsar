"use client";

import { useState } from "react";
import { toast } from "sonner";
import { useTranslations } from "next-intl";
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

/** HRP-476: scope/status codes → keys. Scopes and every status but `error`
 *  already have wording in the shared `common` namespace (the AI-generation
 *  banner uses the same vocabulary); `error` reads "errored" here, so it
 *  keeps its own key in the `competences` namespace. */
const SCOPE_LABEL_KEYS: Record<ActiveSessionRef["scope"], string> = {
  whole_base: "generationScopeWholeBase",
  group: "generationScopeGroup",
  competence_indicators: "generationScopeIndicators",
  specialization_matrix: "generationScopeMatrix",
};

const STATUS_LABEL_KEYS: Record<
  Exclude<ActiveSessionRef["status"], "error">,
  string
> = {
  pending: "generationStatusPending",
  running: "generationStatusRunning",
  ready: "generationStatusReady",
  applied: "generationStatusApplied",
  cancelled: "generationStatusCancelled",
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
  const t = useTranslations("competences");
  const tc = useTranslations("common");
  const [busy, setBusy] = useState(false);
  const open = session !== null;
  const scopeLabel = session
    ? (SCOPE_LABEL_KEYS[session.scope]
        ? tc(SCOPE_LABEL_KEYS[session.scope])
        : session.scope)
    : "";
  const statusLabel = session
    ? session.status === "error"
      ? t("conflictStatusErrored")
      : STATUS_LABEL_KEYS[session.status]
        ? tc(STATUS_LABEL_KEYS[session.status])
        : session.status
    : "";

  async function handleOpen() {
    if (!session) return;
    window.location.href = activeSessionRoute(session);
  }

  async function handleCancelAndRetry() {
    if (!session || busy) return;
    setBusy(true);
    try {
      await competenceGenerationApi.cancel(session.id);
      toast.success(t("toastActiveSessionCancelled"));
      onClose();
      onRetry();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("errorCancelActiveSession"),
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
            {t("preflightTitle")}
          </DialogTitle>
          <DialogDescription className="text-sm text-muted-foreground">
            {t("conflictDescription")}
          </DialogDescription>
        </DialogHeader>
        {session && (
          <div
            data-testid="compgen-conflict-dialog-details"
            className="space-y-1 rounded-md border bg-muted/30 p-3 text-sm"
          >
            <p>
              <span className="font-medium">{t("conflictScopeLabel")}</span>{" "}
              {scopeLabel}
            </p>
            <p>
              <span className="font-medium">{t("conflictStatusLabel")}</span>{" "}
              {statusLabel}
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
                {t("genCancelling")}
              </>
            ) : (
              t("conflictCancelActive")
            )}
          </Button>
          <Button
            data-testid="compgen-conflict-dialog-open"
            onClick={handleOpen}
            disabled={busy}
          >
            {t("conflictOpenActive")}
            <ArrowRight className="ml-1 h-4 w-4" />
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
