"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { Sparkles } from "lucide-react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useActiveAiSessions } from "@/hooks/use-active-ai-sessions";
import { findMatrixSessionForSpec } from "@/lib/active-ai-session-match";
import { activeSessionRoute } from "@/lib/active-ai-session-route";
import type { Position } from "@/lib/types";

interface Props {
  position: Position;
  /** Kept so the position detail page can rerun its loader after the spec
   * AI-generate flow returns the user here. Unused by this card itself —
   * the apply step lives on the spec page. */
  onApplied?: () => void;
}

/**
 * HRP-33 REDO: the AI matrix flow no longer renders inline on the position
 * page — the QA report asked that the operator be taken to the
 * specialization page where the matrix actually lives. The card here is a
 * single CTA that routes the user to
 * `/company/specializations/<spec>/ai-generate?position=<pos>`. The
 * specialization page picks up the `position` query param to (a) preselect
 * the position's grade as required, (b) tag the session with `position_id`
 * so the global banner can find its way back, and (c) return the user to
 * the position page on Apply.
 *
 * `onApplied` is part of the original signature so callers don't break;
 * it's a no-op until the user returns from the spec flow.
 */
export function PositionAIGenerationCard({ position }: Props) {
  const t = useTranslations("company");
  const { all: activeSessions } = useActiveAiSessions();
  const liveSession = findMatrixSessionForSpec(
    activeSessions,
    position.specialization_id,
  );

  const blocked = !position.specialization_id;
  const generateHref = position.specialization_id
    ? `/company/specializations/${position.specialization_id}/ai-generate?position=${position.id}`
    : null;
  const liveSessionHref = liveSession
    ? activeSessionRoute({
        id: liveSession.session_id,
        scope: liveSession.scope,
        target_id: liveSession.target_id,
        status: liveSession.status,
        // HRP-33 review fix: route to the session's true originating
        // position. When the session belongs to another position on the
        // same spec, dropping the operator onto *this* position would be
        // misleading; when the session is standalone, drop the position
        // segment so Apply ends up on the spec page (where the matrix
        // was launched from).
        params: { position_id: liveSession.position_id },
      })
    : null;

  return (
    <Card data-testid="position-ai-generation-card">
      <CardHeader className="flex-row items-center justify-between gap-4">
        <div>
          <CardTitle className="flex items-center gap-2 text-base">
            <Sparkles className="h-4 w-4 text-primary" />
            {t("aiGenerateCompetences")}
          </CardTitle>
          <CardDescription>{t("aiGenerateCardDescription")}</CardDescription>
        </div>
        {liveSessionHref ? (
          <Button
            size="sm"
            variant="default"
            data-testid="position-detail-btn-ai-resume"
            render={<Link href={liveSessionHref} />}
          >
            <Sparkles className="mr-1 h-4 w-4" />
            {t("openActiveSession")}
          </Button>
        ) : generateHref ? (
          <Button
            size="sm"
            data-testid="position-detail-btn-ai-generate"
            render={<Link href={generateHref} />}
          >
            <Sparkles className="mr-1 h-4 w-4" />
            {t("aiGenerate")}
          </Button>
        ) : (
          <Button
            size="sm"
            data-testid="position-detail-btn-ai-generate"
            disabled
          >
            <Sparkles className="mr-1 h-4 w-4" />
            {t("aiGenerate")}
          </Button>
        )}
      </CardHeader>
      {blocked ? (
        <CardContent>
          <p
            data-testid="position-ai-generation-blocked"
            className="text-sm text-muted-foreground"
          >
            {t("aiGenerateBlocked")}
          </p>
        </CardContent>
      ) : null}
    </Card>
  );
}
