"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Sparkles, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  competenceGenerationApi,
  type CompetenceGenerationSession,
  type SessionScope,
  type SessionStatus,
} from "@/lib/api/competence-generation";
import { activeSessionRoute } from "@/lib/active-ai-session-route";
import { useWebSocketEvent } from "@/lib/ws";

const POLL_INTERVAL_MS = 15_000;
const VISIBLE_STATUSES: SessionStatus[] = ["pending", "running", "ready"];

/**
 * HRP-232: pure predicate — should the banner keep polling? Polling runs
 * whenever there is an active session to track, regardless of WS state.
 * WS pushes are a fast-path but cannot be relied on for delivery (HRP-122
 * REDO #3), so a "WS is open" check used to leave the banner stuck on
 * "generation in progress" until the user hit F5.
 */
export function shouldPollGenerationBanner(
  status: SessionStatus | null,
): boolean {
  if (!status) return false;
  return VISIBLE_STATUSES.includes(status);
}

function dismissKey(sessionId: string): string {
  return `hrpulsar:compgen-banner-dismissed:${sessionId}`;
}

function isDismissed(sessionId: string): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.sessionStorage.getItem(dismissKey(sessionId)) === "1";
  } catch {
    return false;
  }
}

function rememberDismissal(sessionId: string): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(dismissKey(sessionId), "1");
  } catch {
    // sessionStorage disabled — banner just won't persist its dismissal
    // across re-renders this tab; reload will still hide it once.
  }
}

/** Scope / status → key in the `common` message namespace. */
const SCOPE_LABEL_KEY: Record<SessionScope, string> = {
  whole_base: "generationScopeWholeBase",
  group: "generationScopeGroup",
  competence_indicators: "generationScopeIndicators",
  specialization_matrix: "generationScopeMatrix",
};

const STATUS_LABEL_KEY: Record<SessionStatus, string> = {
  pending: "generationStatusPending",
  running: "generationStatusRunning",
  ready: "generationStatusReady",
  error: "generationStatusError",
  applied: "generationStatusApplied",
  cancelled: "generationStatusCancelled",
};

/**
 * HRP-33: persistent top-of-page banner that surfaces the user's in-flight
 * AI generation session from every page. Clicking the banner navigates to
 * the review / progress page for the live session — solves the QA report
 * where the user got "active session already exists" on a position page
 * but had no link to the actual session waiting on another page.
 *
 * Polls `/sessions/active` (and listens to `compgen.session.updated` over
 * WS) so the banner reacts to status changes without a hard refresh.
 * Dismissable per session id (sessionStorage) — reload restores it so
 * the user can keep working but is always one click away from finishing
 * the generation.
 */
export function AIGenerationBanner() {
  const t = useTranslations("common");
  const [session, setSession] = useState<CompetenceGenerationSession | null>(
    null,
  );
  const [dismissed, setDismissed] = useState<boolean>(false);
  const pathname = usePathname();

  const refresh = useCallback(async () => {
    try {
      const sess = await competenceGenerationApi.getActive();
      if (sess && VISIBLE_STATUSES.includes(sess.status)) {
        setSession(sess);
        setDismissed(isDismissed(sess.id));
      } else {
        setSession(null);
        setDismissed(false);
      }
    } catch {
      // Banner is decorative — never error-toast on a polling fault.
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh();
  }, [refresh]);

  // WS push shortens latency; REST polling is the source of truth.
  useWebSocketEvent("compgen.session.updated", refresh);

  // HRP-232: poll whenever an active session is being tracked, regardless of
  // WS state. The interval doesn't tear down on every refresh because the
  // dep is the status string, not the session object.
  const sessionStatus = session?.status ?? null;
  useEffect(() => {
    if (!shouldPollGenerationBanner(sessionStatus)) return;
    const tick = () => {
      if (typeof document !== "undefined" && document.hidden) return;
      void refresh();
    };
    const id = setInterval(tick, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [sessionStatus, refresh]);

  if (!session || dismissed) return null;

  const route = activeSessionRoute(session);
  // Don't shout at the user when they're already on the session's page —
  // the inline status card on that page already covers them.
  if (pathname && route.startsWith(pathname.split("?")[0])) return null;

  const scopeKey = SCOPE_LABEL_KEY[session.scope];
  const scopeLabel = scopeKey ? t(scopeKey) : t("aiGeneration");
  const statusKey = STATUS_LABEL_KEY[session.status];
  const statusLabel = statusKey ? t(statusKey) : session.status;

  return (
    <div
      data-testid="ai-generation-banner"
      className="flex items-center justify-between gap-3 border-b border-primary/20 bg-primary/5 px-4 py-2 text-sm"
    >
      <div className="flex items-center gap-2 min-w-0">
        <Sparkles className="h-4 w-4 shrink-0 text-primary" />
        <span className="truncate">
          {t.rich("aiGenerationBanner", {
            scope: scopeLabel,
            status: statusLabel,
            strong: (chunks) => <strong>{chunks}</strong>,
          })}
        </span>
      </div>
      <div className="flex items-center gap-1 shrink-0">
        <Button
          size="sm"
          variant="default"
          data-testid="ai-generation-banner-open"
          render={<Link href={route} />}
        >
          {t("openSession")}
        </Button>
        <Button
          size="icon"
          variant="ghost"
          aria-label={t("dismiss")}
          data-testid="ai-generation-banner-dismiss"
          onClick={() => {
            rememberDismissal(session.id);
            setDismissed(true);
          }}
        >
          <X className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
