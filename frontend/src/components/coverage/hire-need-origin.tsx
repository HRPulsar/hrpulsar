"use client";

// HRP-801 (QA 23.10, b-d): "Based on {process}" on a vacancy opened from a
// Coverage gap, and on its talent card - the way the card names the
// vacancy it was posted from. Recruitment and the talent market know
// nothing of Coverage, so the line asks the work side by vacancy or by card;
// the title links only for a reader who may open that coverage.

import { useEffect, useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { type HireNeedOrigin, workApi } from "@/lib/api/work";

export function HireNeedOriginLine({
  vacancyId,
  talentCardId,
  className,
}: {
  vacancyId?: string;
  talentCardId?: string;
  className?: string;
}) {
  const t = useTranslations("coverage");
  const [origin, setOrigin] = useState<HireNeedOrigin | null>(null);

  useEffect(() => {
    let live = true;
    const ask = vacancyId
      ? workApi.vacancyOrigin(vacancyId)
      : talentCardId
        ? workApi.talentCardOrigin(talentCardId)
        : Promise.resolve(null);
    // A line that fails to load is a line not shown: the page is the
    // vacancy's or the card's, not this one's.
    ask.then((found) => live && setOrigin(found)).catch(() => {});
    return () => {
      live = false;
    };
  }, [vacancyId, talentCardId]);

  if (!origin) return null;
  return (
    <div className={className} data-testid="hire-need-origin">
      <p className="text-muted-foreground">{t(`originLabel_${origin.type}`)}</p>
      {origin.can_open ? (
        <Link
          href={`/coverage/${origin.container_id}`}
          className="font-medium text-primary underline-offset-2 hover:underline"
          data-testid="hire-need-origin-link"
        >
          {origin.title}
        </Link>
      ) : (
        <p className="font-medium" data-testid="hire-need-origin-title">
          {origin.title}
        </p>
      )}
    </div>
  );
}
