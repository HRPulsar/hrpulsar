"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { AlertTriangle, ExternalLink, Info, Loader2 } from "lucide-react";

import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import type {
  AssessmentMatrixCandidate,
  AssessmentMatrixCell,
  AssessmentMatrixCellDetail,
  AssessmentMatrixCompetence,
  AssessmentMatrixData,
} from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

interface AssessmentsTabProps {
  vacancyId: string;
}

interface SelectedCell {
  candidate: AssessmentMatrixCandidate;
  competence: AssessmentMatrixCompetence;
  cell: AssessmentMatrixCell;
}

// Scores follow the app locale; SSR and client resolve the same
// NEXT_LOCALE cookie, so hydration stays consistent. Cached per locale.
const numFmtCache = new Map<string, Intl.NumberFormat>();
function numFmt(locale: string): Intl.NumberFormat {
  let fmt = numFmtCache.get(locale);
  if (!fmt) {
    fmt = new Intl.NumberFormat(locale, { maximumFractionDigits: 1 });
    numFmtCache.set(locale, fmt);
  }
  return fmt;
}

function formatScore(locale: string, value: number | null): string {
  return value === null ? "—" : numFmt(locale).format(value);
}

function formatPercent(locale: string, value: number | null): string {
  return value === null ? "—" : `${numFmt(locale).format(value)}%`;
}

function cellTone(cell: AssessmentMatrixCell): string {
  if (cell.divergence) return "bg-amber-50 dark:bg-amber-950/30";
  if (cell.manager_score === null && cell.ai_score === null)
    return "bg-muted/20";
  return "";
}

function renderAIScore(
  t: (key: string) => string,
  locale: string,
  cell: AssessmentMatrixCell,
): string {
  if (cell.ai_status === "not_covered") return t("assessmentsTabScoreNa");
  if (cell.ai_status === "missing") return formatScore(locale, cell.ai_score);
  if (cell.ai_status !== "ready" && cell.ai_score === null)
    return t("assessmentsTabScoreFail");
  return formatScore(locale, cell.ai_score);
}

export function AssessmentsTab({ vacancyId }: AssessmentsTabProps) {
  const t = useTranslations("recruitment");
  const locale = useLocale();
  const [data, setData] = useState<AssessmentMatrixData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<SelectedCell | null>(null);
  const [detail, setDetail] = useState<AssessmentMatrixCellDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  // Bumped on every cell click so the previous in-flight fetch can detect
  // it has been superseded and bail instead of overwriting newer detail.
  const detailRequestId = useRef(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .get<AssessmentMatrixData>(
        `/recruitment/vacancies/${vacancyId}/assessment-matrix`,
      )
      .then((res) => {
        if (cancelled) return;
        setData(res);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(
          err instanceof Error
            ? err.message
            : t("assessmentsTabLoadFailed"),
        );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [vacancyId, t]);

  const loadCellDetail = useCallback(
    async (sel: SelectedCell) => {
      const myRequestId = ++detailRequestId.current;
      setDetailLoading(true);
      setDetail(null);
      try {
        const fetched = await api.get<AssessmentMatrixCellDetail>(
          `/recruitment/vacancies/${vacancyId}/assessment-matrix/cells/${sel.candidate.candidate_vacancy_id}/${sel.competence.id}`,
        );
        // Drop the response if the user clicked another cell while we
        // were in flight — otherwise stale detail would overwrite the
        // active selection's footer.
        if (myRequestId !== detailRequestId.current) return;
        setDetail(fetched);
      } catch {
        if (myRequestId !== detailRequestId.current) return;
        setDetail(null);
      } finally {
        if (myRequestId === detailRequestId.current) {
          setDetailLoading(false);
        }
      }
    },
    [vacancyId],
  );

  function handleSelect(sel: SelectedCell) {
    setSelected(sel);
    void loadCellDetail(sel);
  }

  const candidatesPayload = useMemo(
    () => data?.candidates ?? [],
    [data?.candidates],
  );
  const competencesPayload = useMemo(
    () => data?.competences ?? [],
    [data?.competences],
  );

  // Index cells by competence id once per candidate so the render loop
  // does not re-scan every candidate.cells array for every header column.
  const cellByCandidate = useMemo(() => {
    const out = new Map<string, Map<string, AssessmentMatrixCell>>();
    for (const cand of candidatesPayload) {
      const inner = new Map<string, AssessmentMatrixCell>();
      for (const c of cand.cells) inner.set(c.competence_id, c);
      out.set(cand.candidate_vacancy_id, inner);
    }
    return out;
  }, [candidatesPayload]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-10 text-sm text-muted-foreground">
        <Loader2 className="mr-2 size-4 animate-spin" />
        {t("assessmentsTabLoading")}
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
        {error}
      </div>
    );
  }

  if (!data || competencesPayload.length === 0) {
    return (
      <div
        data-testid="assessment-compact-matrix-empty"
        className="rounded-lg border border-dashed p-10 text-center text-sm text-muted-foreground"
      >
        {t("assessmentsTabEmptyNoProfile")}
      </div>
    );
  }

  if (candidatesPayload.length === 0) {
    return (
      <div className="space-y-4">
        <CompactToolbar
          vacancyId={vacancyId}
          divergenceThreshold={data.divergence_threshold}
          totalCompetences={data.total_competences}
          candidateCount={0}
        />
        <div
          data-testid="assessment-compact-matrix-empty"
          className="rounded-lg border border-dashed p-10 text-center text-sm text-muted-foreground"
        >
          {t("assessmentsTabEmptyNoCandidates")}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <CompactToolbar
        vacancyId={vacancyId}
        divergenceThreshold={data.divergence_threshold}
        totalCompetences={data.total_competences}
        candidateCount={candidatesPayload.length}
      />

      <div
        data-testid="assessment-compact-matrix"
        className="overflow-auto rounded-lg border"
        style={{ maxHeight: "60vh" }}
      >
        <table className="w-full border-collapse text-xs">
          <thead className="sticky top-0 z-20 bg-card shadow-sm">
            <tr>
              <th
                className="sticky left-0 z-30 min-w-[14rem] border-b border-r bg-card px-3 py-2 text-left font-medium"
                rowSpan={1}
              >
                {t("assessmentsTabColCandidate")}
              </th>
              <th className="border-b border-r bg-card px-3 py-2 text-left font-medium">
                {t("assessmentsTabColMatch")}
              </th>
              {competencesPayload.map((c) => (
                <th
                  key={c.id}
                  data-testid={`assessment-compact-matrix-col-${c.id}`}
                  className="min-w-[7rem] border-b border-r px-2 py-1.5 text-left font-medium"
                  title={c.group ? `${c.group} · ${c.name}` : c.name}
                >
                  <div className="truncate">{c.name}</div>
                  {c.group && (
                    <div className="text-[10px] font-normal text-muted-foreground">
                      {c.group}
                    </div>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {candidatesPayload.map((cand) => (
              <tr key={cand.candidate_vacancy_id} className="border-t">
                <td
                  className="sticky left-0 z-10 border-r bg-card px-3 py-2 font-medium"
                  data-testid={`assessment-compact-matrix-row-${cand.candidate_vacancy_id}`}
                >
                  <Link
                    href={`/recruitment/candidates/${cand.candidate_id}?vacancyId=${vacancyId}`}
                    className="hover:underline"
                  >
                    {cand.name}
                  </Link>
                  <div className="text-[10px] uppercase text-muted-foreground">
                    {cand.stage_name || cand.status}
                  </div>
                </td>
                <td className="border-r px-3 py-2">
                  <div className="flex flex-wrap items-center gap-1">
                    <Badge
                      variant="outline"
                      className="font-mono"
                      title={t("assessmentsTabManagerScoredTitle", {
                        scored: String(cand.manager_scored_competences),
                        total: String(competencesPayload.length),
                      })}
                    >
                      M&nbsp;{formatPercent(locale, cand.manager_percent)}
                    </Badge>
                    <Badge
                      variant="outline"
                      className="font-mono"
                      title={t("assessmentsTabAiScoredTitle", {
                        scored: String(cand.ai_scored_competences),
                        total: String(competencesPayload.length),
                        skipped: String(cand.ai_not_covered_competences),
                      })}
                    >
                      AI&nbsp;{formatPercent(locale, cand.ai_percent)}
                    </Badge>
                    {cand.divergence_count > 0 && (
                      <Badge
                        data-testid={`assessment-compact-matrix-divergence-${cand.candidate_vacancy_id}`}
                        className="border-amber-400 bg-amber-50 text-amber-900 dark:bg-amber-950/30 dark:text-amber-200"
                      >
                        <AlertTriangle className="mr-1 size-3" />
                        {cand.divergence_count}/{competencesPayload.length}
                      </Badge>
                    )}
                  </div>
                </td>
                {competencesPayload.map((comp) => {
                  const cell =
                    cellByCandidate
                      .get(cand.candidate_vacancy_id)
                      ?.get(comp.id) ?? {
                      competence_id: comp.id,
                      manager_score: null,
                      manager_evaluator_count: 0,
                      ai_score: null,
                      ai_status: "missing" as const,
                      divergence: false,
                    };
                  const isSelected =
                    selected?.candidate.candidate_vacancy_id ===
                      cand.candidate_vacancy_id &&
                    selected?.competence.id === comp.id;
                  return (
                    <td
                      key={`${cand.candidate_vacancy_id}::${comp.id}`}
                      className={cn(
                        "border-r p-0",
                        cellTone(cell),
                        isSelected && "outline outline-2 outline-accent",
                      )}
                    >
                      <button
                        type="button"
                        data-testid={`assessment-compact-matrix-cell-${cand.candidate_vacancy_id}-${comp.id}`}
                        onClick={() =>
                          handleSelect({
                            candidate: cand,
                            competence: comp,
                            cell,
                          })
                        }
                        className="flex w-full flex-col items-center gap-0.5 px-2 py-1.5 text-center font-mono text-xs hover:bg-accent/10"
                      >
                        <span>
                          M:{formatScore(locale, cell.manager_score)}
                          {cell.manager_evaluator_count > 1 && (
                            <span className="ml-0.5 text-[9px] text-muted-foreground">
                              ×{cell.manager_evaluator_count}
                            </span>
                          )}
                        </span>
                        <span className="flex items-center gap-1">
                          AI:{renderAIScore(t, locale, cell)}
                          {cell.divergence && (
                            <AlertTriangle
                              aria-label={t("assessmentsTabDivergenceAria")}
                              className="size-3 text-amber-600"
                            />
                          )}
                        </span>
                      </button>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <CompactFooter
        selected={selected}
        detail={detail}
        loading={detailLoading}
        vacancyId={vacancyId}
      />
    </div>
  );
}

interface CompactToolbarProps {
  vacancyId: string;
  divergenceThreshold: number;
  totalCompetences: number;
  candidateCount: number;
}

function CompactToolbar({
  vacancyId,
  divergenceThreshold,
  totalCompetences,
  candidateCount,
}: CompactToolbarProps) {
  const t = useTranslations("recruitment");
  const locale = useLocale();
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="text-xs text-muted-foreground">
        {t.rich("assessmentsTabToolbarSummary", {
          strong: (chunks) => <strong>{chunks}</strong>,
          mono: (chunks) => <strong className="font-mono">{chunks}</strong>,
          candidates: String(candidateCount),
          competences: String(totalCompetences),
          threshold: numFmt(locale).format(divergenceThreshold),
        })}
      </div>
      <Button
        variant="outline"
        size="sm"
        render={
          <Link
            href={`/recruitment/requisitions/${vacancyId}/canvas`}
            data-testid="assessment-canvas-open-fullscreen-btn"
          >
            <ExternalLink className="mr-1 size-4" />
            {t("assessmentsTabOpenFullscreen")}
          </Link>
        }
      />
    </div>
  );
}

interface CompactFooterProps {
  selected: SelectedCell | null;
  detail: AssessmentMatrixCellDetail | null;
  loading: boolean;
  vacancyId: string;
}

function CompactFooter({
  selected,
  detail,
  loading,
  vacancyId,
}: CompactFooterProps) {
  const t = useTranslations("recruitment");
  const locale = useLocale();
  if (!selected) {
    return (
      <div
        data-testid="assessment-compact-matrix-footer"
        className="flex items-start gap-2 rounded-lg border border-dashed p-3 text-xs text-muted-foreground"
      >
        <Info className="mt-0.5 size-3.5" />
        {t("assessmentsTabFooterHint")}
      </div>
    );
  }
  return (
    <div
      data-testid="assessment-compact-matrix-footer"
      className="rounded-lg border bg-card p-3 text-xs"
    >
      <div className="mb-2 flex flex-wrap items-baseline gap-2">
        <strong className="text-sm">
          <Link
            href={`/recruitment/candidates/${selected.candidate.candidate_id}?vacancyId=${vacancyId}`}
            className="hover:underline"
          >
            {selected.candidate.name}
          </Link>
        </strong>
        <span className="text-muted-foreground">·</span>
        <span>{selected.competence.name}</span>
        {selected.cell.divergence && (
          <Badge className="border-amber-400 bg-amber-50 text-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
            {t("assessmentsTabBadgeDivergence")}
          </Badge>
        )}
      </div>
      {loading && (
        <div className="flex items-center text-muted-foreground">
          <Loader2 className="mr-2 size-3 animate-spin" />
          {t("assessmentsTabLoadingDetails")}
        </div>
      )}
      {detail && !loading && (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <section>
            <div className="mb-1 font-medium">
              {t("assessmentsTabManagerScores")}
            </div>
            {detail.manager_entries.length === 0 ? (
              <div className="text-muted-foreground">
                {t("assessmentsTabNoManagerScore")}
              </div>
            ) : (
              <ul className="space-y-1">
                {detail.manager_entries.map((e, idx) => (
                  <li key={idx} className="flex items-baseline gap-2">
                    <Badge variant="outline" className="font-mono">
                      {formatScore(locale, e.score)}
                    </Badge>
                    <span>{e.evaluator_label}</span>
                    {e.comment && (
                      <span className="truncate text-muted-foreground">
                        “{e.comment}”
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section>
            <div className="mb-1 font-medium">{t("assessmentsTabAiScore")}</div>
            {detail.ai_latest === null ? (
              <div className="text-muted-foreground">
                {t("assessmentsTabNoAiScore")}
              </div>
            ) : (
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <Badge variant="outline" className="font-mono">
                    {detail.ai_latest.status === "not_covered"
                      ? t("assessmentsTabScoreNa")
                      : formatScore(locale, detail.ai_latest.score)}
                  </Badge>
                  <span className="text-muted-foreground">
                    {detail.ai_latest.status}
                  </span>
                </div>
                {detail.ai_latest.reasoning && (
                  <p className="text-muted-foreground">
                    {detail.ai_latest.reasoning}
                  </p>
                )}
                {detail.ai_latest.citations.length > 0 && (
                  <ul className="list-disc space-y-0.5 pl-4 text-muted-foreground">
                    {detail.ai_latest.citations.slice(0, 3).map((c, idx) => (
                      <li key={idx}>{c.quote || c.text || "—"}</li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
