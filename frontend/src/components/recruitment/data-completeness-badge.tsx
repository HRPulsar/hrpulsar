"use client";

import { cn } from "@/lib/utils";
import { CheckCircle, AlertTriangle, XCircle } from "lucide-react";

interface DataCompletenessBadgeProps {
  level: "full" | "partial" | "missing";
}

const config = {
  full: {
    icon: CheckCircle,
    label: "Complete",
    className:
      "bg-[color-mix(in_oklch,var(--rec-data-full)_15%,transparent)] text-[var(--rec-data-full)]",
  },
  partial: {
    icon: AlertTriangle,
    label: "Partial",
    className:
      "bg-[color-mix(in_oklch,var(--rec-data-partial)_15%,transparent)] text-[var(--rec-data-partial)]",
  },
  missing: {
    icon: XCircle,
    label: "Missing",
    className:
      "bg-[color-mix(in_oklch,var(--rec-data-missing)_15%,transparent)] text-[var(--rec-data-missing)]",
  },
} as const;

export function DataCompletenessBadge({ level }: DataCompletenessBadgeProps) {
  const { icon: Icon, label, className } = config[level];

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
        className,
      )}
      title={label}
      data-testid="data-completeness-badge"
    >
      <Icon className="size-3" />
      {label}
    </span>
  );
}
