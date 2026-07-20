"use client";

import { Loader2, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { ActiveAiSession } from "@/hooks/use-active-ai-sessions";

interface ActiveAiSessionBadgeProps {
  sessions: ActiveAiSession[];
  /** Called with the first own session id, or — when no own session is in
   * the bucket — the first other session id. The drawer accepts either and
   * loads the snapshot read-only when the caller is not the owner. */
  onOpen: (sessionId: string) => void;
  testIdSuffix?: string;
  className?: string;
}

/**
 * Small "live AI session" affordance: animated sparkles + tooltip naming
 * who is running it (you / another admin). Clicking it opens the drawer on
 * the relevant session — used in the competences tree, the specialization
 * matrix, and the position detail page so reviewers see the in-flight work
 * at a glance (HRP-93 Part 2).
 */
export function ActiveAiSessionBadge({
  sessions,
  onOpen,
  testIdSuffix,
  className,
}: ActiveAiSessionBadgeProps) {
  if (!sessions.length) return null;
  const own = sessions.find((s) => s.kind === "own");
  const target = own ?? sessions[0];
  const spinning = sessions.some(
    (s) => s.status === "pending" || s.status === "running",
  );
  const others = sessions.filter(
    (s): s is Extract<ActiveAiSession, { kind: "other" }> => s.kind === "other",
  );
  const labelTitle = own
    ? "Your AI generation is in progress"
    : `${others[0].user_full_name} is running AI generation`;
  // "+N more" — N = others not already named in labelTitle.
  const namedOthers = own ? 0 : 1;
  const extraCount = others.length - namedOthers;
  const labelExtra = extraCount > 0 ? ` (+${extraCount} more)` : "";

  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <button
            type="button"
            data-testid={
              testIdSuffix
                ? `compgen-active-badge-${testIdSuffix}`
                : "compgen-active-badge"
            }
            onClick={(e) => {
              e.stopPropagation();
              e.preventDefault();
              onOpen(target.session_id);
            }}
            className={cn(
              "inline-flex h-5 w-5 items-center justify-center rounded-full",
              "bg-primary/15 text-primary ring-1 ring-primary/30",
              "transition hover:bg-primary/25 hover:ring-primary/50",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary",
              className,
            )}
            aria-label={labelTitle + labelExtra}
          />
        }
      >
        {spinning ? (
          <Loader2 className="h-3 w-3 animate-spin" />
        ) : (
          <Sparkles className="h-3 w-3" />
        )}
      </TooltipTrigger>
      <TooltipContent side="top" className="text-xs">
        {labelTitle}
        {labelExtra}
      </TooltipContent>
    </Tooltip>
  );
}
