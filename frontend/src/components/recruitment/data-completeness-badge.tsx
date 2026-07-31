"use client";

import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { CheckCircle, AlertTriangle, XCircle } from "lucide-react";

interface DataCompletenessBadgeProps {
  level: "full" | "partial" | "missing";
}

/** `labelKey` points at the `recruitment` i18n namespace. */
const config = {
  full: {
    icon: CheckCircle,
    labelKey: "completenessFull",
    className:
      "bg-[color-mix(in_oklch,var(--rec-data-full)_15%,transparent)] text-[var(--rec-data-full)]",
  },
  partial: {
    icon: AlertTriangle,
    labelKey: "completenessPartial",
    className:
      "bg-[color-mix(in_oklch,var(--rec-data-partial)_15%,transparent)] text-[var(--rec-data-partial)]",
  },
  missing: {
    icon: XCircle,
    labelKey: "completenessMissing",
    className:
      "bg-[color-mix(in_oklch,var(--rec-data-missing)_15%,transparent)] text-[var(--rec-data-missing)]",
  },
} as const;

export function DataCompletenessBadge({ level }: DataCompletenessBadgeProps) {
  const t = useTranslations("recruitment");
  const { icon: Icon, labelKey, className } = config[level];
  const label = t(labelKey);

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
