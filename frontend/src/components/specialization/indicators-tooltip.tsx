"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { specializationsApi, type IndicatorByLevel } from "@/lib/api/specializations";
import { skillLevelLabel } from "@/lib/reference-labels";

type Props = {
  competenceId: string;
  competenceTitle: string | null;
  selectedLevelId: string | null;
  selectedLevelSortIndex: number | null;
  onClose: () => void;
};

export function IndicatorsTooltip({
  competenceId,
  competenceTitle,
  selectedLevelId,
  selectedLevelSortIndex,
  onClose,
}: Props) {
  const t = useTranslations("company");
  const tc = useTranslations("common");
  const tRef = useTranslations("reference");
  const [data, setData] = useState<IndicatorByLevel[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const rows = await specializationsApi.indicatorsByLevel(competenceId);
        if (!cancelled) setData(rows);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : t("toastLoadFailed"));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [competenceId, t]);

  const upToSelected = data
    ? selectedLevelSortIndex == null
      ? []
      : data.filter((row) => row.skill_level_sort_index <= selectedLevelSortIndex)
    : [];

  // HRP-479: group by the level id, not the (now localizable) title —
  // the id also feeds the section testid so it stays locale-independent.
  const grouped = upToSelected.reduce<Record<string, IndicatorByLevel[]>>(
    (acc, row) => {
      const key = row.skill_level_id;
      if (!acc[key]) acc[key] = [];
      acc[key].push(row);
      return acc;
    },
    {},
  );

  const orderedLevels = Object.entries(grouped).sort(
    ([, a], [, b]) =>
      (a[0]?.skill_level_sort_index ?? 0) - (b[0]?.skill_level_sort_index ?? 0),
  );

  const includesPrior = orderedLevels.length > 1;

  return (
    <div
      data-testid="matrix-indicators-tooltip"
      className="fixed inset-0 z-50 flex items-center justify-center bg-background/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="max-h-[80vh] w-[min(560px,90vw)] overflow-y-auto rounded-lg border bg-background p-5 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="text-base font-semibold">
              {competenceTitle ?? t("competence")}
            </h3>
            {selectedLevelId == null ? (
              <p className="text-xs text-muted-foreground">
                {t("indicatorsNoLevelSelected")}
              </p>
            ) : (
              <p className="text-xs text-muted-foreground">
                {includesPrior
                  ? t("indicatorsForLevelWithPrior")
                  : t("indicatorsForLevel")}
              </p>
            )}
          </div>
          <button
            type="button"
            data-testid="matrix-indicators-tooltip-close"
            className="text-sm text-muted-foreground hover:text-foreground"
            onClick={onClose}
          >
            ×
          </button>
        </div>

        <div className="mt-4 space-y-4">
          {error && (
            <p className="text-sm text-destructive">{error}</p>
          )}
          {!data && !error && (
            <p className="text-sm text-muted-foreground">{tc("loading")}</p>
          )}
          {data && upToSelected.length === 0 && !error && (
            <p className="text-sm text-muted-foreground">
              {t("indicatorsEmpty")}
            </p>
          )}
          {orderedLevels.map(([levelId, rows]) => (
            // HRP-157 item 2: each level becomes its own section with a
            // bordered separator and bullet-marked list. Long lists get an
            // internal scroll so the modal stays a fixed height.
            <section
              key={levelId}
              data-testid={`matrix-indicators-section-${levelId}`}
              className="rounded-md border bg-muted/20 p-3"
            >
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {skillLevelLabel(tRef, {
                  title: rows[0]?.skill_level_title ?? "",
                  i18n_key: rows[0]?.skill_level_i18n_key,
                })}
              </p>
              <div className="mt-2 max-h-60 overflow-y-auto pr-1">
                <ul className="list-disc space-y-1 pl-5 text-sm">
                  {rows.map((row) => (
                    <li key={row.id} className="leading-snug">
                      {row.title}
                    </li>
                  ))}
                </ul>
              </div>
            </section>
          ))}
        </div>
      </div>
    </div>
  );
}
