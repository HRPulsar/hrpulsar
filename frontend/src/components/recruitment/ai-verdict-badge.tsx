"use client";

import * as Popover from "@radix-ui/react-popover";
import {
  AlertTriangle,
  CheckCircle2,
  CircleHelp,
  Info,
  XCircle,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { BADGE_COLOR } from "@/lib/badge-tones";
import type { AiReadiness, AiVerdict } from "@/lib/recruitment-types";

interface VerdictConfig {
  label: string;
  icon: typeof CheckCircle2;
  chipClass: string;
}

const VERDICT_CONFIG: Record<AiVerdict, VerdictConfig> = {
  pending: { label: "Pending", icon: CircleHelp, chipClass: BADGE_COLOR.neutral },
  recommended: { label: "Recommended", icon: CheckCircle2, chipClass: BADGE_COLOR.emerald },
  needs_check: { label: "Needs check", icon: AlertTriangle, chipClass: BADGE_COLOR.amber },
  not_recommended: { label: "Not recommended", icon: XCircle, chipClass: BADGE_COLOR.rose },
};

const READINESS_TEXT: Record<AiReadiness, string> = {
  none: "no resume parsed yet",
  resume_only: "resume only",
  resume_and_transcript: "resume + interview transcript",
};

interface Props {
  verdict: AiVerdict;
  aiScore?: number | null;
  aiReadiness?: AiReadiness;
  // HRP-204: mode of the active AI analysis run. ``resume_only``
  // renders an amber sub-badge with a tooltip ("Based on resume only
  // — interview required for full assessment"); ``full`` renders an
  // emerald sub-badge. ``null`` / ``undefined`` hides the sub-badge.
  analysisMode?: "resume_only" | "full" | null;
  scoreDivergence?: boolean;
  summary?: string | null;
  keyStrength?: string | null;
  keyRisk?: string | null;
  riskMitigation?: string | null;
  testIdPrefix?: string;
}

export function AiVerdictBadge({
  verdict,
  aiScore = null,
  aiReadiness,
  analysisMode,
  scoreDivergence = false,
  summary,
  keyStrength,
  keyRisk,
  riskMitigation,
  testIdPrefix,
}: Props) {
  const cfg = VERDICT_CONFIG[verdict];
  const Icon = cfg.icon;
  const hasDetails = verdict !== "pending" &&
    (summary || keyStrength || keyRisk || riskMitigation);

  const badge = (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
        cfg.chipClass,
      )}
      data-testid={
        testIdPrefix ? `${testIdPrefix}-ai-verdict-badge` : undefined
      }
    >
      <Icon className="size-3" aria-hidden />
      <span>{cfg.label}</span>
    </span>
  );

  const modeSubBadge =
    analysisMode === "resume_only" || analysisMode === "full" ? (
      <span
        className={cn(
          "inline-flex items-center rounded-full border px-1.5 py-0.5 text-[10px] uppercase tracking-wide",
          analysisMode === "resume_only"
            ? "border-amber-300 text-amber-800 dark:border-amber-700 dark:text-amber-300"
            : "border-emerald-300 text-emerald-800 dark:border-emerald-700 dark:text-emerald-300",
        )}
        title={
          analysisMode === "resume_only"
            ? "Based on resume only — interview required for full assessment"
            : "Based on resume and interview transcript"
        }
        data-testid={
          testIdPrefix
            ? `${testIdPrefix}-ai-analysis-mode-badge-${analysisMode}`
            : `ai-analysis-mode-badge-${analysisMode}`
        }
      >
        {analysisMode === "resume_only" ? "resume only" : "full"}
      </span>
    ) : null;

  return (
    <span className="inline-flex items-center gap-1 align-middle">
      {badge}
      {modeSubBadge}
      {aiScore !== null && aiScore !== undefined && (
        <span className="text-xs tabular-nums text-muted-foreground">
          {/* Canonical raw 0..1 scale (HRP-274) — two decimals. */}
          {aiScore.toFixed(2)}
        </span>
      )}
      {scoreDivergence && (
        <span
          className="inline-flex items-center text-amber-700 dark:text-amber-300"
          title="Manager and AI scores disagree by ≥ 1.0"
          aria-label="Manager and AI scores disagree by at least 1.0"
          data-testid={
            testIdPrefix
              ? `${testIdPrefix}-score-divergence-marker`
              : undefined
          }
        >
          <AlertTriangle className="size-3.5" aria-hidden />
        </span>
      )}
      {hasDetails && (
        <Popover.Root>
          <Popover.Trigger
            type="button"
            className="inline-flex items-center justify-center text-muted-foreground transition-colors hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-full"
            aria-label="AI verdict details"
            data-testid={
              testIdPrefix
                ? `${testIdPrefix}-ai-verdict-info-btn`
                : undefined
            }
          >
            <Info className="size-3.5" aria-hidden />
          </Popover.Trigger>
          <Popover.Portal>
            <Popover.Content
              align="end"
              sideOffset={6}
              className="z-50 w-[360px] max-w-[90vw] rounded-md border bg-popover p-4 text-popover-foreground shadow-md outline-none"
              data-testid={
                testIdPrefix
                  ? `${testIdPrefix}-ai-verdict-popover`
                  : "ai-verdict-popover"
              }
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-2">
                  <Icon className="size-4" aria-hidden />
                  <span className="text-sm font-semibold">{cfg.label}</span>
                </div>
                {aiScore !== null && aiScore !== undefined && (
                  <span className="text-xs tabular-nums text-muted-foreground">
                    Score {aiScore.toFixed(2)}
                  </span>
                )}
              </div>
              {summary && (
                <p className="mt-2 text-sm text-foreground/90">{summary}</p>
              )}
              <dl className="mt-3 space-y-2 text-xs">
                {keyStrength && (
                  <div>
                    <dt className="font-medium text-foreground">
                      Key strength
                    </dt>
                    <dd className="text-muted-foreground">{keyStrength}</dd>
                  </div>
                )}
                {keyRisk && (
                  <div>
                    <dt className="font-medium text-foreground">Key risk</dt>
                    <dd className="text-muted-foreground">{keyRisk}</dd>
                  </div>
                )}
                {riskMitigation && (
                  <div>
                    <dt className="font-medium text-foreground">
                      Risk mitigation
                    </dt>
                    <dd className="text-muted-foreground">{riskMitigation}</dd>
                  </div>
                )}
              </dl>
              {aiReadiness && (
                <p className="mt-3 border-t pt-2 text-[11px] text-muted-foreground">
                  Based on: {READINESS_TEXT[aiReadiness]}
                </p>
              )}
            </Popover.Content>
          </Popover.Portal>
        </Popover.Root>
      )}
    </span>
  );
}
