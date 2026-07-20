"use client";

// HRP-359: the competence-scoring form shared between the internal
// Manager assessments section (candidate card) and the public invited
// evaluator page. Both render the same structure — competence accordion
// with an Overall radio row, expandable indicators and a comment — and
// must stay visually identical, so the JSX lives here once.

import { Badge } from "@/components/ui/badge";
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

interface CompetenceScoreListProps {
  competences: ProfileCompetence[];
  scaleLevels: ScaleLevel[];
  competenceScores: CompetenceScore[];
  indicatorScores: IndicatorScore[];
  disabled?: boolean;
  emptyHint: string;
  onCompetenceScore: (
    competenceId: string,
    value: number | null,
    comment?: string,
  ) => void;
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
  onCompetenceScore,
  onIndicatorScore,
}: CompetenceScoreListProps) {
  return (
    <div className="space-y-2">
      {competences.length === 0 && (
        <p className="text-xs text-muted-foreground">{emptyHint}</p>
      )}
      {competences.map((comp) => {
        const score = competenceScores.find(
          (s) => s.competence_id === comp.id,
        );
        return (
          <details
            key={comp.id}
            className="rounded-md border bg-muted/20 p-3"
            data-testid={`assessment-competence-card-${comp.id}`}
          >
            <summary className="flex cursor-pointer items-center justify-between gap-2 text-sm font-medium">
              <span className="flex items-center gap-2">
                {comp.name}
                {comp.criticality && (
                  <span
                    className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${criticalityConfig[comp.criticality].className}`}
                    data-testid={`assessment-competence-criticality-${comp.id}`}
                  >
                    {criticalityConfig[comp.criticality].label}
                  </span>
                )}
              </span>
              {score?.score_source === "computed_from_indicators" && (
                <Badge
                  variant="outline"
                  className="ml-2 text-[10px]"
                  data-testid={`assessment-competence-overall-computed-badge-${comp.id}`}
                >
                  from indicators
                </Badge>
              )}
            </summary>
            <div className="mt-2 space-y-2">
              {comp.indicators.length > 0 && (
                <p className="text-[11px] font-semibold uppercase text-muted-foreground">
                  Overall
                </p>
              )}
              <div className="flex flex-wrap gap-1">
                {scaleLevels.map((lvl) => (
                  <label
                    key={lvl.value}
                    className={`rounded-md border px-2 py-1 text-xs ${
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
                      onChange={() =>
                        onCompetenceScore(
                          comp.id,
                          lvl.value,
                          score?.comment ?? undefined,
                        )
                      }
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
                  Not assessed
                </button>
              </div>
              {comp.indicators.length > 0 && (
                <div
                  className="space-y-2 border-l-2 border-muted pl-3"
                  data-testid={`assessment-indicators-${comp.id}`}
                >
                  <p className="text-[11px] font-semibold uppercase text-muted-foreground">
                    Indicators
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
                              className={`rounded-md border px-2 py-0.5 text-[11px] ${
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
                            Not assessed
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
                onChange={(e) =>
                  onCompetenceScore(
                    comp.id,
                    score?.score_value ?? null,
                    e.target.value,
                  )
                }
                placeholder="Comment (optional)"
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
