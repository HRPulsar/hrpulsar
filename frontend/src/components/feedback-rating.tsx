"use client";

import { ThumbsDown, ThumbsUp } from "lucide-react";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";
import type { FeedbackRating } from "@/lib/api/feedback";

/** Thumb up / thumb down toggle, shared by the header widget (HRP-586)
 * and the demo popup (HRP-587). `testIdPrefix` keeps the two surfaces
 * addressable separately in e2e. */
export function FeedbackRatingButtons({
  value,
  onChange,
  testIdPrefix,
}: {
  value: FeedbackRating | null;
  onChange: (value: FeedbackRating) => void;
  testIdPrefix: string;
}) {
  const t = useTranslations("feedback");
  return (
    <div className="flex gap-2">
      <button
        type="button"
        onClick={() => onChange("up")}
        aria-pressed={value === "up"}
        data-testid={`${testIdPrefix}-rating-up`}
        className={cn(
          "flex items-center gap-2 rounded-md border px-3 py-2 text-sm transition-colors",
          value === "up"
            ? "border-emerald-500 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
            : "border-border text-muted-foreground hover:bg-muted",
        )}
      >
        <ThumbsUp className="h-4 w-4" />
        {t("ratingUp")}
      </button>
      <button
        type="button"
        onClick={() => onChange("down")}
        aria-pressed={value === "down"}
        data-testid={`${testIdPrefix}-rating-down`}
        className={cn(
          "flex items-center gap-2 rounded-md border px-3 py-2 text-sm transition-colors",
          value === "down"
            ? "border-red-500 bg-red-500/10 text-red-600 dark:text-red-400"
            : "border-border text-muted-foreground hover:bg-muted",
        )}
      >
        <ThumbsDown className="h-4 w-4" />
        {t("ratingDown")}
      </button>
    </div>
  );
}
