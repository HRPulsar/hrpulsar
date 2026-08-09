"use client";

// HRP-359: the competence-scoring form shared between the internal
// Manager assessments section (candidate card) and the public invited
// evaluator page. Both render the same structure — competence accordion
// with an Overall radio row, expandable indicators and a comment — and
// must stay visually identical, so the JSX lives here once.

import { useTranslations } from "next-intl";
import { AlertTriangle, ChevronRight } from "lucide-react";

import {
  competenceScoreId,
  indicatorScoreId,
} from "@/lib/competence-ids";
import { criticalityConfig } from "@/components/recruitment/competence-tree-view";

export interface ScaleLevel {
  value: number;
  label: string;
  description?: string | null;
  weight: number;
  color?: string | null;
}

export interface CompetenceScore {
  id: string;
  competence_id: string;
  score_value: number | null;
  score_source: string;
  comment: string | null;
}

export interface IndicatorScore {
  id: string;
  indicator_id: string;
  competence_id: string;
  score_value: number | null;
  comment: string | null;
}

export interface ProfileIndicator {
  id: string;
  text: string;
}

export interface ProfileCompetence {
  id: string;
  name: string;
  criticality: "critical" | "important" | "desirable" | null;
  indicators: ProfileIndicator[];
}

export interface RawProfileCompetence {
  id?: string;
  name?: string;
  criticality?: string;
  indicators?: unknown[];
}

/** Normalize raw profile competences into stable score-row ids. */
export function toProfileCompetences(
  raw: RawProfileCompetence[],
): Promise<ProfileCompetence[]> {
  return Promise.all(
    raw
      .filter((comp) => comp.id || comp.name)
      .map(async (comp) => {
        const name = comp.name ?? "";
        const id = await competenceScoreId(comp.id, name);
        const indicatorTexts = (comp.indicators ?? []).flatMap((i) => {
          if (typeof i === "string") return i.trim() ? [i] : [];
          // Legacy shape: objects with a name field.
          const text = (i as { name?: string } | null)?.name;
          return text ? [text] : [];
        });
        const indicators = await Promise.all(
          indicatorTexts.map(async (text) => ({
            id: await indicatorScoreId(id, text),
            text,
          })),
        );
        const criticality =
          comp.criticality === "critical" ||
          comp.criticality === "important" ||
          comp.criticality === "desirable"
            ? comp.criticality
            : null;
        return { id, name: name || id, criticality, indicators };
      }),
  );
}

export function upsertCompetence(
  scores: CompetenceScore[],
  patch: Pick<CompetenceScore, "competence_id" | "score_value" | "comment">,
): CompetenceScore[] {
  const idx = scores.findIndex((c) => c.competence_id === patch.competence_id);
  if (idx === -1) {
    return [
      ...scores,
      {
        id: `tmp-${patch.competence_id}`,
        competence_id: patch.competence_id,
        score_value: patch.score_value,
        comment: patch.comment ?? null,
        score_source: "manual",
      },
    ];
  }
  const next = [...scores];
  next[idx] = {
    ...next[idx]!,
    score_value: patch.score_value,
    comment: patch.comment ?? null,
    score_source: "manual",
  };
  return next;
}

/** HRP-378: update only the note, leaving the score and its source alone. */
export function upsertCompetenceComment(
  scores: CompetenceScore[],
  competenceId: string,
  comment: string,
): CompetenceScore[] {
  const idx = scores.findIndex((c) => c.competence_id === competenceId);
  if (idx === -1) {
    return [
      ...scores,
      {
        id: `tmp-${competenceId}`,
        competence_id: competenceId,
        score_value: null,
        comment,
        score_source: "manual",
      },
    ];
  }
  const next = [...scores];
  next[idx] = { ...next[idx]!, comment };
  return next;
}

/** HRP-378: a manual overall drops the competence's indicator answers. */
export function clearIndicatorsFor(
  rows: IndicatorScore[],
  competenceId: string,
): IndicatorScore[] {
  return rows.filter((r) => r.competence_id !== competenceId);
}

export function replaceCompetenceRow(
  rows: CompetenceScore[],
  fresh: CompetenceScore,
): CompetenceScore[] {
  const idx = rows.findIndex((r) => r.competence_id === fresh.competence_id);
  return idx === -1
    ? [...rows, fresh]
    : rows.map((r, i) => (i === idx ? fresh : r));
}

export function replaceIndicatorRow(
  rows: IndicatorScore[],
  fresh: IndicatorScore,
): IndicatorScore[] {
  const idx = rows.findIndex((r) => r.indicator_id === fresh.indicator_id);
  return idx === -1
    ? [...rows, fresh]
    : rows.map((r, i) => (i === idx ? fresh : r));
}

export function upsertIndicator(
  scores: IndicatorScore[],
  patch: Pick<IndicatorScore, "indicator_id" | "competence_id" | "score_value">,
): IndicatorScore[] {
  const idx = scores.findIndex((s) => s.indicator_id === patch.indicator_id);
  if (idx === -1) {
    return [
      ...scores,
      {
        id: `tmp-${patch.indicator_id}`,
        indicator_id: patch.indicator_id,
        competence_id: patch.competence_id,
        score_value: patch.score_value,
        comment: null,
      },
    ];
  }
  const next = [...scores];
  next[idx] = { ...next[idx]!, score_value: patch.score_value };
  return next;
}

export function findCompetenceComment(
  sheet: { competence_scores: CompetenceScore[] } | null,
  competenceId: string,
): string {
  if (!sheet) return "";
  return (
    sheet.competence_scores.find((c) => c.competence_id === competenceId)
      ?.comment ?? ""
  );
}

/** HRP-374: "Evaluators disagree: Internal A P: 4, External Ivan Petrov: 2".
 *
 * Each entry is rendered through its own ICU message so the evaluator name
 * and the score stay translator-visible arguments rather than glued-together
 * substrings. */
function divergenceTooltip(
  t: (key: string, values?: Record<string, string | number>) => string,
  aggregate: CompetenceAggregate,
): string {
  const entries = aggregate.scorers.map((s) =>
    t(
      s.evaluator_type === "external"
        ? "evalSheetDivergenceEntryExternal"
        : "evalSheetDivergenceEntryInternal",
      { name: s.evaluator, score: s.score },
    ),
  );
  return t("evalSheetDivergenceTooltip", { entries: entries.join(", ") });
}

/** HRP-374: one competence's cross-evaluator roll-up for the round. */
export interface CompetenceAggregate {
  average: number;
  diverges: boolean;
  scorers: {
    evaluator: string;
    evaluator_type: "internal" | "external";
    score: number;
  }[];
}

interface CompetenceScoreListProps {
  competences: ProfileCompetence[];
  scaleLevels: ScaleLevel[];
  competenceScores: CompetenceScore[];
  indicatorScores: IndicatorScore[];
  disabled?: boolean;
  emptyHint: string;
  /** HRP-374: per-competence round averages, keyed by competence id. Only
   * the internal sheet passes these — an invited external evaluator must
   * not see what the rest of the panel scored. */
  aggregates?: Record<string, CompetenceAggregate>;
  onCompetenceScore: (competenceId: string, value: number | null) => void;
  onCompetenceComment: (competenceId: string, comment: string) => void;
  onIndicatorScore: (
    competenceId: string,
    indicatorId: string,
    value: number | null,
  ) => void;
}

export function CompetenceScoreList({
  competences,
  scaleLevels,
  competenceScores,
  indicatorScores,
  disabled = false,
  emptyHint,
  aggregates,
  onCompetenceScore,
  onCompetenceComment,
  onIndicatorScore,
}: CompetenceScoreListProps) {
  const t = useTranslations("recruitment");
  return (
    <div className="space-y-2">
      {competences.length === 0 && (
        <p className="text-xs text-muted-foreground">{emptyHint}</p>
      )}
      {competences.map((comp) => {
        const score = competenceScores.find(
          (s) => s.competence_id === comp.id,
        );
        const aggregate = aggregates?.[comp.id];
        return (
          <details
            key={comp.id}
            className={`group rounded-md border p-3 ${
              aggregate?.diverges
                ? "border-amber-400 bg-amber-50 dark:bg-amber-950/30"
                : "bg-muted/20"
            }`}
            data-testid={`assessment-competence-card-${comp.id}`}
          >
            {/* HRP-368: without a disclosure affordance the card reads as a
                static row and evaluators never discover the questions inside.
                The marker is suppressed in favour of an explicit chevron that
                rotates with the native `open` state. */}
            <summary className="flex cursor-pointer list-none items-center justify-between gap-2 text-sm font-medium [&::-webkit-details-marker]:hidden">
              <span className="flex items-center gap-2">
                <ChevronRight
                  aria-hidden="true"
                  className="size-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-90"
                  data-testid={`assessment-competence-chevron-${comp.id}`}
                />
                {comp.name}
                {comp.criticality && (
                  <span
                    className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${criticalityConfig[comp.criticality].className}`}
                    data-testid={`assessment-competence-criticality-${comp.id}`}
                  >
                    {t(criticalityConfig[comp.criticality].labelKey)}
                  </span>
                )}
              </span>
              {aggregate && (
                <span className="flex items-center gap-1 text-[11px] font-normal text-muted-foreground">
                  {aggregate.diverges && (
                    <AlertTriangle
                      role="img"
                      aria-label={t("evalSheetDivergenceAria")}
                      className="size-3.5 text-amber-600"
                      data-testid={`assessment-competence-divergence-icon-${comp.id}`}
                    />
                  )}
                  <span
                    data-testid={`assessment-competence-round-average-${comp.id}`}
                    title={
                      aggregate.diverges
                        ? divergenceTooltip(t, aggregate)
                        : undefined
                    }
                  >
                    {t("evalSheetRoundAverage", {
                      score: aggregate.average.toFixed(1),
                    })}
                  </span>
                </span>
              )}
            </summary>
            <div className="mt-2 space-y-2">
              {comp.indicators.length > 0 && (
                <p className="text-[11px] font-semibold uppercase text-muted-foreground">
                  {t("evalSheetOverall")}
                </p>
              )}
              <div className="flex flex-wrap gap-1">
                {scaleLevels.map((lvl) => (
                  <label
                    key={lvl.value}
                    // HRP-370: `relative` is load-bearing — see the note on
                    // the indicator radio below.
                    className={`relative rounded-md border px-2 py-1 text-xs ${
                      score?.score_value === lvl.value
                        ? "border-emerald-500 bg-emerald-50"
                        : "bg-background"
                    } ${disabled ? "opacity-70" : "cursor-pointer"}`}
                    title={lvl.description ?? lvl.label}
                  >
                    <input
                      type="radio"
                      name={`comp-${comp.id}`}
                      className="sr-only"
                      disabled={disabled}
                      checked={score?.score_value === lvl.value}
                      onChange={() => onCompetenceScore(comp.id, lvl.value)}
                      data-testid={`assessment-competence-overall-radio-${comp.id}-${lvl.value}`}
                    />
                    {lvl.value} — {lvl.label}
                  </label>
                ))}
                <button
                  type="button"
                  disabled={disabled}
                  className={`rounded-md border px-2 py-1 text-xs ${
                    score?.score_value === null
                      ? "border-amber-500 bg-amber-50"
                      : "bg-background"
                  } ${disabled ? "opacity-70" : ""}`}
                  onClick={() => onCompetenceScore(comp.id, null)}
                  data-testid={`assessment-competence-overall-not-assessed-${comp.id}`}
                >
                  {t("evalSheetNotAssessed")}
                </button>
              </div>
              {comp.indicators.length > 0 && (
                <div
                  className="space-y-2 border-l-2 border-muted pl-3"
                  data-testid={`assessment-indicators-${comp.id}`}
                >
                  <p className="text-[11px] font-semibold uppercase text-muted-foreground">
                    {t("evalSheetIndicators")}
                  </p>
                  {comp.indicators.map((ind) => {
                    const iScore = indicatorScores.find(
                      (s) => s.indicator_id === ind.id,
                    );
                    return (
                      <div key={ind.id} className="space-y-1">
                        <p className="text-xs">{ind.text}</p>
                        <div className="flex flex-wrap gap-1">
                          {scaleLevels.map((lvl) => (
                            <label
                              key={lvl.value}
                              // HRP-370: `relative` is load-bearing. The radio
                              // below is `sr-only`, i.e. `position:absolute`.
                              // Without a positioned ancestor its containing
                              // block is the document, so inside the dashboard's
                              // `main.overflow-auto` the label scrolls
                              // internally while the 1x1 input stays behind —
                              // they drift apart by `main.scrollTop`. Clicking
                              // focuses the input and the browser scrolls the
                              // window to reach it, throwing the whole app
                              // shell off-screen (the reported white screen).
                              // The public sheet has no nested scroller, which
                              // is why only the internal one was affected.
                              className={`relative rounded-md border px-2 py-0.5 text-[11px] ${
                                iScore?.score_value === lvl.value
                                  ? "border-emerald-500 bg-emerald-50"
                                  : "bg-background"
                              } ${disabled ? "opacity-70" : "cursor-pointer"}`}
                              title={lvl.description ?? lvl.label}
                            >
                              <input
                                type="radio"
                                name={`ind-${ind.id}`}
                                className="sr-only"
                                disabled={disabled}
                                checked={iScore?.score_value === lvl.value}
                                onChange={() =>
                                  onIndicatorScore(comp.id, ind.id, lvl.value)
                                }
                                data-testid={`assessment-indicator-radio-${comp.id}-${ind.id}-${lvl.value}`}
                              />
                              {lvl.value}
                            </label>
                          ))}
                          <button
                            type="button"
                            disabled={disabled}
                            className={`rounded-md border px-2 py-0.5 text-[11px] ${
                              iScore != null && iScore.score_value === null
                                ? "border-amber-500 bg-amber-50"
                                : "bg-background"
                            } ${disabled ? "opacity-70" : ""}`}
                            onClick={() =>
                              onIndicatorScore(comp.id, ind.id, null)
                            }
                            data-testid={`assessment-indicator-not-assessed-${comp.id}-${ind.id}`}
                          >
                            {t("evalSheetNotAssessed")}
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
              <textarea
                value={score?.comment ?? ""}
                readOnly={disabled}
                onChange={(e) => onCompetenceComment(comp.id, e.target.value)}
                placeholder={t("evalSheetCommentPlaceholder")}
                className="w-full rounded-md border bg-background p-2 text-xs"
                rows={2}
                data-testid={`assessment-competence-comment-${comp.id}`}
              />
            </div>
          </details>
        );
      })}
    </div>
  );
}
