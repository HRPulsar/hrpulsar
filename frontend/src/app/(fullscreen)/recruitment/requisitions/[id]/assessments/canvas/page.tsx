"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { AlertTriangle, ArrowLeft, Download, Info, Loader2 } from "lucide-react";

import { api } from "@/lib/api";
import { API_BASE } from "@/lib/api-base";
import { cn } from "@/lib/utils";
import {
  candidateVacancyStatusLabel,
  matrixAiStatusLabel,
  type AssessmentMatrixCandidate,
  type AssessmentMatrixCell,
  type AssessmentMatrixCellDetail,
  type AssessmentMatrixCompetence,
  type AssessmentMatrixData,
  type Vacancy,
} from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { formatDateTime } from "@/lib/date-format";

type CanvasView = "manager_ai" | "manager" | "ai" | "aggregated";
type CanvasScale = "points" | "percent";

interface SelectedCell {
  candidate: AssessmentMatrixCandidate;
  competence: AssessmentMatrixCompetence;
  cell: AssessmentMatrixCell;
}

const numFmtCache = new Map<string, Intl.NumberFormat>();
function numFmt(locale: string): Intl.NumberFormat {
  let fmt = numFmtCache.get(locale);
  if (!fmt) {
    fmt = new Intl.NumberFormat(locale, { maximumFractionDigits: 1 });
    numFmtCache.set(locale, fmt);
  }
  return fmt;
}

const EMPTY_CELL: AssessmentMatrixCell = {
  competence_id: "",
  manager_score: null,
  manager_evaluator_count: 0,
  ai_score: null,
  ai_status: "missing",
  divergence: false,
};

export default function AssessmentCanvasPage() {
  const { id } = useParams<{ id: string }>();
  // HRP-507: the Divergence badge on the vacancy Candidates block links
  // here with ?filter=divergences, so the recruiter lands on exactly the
  // cells the badge counted instead of the full grid.
  const searchParams = useSearchParams();
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const locale = useLocale();

  const [vacancy, setVacancy] = useState<Vacancy | null>(null);
  const [data, setData] = useState<AssessmentMatrixData | null>(null);
  const [loading, setLoading] = useState(true);
  const [xlsxLoading, setXlsxLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [view, setView] = useState<CanvasView>("manager_ai");
  const [round, setRound] = useState("latest");
  const [scale, setScale] = useState<CanvasScale>("points");
  const [hidden, setHidden] = useState<Set<string>>(() => new Set());
  const [onlyDivergences, setOnlyDivergences] = useState(
    () => searchParams.get("filter") === "divergences",
  );
  const [hideUnscored, setHideUnscored] = useState(false);

  const [selected, setSelected] = useState<SelectedCell | null>(null);
  const [detail, setDetail] = useState<AssessmentMatrixCellDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const detailRequestId = useRef(0);

  useEffect(() => {
    api
      .get<Vacancy>(`/recruitment/vacancies/${id}`)
      .then(setVacancy)
      .catch(() => {});
  }, [id]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    // The footer renders a snapshot of the clicked cell. A new round (or
    // vacancy) is a different set of scores, so keeping the old snapshot
    // would show last round's numbers under the new grid. Bump the
    // detail request id too, so an in-flight detail fetch cannot land
    // on top of the cleared selection.
    detailRequestId.current += 1;
    setSelected(null);
    setDetail(null);
    setDetailLoading(false);
    api
      .get<AssessmentMatrixData>(
        `/recruitment/vacancies/${id}/assessment-matrix?round=${round}`,
      )
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(
          err instanceof Error ? err.message : t("assessmentsTabLoadFailed"),
        );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [id, round, t]);

  const allCandidates = useMemo(() => data?.candidates ?? [], [data]);
  const allCompetences = useMemo(() => data?.competences ?? [], [data]);
  const maxScore = data?.max_score ?? 5;

  const cellIndex = useMemo(() => {
    const out = new Map<string, Map<string, AssessmentMatrixCell>>();
    for (const cand of allCandidates) {
      const inner = new Map<string, AssessmentMatrixCell>();
      for (const c of cand.cells) inner.set(c.competence_id, c);
      out.set(cand.candidate_vacancy_id, inner);
    }
    return out;
  }, [allCandidates]);

  function cellFor(
    cand: AssessmentMatrixCandidate,
    comp: AssessmentMatrixCompetence,
  ): AssessmentMatrixCell {
    return (
      cellIndex.get(cand.candidate_vacancy_id)?.get(comp.id) ?? {
        ...EMPTY_CELL,
        competence_id: comp.id,
      }
    );
  }

  // Row filters: visibility checkboxes first, then "hide candidates with
  // no scores", then "show only divergences".
  const visibleCandidates = useMemo(() => {
    return allCandidates.filter((cand) => {
      if (hidden.has(cand.candidate_vacancy_id)) return false;
      if (hideUnscored) {
        const scored = cand.cells.some(
          (c) => c.manager_score !== null || c.ai_score !== null,
        );
        if (!scored) return false;
      }
      if (onlyDivergences && cand.divergence_count === 0) return false;
      return true;
    });
  }, [allCandidates, hidden, hideUnscored, onlyDivergences]);

  // Column filter: with "only divergences" on, keep competences where at
  // least one *visible* candidate diverges — otherwise the grid keeps
  // columns that are empty for everyone left on screen.
  const visibleCompetences = useMemo(() => {
    if (!onlyDivergences) return allCompetences;
    return allCompetences.filter((comp) =>
      visibleCandidates.some((cand) => cellFor(cand, comp).divergence),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allCompetences, visibleCandidates, onlyDivergences, cellIndex]);

  const loadCellDetail = useCallback(
    async (sel: SelectedCell) => {
      const myRequestId = ++detailRequestId.current;
      setDetailLoading(true);
      setDetail(null);
      try {
        const fetched = await api.get<AssessmentMatrixCellDetail>(
          `/recruitment/vacancies/${id}/assessment-matrix/cells/${sel.candidate.candidate_vacancy_id}/${sel.competence.id}`,
        );
        if (myRequestId !== detailRequestId.current) return;
        setDetail(fetched);
      } catch {
        if (myRequestId !== detailRequestId.current) return;
        setDetail(null);
      } finally {
        if (myRequestId === detailRequestId.current) setDetailLoading(false);
      }
    },
    [id],
  );

  function toggleCandidate(cvId: string) {
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(cvId)) next.delete(cvId);
      else next.add(cvId);
      return next;
    });
  }

  function formatValue(value: number | null): string {
    if (value === null) return "—";
    if (scale === "percent" && maxScore > 0) {
      return `${numFmt(locale).format((value / maxScore) * 100)}%`;
    }
    return numFmt(locale).format(value);
  }

  function aiText(cell: AssessmentMatrixCell): string {
    if (cell.ai_status === "not_covered") return t("assessmentsTabScoreNa");
    return formatValue(cell.ai_score);
  }

  // The M:/AI: prefixes are machine-ish labels, not prose — building them
  // here keeps the JSX free of raw string literals (jsx-no-literals).
  function managerCellText(cell: AssessmentMatrixCell): string {
    return `M:${formatValue(cell.manager_score)}`;
  }

  function aiCellText(cell: AssessmentMatrixCell): string {
    return `AI:${aiText(cell)}`;
  }

  function evaluatorMeta(row: AssessmentMatrixCellDetail | null): string | null {
    const entry = row?.manager_entries?.[0];
    if (!entry) return null;
    const when = entry.updated_at ? `, ${formatDateTime(entry.updated_at)}` : "";
    return `(${entry.evaluator_label}${when})`;
  }

  function aiMeta(row: AssessmentMatrixCellDetail | null): string | null {
    if (!row?.ai_latest) return null;
    // ai_latest.status is a machine token ("ready" / "not_covered" /
    // "missing"); render its wording, and nothing at all when the
    // backend passed through a status we have no label for.
    const label = matrixAiStatusLabel(t, row.ai_latest.status);
    return label ? `(${label})` : null;
  }

  /** "Aggregated" collapses Manager and AI into their mean. */
  function aggregatedValue(cell: AssessmentMatrixCell): number | null {
    const parts = [cell.manager_score, cell.ai_score].filter(
      (v): v is number => v !== null,
    );
    if (parts.length === 0) return null;
    return parts.reduce((a, b) => a + b, 0) / parts.length;
  }

  /** CSV injection guard: a cell opening with =, +, - or @ is executed as
   *  a formula by Excel / Sheets. Prefixing with an apostrophe keeps the
   *  text visible and inert. Candidate and competence names are free
   *  text, so the whole row goes through this. */
  function csvSafe(value: string): string {
    return /^[=+\-@]/.test(value) ? `'${value}` : value;
  }

  function handleExportCsv() {
    const header = [
      t("canvasColCandidate"),
      t("canvasColSource"),
      ...visibleCompetences.map((c) => c.name),
    ];
    const lines = [header];
    // Source labels mirror the View selector — same wording as the
    // on-screen option the export was taken from.
    const managerLabel = t("canvasViewManagerOnly");
    const aiLabel = t("canvasViewAiOnly");
    for (const cand of visibleCandidates) {
      const rowsForCandidate: [string, (c: AssessmentMatrixCell) => string][] =
        view === "aggregated"
          ? [
              [
                t("canvasViewAggregated"),
                (c) => formatValue(aggregatedValue(c)),
              ],
            ]
          : view === "manager"
            ? [[managerLabel, (c) => formatValue(c.manager_score)]]
            : view === "ai"
              ? [[aiLabel, (c) => aiText(c)]]
              : [
                  [managerLabel, (c) => formatValue(c.manager_score)],
                  [aiLabel, (c) => aiText(c)],
                ];
      for (const [label, render] of rowsForCandidate) {
        lines.push([
          cand.name,
          label,
          ...visibleCompetences.map((comp) => render(cellFor(cand, comp))),
        ]);
      }
    }
    const csv = lines
      .map((row) =>
        row
          .map((v) => `"${csvSafe(String(v)).replace(/"/g, '""')}"`)
          .join(","),
      )
      .join("\n");
    // Prepend a BOM so Excel opens the UTF-8 file with the right encoding.
    const blob = new Blob([`﻿${csv}`], {
      type: "text/csv;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `canvas-${id}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  /** XLSX comes from the API, which is bearer-authenticated — a plain
   *  <a href> would send no Authorization header and 401. Fetch it,
   *  then hand the blob to a synthetic download link. */
  async function handleExportXlsx() {
    setXlsxLoading(true);
    try {
      const token = localStorage.getItem("access_token");
      const res = await fetch(
        `${API_BASE}/recruitment/vacancies/${id}/assessment-matrix/export.xlsx?round=${round}`,
        { headers: token ? { Authorization: `Bearer ${token}` } : {} },
      );
      if (!res.ok) throw new Error(String(res.status));
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `canvas-${id}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setError(t("canvasExportXlsxFailed"));
    } finally {
      setXlsxLoading(false);
    }
  }

  const totalsLabel = (cand: AssessmentMatrixCandidate) => {
    const scored = cand.manager_scored_competences;
    const aiScored = cand.ai_scored_competences;
    return { scored, aiScored };
  };

  // No early return on `loading`: every Round / vacancy switch flips it,
  // and unmounting the header would blow away the focus of the select
  // the user just used. The spinner lives in the grid area instead.
  return (
    <div
      className="flex h-full flex-col"
      data-testid="recruitment-canvas-fullscreen"
    >
      {/* ── Top bar ─────────────────────────────────────────────── */}
      <header className="border-b px-4 py-2">
        <div className="flex flex-wrap items-center gap-3">
          <Button
            variant="ghost"
            size="sm"
            render={
              <Link
                href={`/recruitment/requisitions/${id}`}
                data-testid="canvas-back-link"
              >
                <ArrowLeft className="mr-1 size-4" />
                {tc("back")}
              </Link>
            }
          />
          <span className="text-sm font-semibold">
            {t("canvasHeading", { vacancy: vacancy?.title ?? "" })}
          </span>
          <span className="text-xs text-muted-foreground">
            {t("canvasCounts", {
              candidates: String(allCandidates.length),
              competences: String(allCompetences.length),
            })}
          </span>
        </div>

        <div className="mt-2 flex flex-wrap items-center gap-3 text-xs">
          <label className="flex items-center gap-1">
            <span className="text-muted-foreground">{t("canvasViewLabel")}</span>
            <select
              className="h-7 rounded-md border border-input bg-transparent px-2"
              data-testid="canvas-view-select"
              value={view}
              onChange={(e) => {
                // The footer describes a cell as seen in the previous
                // view; drop the selection rather than keep explaining a
                // Manager/AI split the grid no longer shows.
                setSelected(null);
                setDetail(null);
                setView(e.target.value as CanvasView);
              }}
            >
              <option value="manager_ai">{t("canvasViewManagerAi")}</option>
              <option value="manager">{t("canvasViewManagerOnly")}</option>
              <option value="ai">{t("canvasViewAiOnly")}</option>
              <option value="aggregated">{t("canvasViewAggregated")}</option>
            </select>
          </label>

          <label className="flex items-center gap-1">
            <span className="text-muted-foreground">
              {t("canvasRoundLabel")}
            </span>
            <select
              className="h-7 rounded-md border border-input bg-transparent px-2"
              data-testid="canvas-round-select"
              value={round}
              onChange={(e) => setRound(e.target.value)}
            >
              <option value="latest">{t("canvasRoundLatest")}</option>
              {Array.from({ length: data?.round_count ?? 0 }, (_, i) => (
                <option key={i + 1} value={String(i + 1)}>
                  {t("canvasRoundNumber", { number: String(i + 1) })}
                </option>
              ))}
              <option value="all">{t("canvasRoundAll")}</option>
            </select>
          </label>

          <label className="flex items-center gap-1">
            <span className="text-muted-foreground">
              {t("canvasScaleLabel")}
            </span>
            <select
              className="h-7 rounded-md border border-input bg-transparent px-2"
              data-testid="canvas-scale-select"
              value={scale}
              onChange={(e) => setScale(e.target.value as CanvasScale)}
            >
              <option value="points">
                {data?.scale_name ??
                  t("canvasScalePoints", { max: String(maxScore) })}
              </option>
              <option value="percent">{t("canvasScalePercent")}</option>
            </select>
          </label>

          <span className="ml-auto flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={handleExportCsv}
              data-testid="canvas-export-csv"
            >
              <Download className="mr-1 size-3.5" />
              {t("canvasExportCsv")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={handleExportXlsx}
              disabled={xlsxLoading}
              data-testid="canvas-export-xlsx"
            >
              {xlsxLoading ? (
                <Loader2 className="mr-1 size-3.5 animate-spin" />
              ) : (
                <Download className="mr-1 size-3.5" />
              )}
              {t("canvasExportXlsx")}
            </Button>
          </span>
        </div>

        <div className="mt-2 flex flex-wrap items-center gap-4 text-xs">
          <label className="flex items-center gap-2">
            <Checkbox
              checked={onlyDivergences}
              onCheckedChange={() => setOnlyDivergences((v) => !v)}
              data-testid="canvas-filter-divergences"
            />
            {t("canvasFilterDivergences")}
          </label>
          <label className="flex items-center gap-2">
            <Checkbox
              checked={hideUnscored}
              onCheckedChange={() => setHideUnscored((v) => !v)}
              data-testid="canvas-filter-unscored"
            />
            {t("canvasFilterNoScores")}
          </label>
        </div>
      </header>

      {error && (
        <div className="border-b bg-destructive/5 p-3 text-sm text-destructive">
          {error}
        </div>
      )}

      {/* ── Body: candidate panel + matrix ──────────────────────── */}
      <div className="flex min-h-0 flex-1">
        <aside
          className="w-56 shrink-0 overflow-y-auto border-r p-3"
          data-testid="canvas-candidate-panel"
        >
          <p className="mb-2 text-xs font-medium uppercase text-muted-foreground">
            {t("canvasCandidatesPanel")}
          </p>
          {allCandidates.length === 0 && (
            <p className="text-xs text-muted-foreground">
              {t("assessmentsTabEmptyNoCandidates")}
            </p>
          )}
          <ul className="space-y-2">
            {allCandidates.map((cand) => (
              <li
                key={cand.candidate_vacancy_id}
                className="flex items-start gap-2 text-xs"
              >
                <Checkbox
                  checked={!hidden.has(cand.candidate_vacancy_id)}
                  onCheckedChange={() =>
                    toggleCandidate(cand.candidate_vacancy_id)
                  }
                  data-testid={`canvas-candidate-toggle-${cand.candidate_vacancy_id}`}
                />
                <span className="min-w-0">
                  <span className="block truncate font-medium">
                    {cand.name}
                  </span>
                  <span className="block truncate text-muted-foreground">
                    {cand.stage_name ||
                      candidateVacancyStatusLabel(t, cand.status)}
                  </span>
                  <span className="block truncate text-muted-foreground">
                    {round === "latest"
                      ? t("canvasRoundLatest")
                      : round === "all"
                        ? t("canvasRoundAll")
                        : t("canvasRoundNumber", { number: round })}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        </aside>

        <main className="min-w-0 flex-1 overflow-auto p-3">
          {loading ? (
            <p
              className="flex items-center justify-center p-10 text-sm text-muted-foreground"
              data-testid="canvas-matrix-loading"
            >
              <Loader2 className="mr-2 size-4 animate-spin" />
              {t("assessmentsTabLoading")}
            </p>
          ) : visibleCompetences.length === 0 ||
            visibleCandidates.length === 0 ? (
            <p
              className="rounded-lg border border-dashed p-10 text-center text-sm text-muted-foreground"
              data-testid="canvas-matrix-empty"
            >
              {t("canvasNothingToShow")}
            </p>
          ) : (
            <table
              className="border-collapse text-xs"
              data-testid="canvas-matrix"
            >
              <thead>
                <tr>
                  <th className="border-b border-r px-2 py-1.5 text-left font-medium">
                    {t("canvasColCandidate")}
                  </th>
                  {visibleCompetences.map((comp) => (
                    <th
                      key={comp.id}
                      className="min-w-[6.5rem] border-b border-r px-2 py-1.5 text-left font-medium"
                      title={comp.group ? `${comp.group} · ${comp.name}` : comp.name}
                    >
                      <span className="block max-w-[8rem] truncate">
                        {comp.name}
                      </span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {visibleCandidates.map((cand) => (
                  <tr key={cand.candidate_vacancy_id} className="border-t">
                    <td className="border-r px-2 py-1.5 font-medium">
                      {cand.name}
                    </td>
                    {visibleCompetences.map((comp) => {
                      const cell = cellFor(cand, comp);
                      const isSelected =
                        selected?.candidate.candidate_vacancy_id ===
                          cand.candidate_vacancy_id &&
                        selected?.competence.id === comp.id;
                      const empty =
                        cell.manager_score === null && cell.ai_score === null;
                      return (
                        <td
                          key={comp.id}
                          className={cn(
                            "border-r p-0",
                            cell.divergence && "bg-amber-50 dark:bg-amber-950/30",
                            empty && "bg-muted/20",
                            isSelected && "outline outline-2 outline-accent",
                          )}
                        >
                          <button
                            type="button"
                            data-testid={`canvas-cell-${cand.candidate_vacancy_id}-${comp.id}`}
                            onClick={() => {
                              const sel = {
                                candidate: cand,
                                competence: comp,
                                cell,
                              };
                              setSelected(sel);
                              void loadCellDetail(sel);
                            }}
                            className="flex w-full flex-col items-center gap-0.5 px-2 py-1 text-center font-mono hover:bg-accent/10"
                          >
                            {view === "aggregated" ? (
                              <span>{formatValue(aggregatedValue(cell))}</span>
                            ) : (
                              <>
                                {view !== "ai" && (
                                  <span>
                                    {empty && view === "manager"
                                      ? "●"
                                      : managerCellText(cell)}
                                  </span>
                                )}
                                {view !== "manager" && (
                                  <span className="flex items-center gap-1">
                                    {aiCellText(cell)}
                                    {cell.divergence && (
                                      <AlertTriangle
                                        aria-label={t(
                                          "assessmentsTabDivergenceAria",
                                        )}
                                        className="size-3 text-amber-600"
                                      />
                                    )}
                                  </span>
                                )}
                              </>
                            )}
                          </button>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {/* ── Totals ──────────────────────────────────────────── */}
          {!loading && visibleCandidates.length > 0 && (
            <section className="mt-4" data-testid="canvas-totals">
              <p className="mb-1 text-xs font-medium uppercase text-muted-foreground">
                {t("canvasTotals")}
              </p>
              <ul className="space-y-0.5 text-xs">
                {visibleCandidates.map((cand) => {
                  const { scored, aiScored } = totalsLabel(cand);
                  return (
                    <li
                      key={cand.candidate_vacancy_id}
                      data-testid={`canvas-total-${cand.candidate_vacancy_id}`}
                      className="font-mono"
                    >
                      {t("canvasTotalRow", {
                        name: cand.name,
                        manager:
                          cand.manager_percent === null
                            ? "—"
                            : `${numFmt(locale).format(cand.manager_percent)}% (${scored}/${allCompetences.length})`,
                        ai:
                          cand.ai_percent === null
                            ? "—"
                            : `${numFmt(locale).format(cand.ai_percent)}% (${aiScored}/${allCompetences.length})`,
                      })}
                      {cand.divergence_count > 0 && (
                        <Badge className="ml-2 border-amber-400 bg-amber-50 text-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
                          <AlertTriangle className="mr-1 size-3" />
                          {cand.divergence_count}
                        </Badge>
                      )}
                    </li>
                  );
                })}
              </ul>
            </section>
          )}
        </main>
      </div>

      {/* ── Footer: selected cell ───────────────────────────────── */}
      <footer
        className="border-t bg-card px-4 py-2 text-xs"
        data-testid="canvas-footer"
      >
        {!selected ? (
          <span className="flex items-center gap-2 text-muted-foreground">
            <Info className="size-3.5" />
            {t("assessmentsTabFooterHint")}
          </span>
        ) : detailLoading ? (
          <span className="flex items-center text-muted-foreground">
            <Loader2 className="mr-2 size-3 animate-spin" />
            {t("assessmentsTabLoadingDetails")}
          </span>
        ) : (
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <strong>{t("canvasCellSelected")}</strong>
            <span>
              {selected.candidate.name} / {selected.competence.name}
            </span>
            <span className="text-muted-foreground">·</span>
            <span className="font-mono">
              {managerCellText(selected.cell)}
            </span>
            {evaluatorMeta(detail) && (
              <span className="text-muted-foreground">
                {evaluatorMeta(detail)}
              </span>
            )}
            <span className="text-muted-foreground">·</span>
            <span className="font-mono">{aiCellText(selected.cell)}</span>
            {aiMeta(detail) && (
              <span className="text-muted-foreground">{aiMeta(detail)}</span>
            )}
          </span>
        )}
      </footer>
    </div>
  );
}
