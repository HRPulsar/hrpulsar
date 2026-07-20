"use client";

import { FileText, Mic, MinusCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import type { AiReadiness } from "@/lib/recruitment-types";

const READINESS_CONFIG: Record<
  AiReadiness,
  { label: string; tooltip: string; tone: string }
> = {
  none: {
    label: "—",
    tooltip: "No resume parsed yet",
    tone: "text-muted-foreground",
  },
  resume_only: {
    label: "Resume",
    tooltip: "Resume available. Upload interview for full analysis.",
    tone: "text-muted-foreground",
  },
  resume_and_transcript: {
    label: "Resume + interview",
    tooltip:
      "Resume + interview transcript available. AI analysis is complete.",
    tone: "text-emerald-700 dark:text-emerald-400",
  },
};

interface Props {
  readiness: AiReadiness;
  testId?: string;
}

export function AiReadinessBadge({ readiness, testId }: Props) {
  const cfg = READINESS_CONFIG[readiness];

  if (readiness === "none") {
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1 text-xs",
          cfg.tone,
        )}
        title={cfg.tooltip}
        aria-label={cfg.tooltip}
        data-testid={testId}
      >
        <MinusCircle className="size-3.5" aria-hidden />
        <span className="sr-only">{cfg.label}</span>
      </span>
    );
  }

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full bg-muted/70 px-2 py-0.5 text-[11px] font-medium",
        cfg.tone,
      )}
      title={cfg.tooltip}
      aria-label={cfg.tooltip}
      data-testid={testId}
    >
      <FileText className="size-3" aria-hidden />
      {readiness === "resume_and_transcript" && (
        <Mic className="size-3" aria-hidden />
      )}
      <span>{cfg.label}</span>
    </span>
  );
}
