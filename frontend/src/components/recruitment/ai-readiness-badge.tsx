"use client";

import { FileText, Mic, MinusCircle } from "lucide-react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import type { AiReadiness } from "@/lib/recruitment-types";

/** `labelKey` / `tooltipKey` point at the `recruitment` i18n namespace. */
const READINESS_CONFIG: Record<
  AiReadiness,
  { labelKey: string; tooltipKey: string; tone: string }
> = {
  none: {
    labelKey: "readinessLabelNone",
    tooltipKey: "readinessTooltipNone",
    tone: "text-muted-foreground",
  },
  resume_only: {
    labelKey: "readinessLabelResumeOnly",
    tooltipKey: "readinessTooltipResumeOnly",
    tone: "text-muted-foreground",
  },
  resume_and_transcript: {
    labelKey: "readinessLabelResumeAndTranscript",
    tooltipKey: "readinessTooltipResumeAndTranscript",
    tone: "text-emerald-700 dark:text-emerald-400",
  },
};

interface Props {
  readiness: AiReadiness;
  testId?: string;
}

export function AiReadinessBadge({ readiness, testId }: Props) {
  const t = useTranslations("recruitment");
  const cfg = READINESS_CONFIG[readiness];
  const label = t(cfg.labelKey);
  const tooltip = t(cfg.tooltipKey);

  if (readiness === "none") {
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1 text-xs",
          cfg.tone,
        )}
        title={tooltip}
        aria-label={tooltip}
        data-testid={testId}
      >
        <MinusCircle className="size-3.5" aria-hidden />
        <span className="sr-only">{label}</span>
      </span>
    );
  }

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full bg-muted/70 px-2 py-0.5 text-[11px] font-medium",
        cfg.tone,
      )}
      title={tooltip}
      aria-label={tooltip}
      data-testid={testId}
    >
      <FileText className="size-3" aria-hidden />
      {readiness === "resume_and_transcript" && (
        <Mic className="size-3" aria-hidden />
      )}
      <span>{label}</span>
    </span>
  );
}
