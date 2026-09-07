"use client";

import { ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";

import type { AnswerOption } from "@/lib/types";
import { scaleOptionDescription, scaleOptionLabel } from "@/lib/reference-labels";

/**
 * HRP-721: the scale explained once, above the questions, instead of the
 * description trailing every option of every indicator ("Meets
 * Expectations — Meets the expected level", N indicators deep). Collapsed
 * by default — native `<details>`, same disclosure pattern as the
 * recruitment evaluation sheet.
 */
export function ScaleLegend({ options }: { options: AnswerOption[] }) {
  const t = useTranslations("assessments");
  const tRef = useTranslations("reference");

  const sorted = [...options].sort((a, b) => a.sort_index - b.sort_index);
  if (sorted.length === 0) return null;

  return (
    <details
      className="group rounded-md border bg-muted/20 p-3"
      data-testid="assessment-scale-legend"
    >
      <summary className="flex cursor-pointer list-none items-center gap-2 text-sm font-medium [&::-webkit-details-marker]:hidden">
        <ChevronRight
          aria-hidden="true"
          className="size-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-90"
        />
        {t("scaleLegendTitle")}
      </summary>
      <dl className="mt-2 space-y-1 text-sm">
        {sorted.map((opt) => (
          <div
            key={opt.id}
            className="flex flex-wrap gap-x-2"
            data-testid={`assessment-scale-legend-option-${opt.code}`}
          >
            <dt className="font-medium">{scaleOptionLabel(tRef, opt)}</dt>
            <dd className="text-muted-foreground">
              {scaleOptionDescription(tRef, opt)}
            </dd>
          </div>
        ))}
      </dl>
    </details>
  );
}
