"use client";

import { useEffect, useState } from "react";
import { AlertCircle, Loader2, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import {
  CompetenceGenerationSession,
  OtherActiveSession,
  competenceGenerationApi,
} from "@/lib/api/competence-generation";
import {
  GenerationConfirmDialog,
  type GenerationConfirmSubmit,
} from "./GenerationConfirmDialog";
import { PreflightModal } from "./PreflightModal";

interface Prerequisites {
  hasSpecializations: boolean;
  hasSkillLevels: boolean;
  hasAiSettings: boolean;
}

export interface GenerationStatusButtonProps {
  /** Total competences in the tenant tree — drives the «generate vs extend» wording. */
  totalCompetences: number;
  activeSession: CompetenceGenerationSession | null;
  /** HRP-122 re-spec: true while the page is still resolving the active
   * session. Surfaces a `Checking session…` button state so the user can't
   * click `Generate` and land on a stale "no session yet" drawer when a
   * session was already in flight before the page loaded. */
  activeSessionLoading?: boolean;
  onCreated: (sessionId: string) => void;
  /** Called when user clicks while a session is ready/error/running — opens drawer. */
  onOpenDrawer: () => void;
}

export function GenerationStatusButton({
  totalCompetences,
  activeSession,
  activeSessionLoading = false,
  onCreated,
  onOpenDrawer,
}: GenerationStatusButtonProps) {
  const [prereq, setPrereq] = useState<Prerequisites | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [preflightOpen, setPreflightOpen] = useState(false);
  const [others, setOthers] = useState<OtherActiveSession[]>([]);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [specs, levels, settings] = await Promise.all([
          api
            .get<{ id: string }[]>("/dictionaries/specialization")
            .catch(() => []),
          api.get<{ id: string }[]>("/skill-levels").catch(() => []),
          api.get<unknown>("/admin/ai-settings").catch(() => null),
        ]);
        if (cancelled) return;
        setPrereq({
          hasSpecializations: specs.length > 0,
          hasSkillLevels: levels.length > 0,
          hasAiSettings: settings != null,
        });
      } catch {
        if (!cancelled) {
          setPrereq({
            hasSpecializations: false,
            hasSkillLevels: false,
            hasAiSettings: false,
          });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const status = activeSession?.status ?? null;
  const errored = status === "error";
  const running = status === "pending" || status === "running";
  const ready = status === "ready";

  const prereqMissing = prereq
    ? !prereq.hasSpecializations || !prereq.hasSkillLevels
    : false;
  const prereqHint = !prereq
    ? null
    : !prereq.hasSpecializations
      ? "Add at least one specialization"
      : !prereq.hasSkillLevels
        ? "Create skill levels first"
        : null;

  async function handleClick() {
    if (showLoading) {
      // HRP-122 re-spec: the button is disabled in this state, but guard
      // here too so a hypothetical aria-trigger can't slip through and
      // open the "no session" empty drawer.
      return;
    }
    if (running || ready || errored) {
      onOpenDrawer();
      return;
    }
    // HRP-122 re-spec: re-check the server right before opening Confirm so
    // a session that landed between the page's initial fetch and the click
    // (WS-down tab, other-window action) routes us to the existing drawer
    // instead of producing a 409 the user has to resolve manually.
    try {
      const live = await competenceGenerationApi.getActive();
      if (live && (live.status === "pending" || live.status === "running" || live.status === "ready")) {
        onOpenDrawer();
        return;
      }
    } catch {
      // best-effort
    }
    // Preflight — show modal if other admins are running sessions.
    try {
      const o = await competenceGenerationApi.getActiveOthers();
      if (o.length > 0) {
        setOthers(o);
        setPreflightOpen(true);
        return;
      }
    } catch {
      // best-effort, continue to confirm
    }
    setConfirmOpen(true);
  }

  async function handleStart(params: GenerationConfirmSubmit) {
    setCreating(true);
    try {
      const sess = await competenceGenerationApi.create({
        scope: "whole_base",
        params,
      });
      onCreated(sess.id);
    } finally {
      setCreating(false);
    }
  }

  // ---- visual state ----------------------------------------------------
  let label: string;
  let testId: string;
  let icon = <Sparkles className="mr-1 h-4 w-4" />;
  let variant: "default" | "outline" | "destructive" = "default";
  // HRP-122 re-spec: surface a dedicated "checking session" state so the
  // user can't dispatch a fresh generation before the page knows whether
  // an active session already exists for them.
  const showLoading = activeSessionLoading && !activeSession;
  let buttonState: "loading" | "idle" | "active-session" | "error";

  if (showLoading) {
    label = "Checking session…";
    testId = "compgen-btn-checking";
    icon = <Loader2 className="mr-1 h-4 w-4 animate-spin" />;
    variant = "outline";
    buttonState = "loading";
  } else if (running) {
    label = "AI generation in progress";
    testId = "compgen-btn-running";
    icon = <Loader2 className="mr-1 h-4 w-4 animate-spin" />;
    variant = "outline";
    buttonState = "active-session";
  } else if (ready) {
    label = "Open active AI session";
    testId = "compgen-btn-active-session";
    buttonState = "active-session";
  } else if (errored) {
    label = "Generation error";
    testId = "compgen-btn-error";
    icon = <AlertCircle className="mr-1 h-4 w-4" />;
    variant = "destructive";
    buttonState = "error";
  } else if (totalCompetences > 0) {
    label = "Extend library with AI";
    testId = "compgen-btn-extend-base";
    variant = "outline";
    buttonState = "idle";
  } else {
    label = "Generate library with AI";
    testId = "compgen-btn-generate-base";
    buttonState = "idle";
  }

  return (
    <>
      <Button
        data-testid={testId}
        data-state-machine={`compgen-btn-state-${buttonState}`}
        size="sm"
        variant={variant}
        onClick={handleClick}
        disabled={
          showLoading ||
          (prereqMissing && !running && !ready && !errored)
        }
        title={prereqMissing && prereqHint ? prereqHint : undefined}
        aria-live="polite"
        aria-busy={showLoading || undefined}
      >
        {icon}
        {label}
      </Button>

      <GenerationConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        scope="whole_base"
        hasExistingLibrary={totalCompetences > 0}
        onSubmit={async (params) => {
          await handleStart(params);
        }}
      />

      <PreflightModal
        open={preflightOpen}
        onOpenChange={setPreflightOpen}
        hasOwnSession={!!activeSession}
        onGoToOwn={onOpenDrawer}
        others={others}
      />

      {creating && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
          <div className="rounded-md bg-background px-4 py-3 text-sm shadow">
            Starting AI generation…
          </div>
        </div>
      )}
    </>
  );
}
