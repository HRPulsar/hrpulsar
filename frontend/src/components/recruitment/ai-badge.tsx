"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import { Sparkles } from "lucide-react";

interface AIBadgeProps {
  source?: string;
  date?: string;
}

export function AIBadge({ source, date }: AIBadgeProps) {
  const [showTooltip, setShowTooltip] = useState(false);

  const hasTooltip = source || date;

  return (
    <span
      className="relative inline-flex items-center"
      onMouseEnter={() => setShowTooltip(true)}
      onMouseLeave={() => setShowTooltip(false)}
    >
      <span
        className="inline-flex items-center gap-0.5 rounded-full bg-[color-mix(in_oklch,var(--rec-ai-accent)_15%,transparent)] px-1.5 py-0.5 text-xs font-medium text-[var(--rec-ai-accent)]"
        data-testid="ai-badge"
      >
        <Sparkles className="size-3" />
        AI
      </span>
      {hasTooltip && showTooltip && (
        <span
          className={cn(
            "absolute bottom-full left-1/2 z-50 mb-1.5 -translate-x-1/2 whitespace-nowrap rounded-md bg-popover px-2.5 py-1.5 text-xs text-popover-foreground shadow-md ring-1 ring-foreground/10",
          )}
        >
          {source && <span className="block">Based on: {source}</span>}
          {date && <span className="block text-muted-foreground">{date}</span>}
        </span>
      )}
    </span>
  );
}
