"use client";

import * as Popover from "@radix-ui/react-popover";
import {
  AlertTriangle,
  CheckCircle2,
  CircleHelp,
  Info,
  Loader2,
  XCircle,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { BADGE_COLOR } from "@/lib/badge-tones";
import { aiVerdictCellState } from "@/lib/recruitment-types";
import type { AiReadiness, AiVerdict } from "@/lib/recruitment-types";

interface VerdictConfig {
  /** Key in the `recruitment` i18n namespace. */
  labelKey: string;
  icon: typeof CheckCircle2;
  chipClass: string;
}

const VERDICT_CONFIG: Record<AiVerdict, VerdictConfig> = {
  pending: { labelKey: "verdictPending", icon: CircleHelp, chipClass: BADGE_COLOR.neutral },
  recommended: { labelKey: "verdictRecommended", icon: CheckCircle2, chipClass: BADGE_COLOR.emerald },
  needs_check: { labelKey: "verdictNeedsCheck", icon: AlertTriangle, chipClass: BADGE_COLOR.amber },
  not_recommended: { labelKey: "verdictNotRecommended", icon: XCircle, chipClass: BADGE_COLOR.rose },
};

const READINESS_TEXT_KEYS: Record<AiReadiness, string> = {
  none: "verdictReadinessNone",
  resume_only: "verdictReadinessResumeOnly",
  resume_and_transcript: "verdictReadinessResumeAndTranscript",
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
  /** HRP-493: a run is queued or executing for this pair right now. */
  inProgress?: boolean;
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
  inProgress = false,
  summary,
  keyStrength,
  keyRisk,
  riskMitigation,
  testIdPrefix,
}: Props) {
  const t = useTranslations("recruitment");
  const cfg = VERDICT_CONFIG[verdict];
  const Icon = cfg.icon;
  const label = t(cfg.labelKey);
  const hasDetails = verdict !== "pending" &&
    (summary || keyStrength || keyRisk || riskMitigation);

  // HRP-493: "an analysis is running" and "nothing has ever run" both
  // arrive as ``verdict === "pending"``. Splitting them is the whole
  // point of the AI VERDICT column: a spinner tells the recruiter to
  // wait, a bare icon tells them to press Analyze.
  const cellState = aiVerdictCellState({ verdict, readiness: aiReadiness, inProgress });

  if (cellState === "analyzing") {
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium align-middle",
          BADGE_COLOR.neutral,
        )}
        title={t("verdictAnalyzing")}
        data-testid={
          testIdPrefix ? `${testIdPrefix}-ai-verdict-analyzing` : undefined
        }
      >
        <Loader2 className="size-3 animate-spin" aria-hidden />
        <span>{t("verdictAnalyzing")}</span>
      </span>
    );
  }

  // No resume means no analysis is even possible yet — a "Pending"
  // chip overstated that as work already under way.
  if (cellState === "no-analysis") {
    return (
      <span
        className="inline-flex items-center align-middle text-muted-foreground"
        title={t("verdictNoAnalysisYet")}
        aria-label={t("verdictNoAnalysisYet")}
        data-testid={
          testIdPrefix ? `${testIdPrefix}-ai-verdict-none` : undefined
        }
      >
        <CircleHelp className="size-3.5" aria-hidden />
      </span>
    );
  }

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
      <span>{label}</span>
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
            ? t("verdictModeResumeOnlyTooltip")
            : t("verdictModeFullTooltip")
        }
        data-testid={
          testIdPrefix
            ? `${testIdPrefix}-ai-analysis-mode-badge-${analysisMode}`
            : `ai-analysis-mode-badge-${analysisMode}`
        }
      >
        {analysisMode === "resume_only"
          ? t("verdictModeResumeOnly")
          : t("verdictModeFull")}
      </span>
    ) : null;

  return (
    <span className="inline-flex items-center gap-1 align-middle">
      {badge}
      {modeSubBadge}
      {/* HRP-493: the candidates table no longer passes ``aiScore`` —
          the AI column two cells to the left already shows it, and the
          divergence marker that used to follow restated the amber
          highlight on the MANAGER / AI cells. Surfaces without those
          columns (the candidate card's application list) still pass it
          and still get the number. */}
      {aiScore !== null && aiScore !== undefined && (
        <span className="text-xs tabular-nums text-muted-foreground">
          {/* Canonical raw 0..1 scale (HRP-274) — two decimals. */}
          {aiScore.toFixed(2)}
        </span>
      )}
      {hasDetails && (
        <Popover.Root>
          <Popover.Trigger
            type="button"
            className="inline-flex items-center justify-center text-muted-foreground transition-colors hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-full"
            aria-label={t("verdictDetailsAria")}
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
                  <span className="text-sm font-semibold">{label}</span>
                </div>
                {aiScore !== null && aiScore !== undefined && (
                  <span className="text-xs tabular-nums text-muted-foreground">
                    {t("verdictScore", { score: aiScore.toFixed(2) })}
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
                      {t("verdictKeyStrength")}
                    </dt>
                    <dd className="text-muted-foreground">{keyStrength}</dd>
                  </div>
                )}
                {keyRisk && (
                  <div>
                    <dt className="font-medium text-foreground">
                      {t("verdictKeyRisk")}
                    </dt>
                    <dd className="text-muted-foreground">{keyRisk}</dd>
                  </div>
                )}
                {riskMitigation && (
                  <div>
                    <dt className="font-medium text-foreground">
                      {t("verdictRiskMitigation")}
                    </dt>
                    <dd className="text-muted-foreground">{riskMitigation}</dd>
                  </div>
                )}
              </dl>
              {aiReadiness && (
                <p className="mt-3 border-t pt-2 text-[11px] text-muted-foreground">
                  {t("verdictBasedOn", {
                    readiness: t(READINESS_TEXT_KEYS[aiReadiness]),
                  })}
                </p>
              )}
            </Popover.Content>
          </Popover.Portal>
        </Popover.Root>
      )}
    </span>
  );
}
