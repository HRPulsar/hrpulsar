"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { CompetenceItem } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { History, Loader2, Save, Undo2 } from "lucide-react";
import { toast } from "sonner";
import { ScoreCell } from "./score-cell";
import { cellKey, useCanvasState } from "./use-canvas-state";
import { CanvasVersionsSheet } from "./canvas-versions-sheet";
import { CanvasConflictModal } from "./canvas-conflict-modal";

const VIRTUALIZE_THRESHOLD = 50;
const ESTIMATED_ROW_PX = 36;

export interface ScaleConfig {
  min: number;
  max: number;
  step: number;
}

const DEFAULT_SCALE: ScaleConfig = { min: 0, max: 5, step: 0.5 };

interface CanvasGridProps {
  vacancyId: string;
  /** Compact mode pins to one candidate-vacancy. */
  candidateVacancyId?: string;
  inviteToken?: string;
  mode: "compact" | "fullscreen";
  scale?: ScaleConfig;
}

interface CompetenceWithId extends CompetenceItem {
  id?: string;
}

function competenceId(c: CompetenceWithId): string {
  return c.id || c.name;
}

function SpacerRow({ height, cols }: { height: number; cols: number }) {
  if (height <= 0) return null;
  return (
    <tr aria-hidden style={{ height }}>
      <td colSpan={cols} style={{ height, padding: 0, border: 0 }} />
    </tr>
  );
}

/** Minimal shape of the `next-intl` translator the row renderer needs. */
type Translate = (key: string, values?: Record<string, string>) => string;

interface CanvasCandidateRow {
  candidate_vacancy_id: string;
  name: string;
  status: string;
  human_scores: Record<string, Record<string, number | null>>;
  ai_scores: Record<string, number | null>;
}

function renderRow(
  cand: CanvasCandidateRow,
  rowIdx: number,
  competences: CompetenceWithId[],
  evaluatorList: { id: string; name: string }[],
  selfEvaluatorId: string | null,
  inviteMode: boolean,
  dirtyCells: Set<string>,
  pendingCells: Set<string>,
  scale: ScaleConfig,
  setScore: (
    cvId: string,
    competenceId: string,
    evaluatorId: string,
    score: number | null,
  ) => void,
  t: Translate,
) {
  let colIdx = 0;
  return (
    <tr key={cand.candidate_vacancy_id} className="border-t">
      <td className="sticky left-0 z-10 border-r bg-card px-3 py-2 font-medium">
        {cand.name}
        <span className="ml-2 text-[10px] uppercase text-muted-foreground">
          {cand.status}
        </span>
      </td>
      {competences.map((c) =>
        evaluatorList.length > 0 ? (
          evaluatorList.map((ev) => {
            const cid = competenceId(c);
            const score = cand.human_scores?.[cid]?.[ev.id] ?? null;
            const aiScore = cand.ai_scores?.[cid] ?? null;
            const key = cellKey({
              candidateVacancyId: cand.candidate_vacancy_id,
              competenceId: cid,
              evaluatorId: ev.id,
            });
            const editable = inviteMode || ev.id === selfEvaluatorId;
            const dataRow = rowIdx;
            const dataCol = colIdx++;
            return (
              <td
                key={`${cand.candidate_vacancy_id}::${cid}::${ev.id}`}
                className="border-r p-0"
              >
                <ScoreCell
                  value={score}
                  aiValue={aiScore}
                  editable={editable}
                  dirty={dirtyCells.has(key)}
                  pending={pendingCells.has(key)}
                  min={scale.min}
                  max={scale.max}
                  step={scale.step}
                  dataRow={dataRow}
                  dataCol={dataCol}
                  onCommit={(next) =>
                    setScore(cand.candidate_vacancy_id, cid, ev.id, next)
                  }
                  data-testid={`canvas-cell-${cand.candidate_vacancy_id}-${cid}-${ev.id}`}
                  ariaLabel={t("canvasCellAriaLabel", {
                    candidate: cand.name,
                    competence: c.name,
                    evaluator: ev.name,
                  })}
                />
              </td>
            );
          })
        ) : (
          <td
            key={`${cand.candidate_vacancy_id}::${competenceId(c)}::empty`}
            className="border-r px-2 py-2 text-center text-muted-foreground"
          >
            —
          </td>
        ),
      )}
    </tr>
  );
}

export function CanvasGrid({
  vacancyId,
  candidateVacancyId,
  inviteToken,
  mode,
  scale = DEFAULT_SCALE,
}: CanvasGridProps) {
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const tableRef = useRef<HTMLTableElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const [versionsOpen, setVersionsOpen] = useState(false);
  const {
    data,
    loading,
    error,
    pendingCells,
    dirtyCells,
    selfEvaluatorId,
    setScore,
    flush,
    reload,
    undo,
    canUndo,
    conflicts,
    resolveConflict,
  } = useCanvasState({ vacancyId, candidateVacancyId, inviteToken });

  // Cell-aware arrow navigation: ↑/↓/←/→ move focus between cells.
  // We rely on data-row/data-col attributes set on each cell wrapper below.
  const handleArrowNav = useCallback(
    (e: React.KeyboardEvent<HTMLTableElement>) => {
      const target = e.target as HTMLElement;
      const rowAttr = target.getAttribute("data-row");
      const colAttr = target.getAttribute("data-col");
      if (rowAttr === null || colAttr === null) return;
      const dx = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
      const dy = e.key === "ArrowDown" ? 1 : e.key === "ArrowUp" ? -1 : 0;
      if (dx === 0 && dy === 0) return;
      e.preventDefault();
      const nextRow = Number(rowAttr) + dy;
      const nextCol = Number(colAttr) + dx;
      const next = tableRef.current?.querySelector<HTMLElement>(
        `[data-row="${nextRow}"][data-col="${nextCol}"]`,
      );
      next?.focus();
    },
    [],
  );

  const competences = useMemo<CompetenceWithId[]>(
    () => (data?.competences as CompetenceWithId[]) ?? [],
    [data?.competences],
  );

  const evaluatorList = useMemo(() => {
    const list = data?.evaluators ?? [];
    if (selfEvaluatorId && !list.find((e) => e.id === selfEvaluatorId)) {
      return [{ id: selfEvaluatorId, name: t("canvasEvaluatorYou") }, ...list];
    }
    return list;
  }, [data?.evaluators, selfEvaluatorId, t]);

  const candidates = data?.candidates ?? [];

  // Linear column index → (competenceId, evaluatorId) lookup. Mirrors the
  // render-side counter used to assign data-col attributes.
  const colMeta = useMemo(() => {
    const meta: { competenceId: string; evaluatorId: string }[] = [];
    for (const c of competences) {
      const cid = competenceId(c);
      if (evaluatorList.length === 0) continue;
      for (const ev of evaluatorList) {
        meta.push({ competenceId: cid, evaluatorId: ev.id });
      }
    }
    return meta;
  }, [competences, evaluatorList]);

  function parseScore(raw: string): number | null {
    const trimmed = raw.trim();
    if (trimmed === "") return null;
    const normalized = trimmed.replace(",", ".");
    const num = Number(normalized);
    if (!Number.isFinite(num)) return null;
    if (num < scale.min || num > scale.max) return null;
    return num;
  }

  // TSV paste — parse clipboard rectangle, write into cells starting at
  // the focused cell. Excel / Google Sheets format: tab-separated columns,
  // newline-separated rows. Cells the user isn't allowed to edit are
  // silently skipped so a paste from a wide rectangle still drops cleanly
  // onto editable columns only.
  const handlePaste = useCallback(
    (e: React.ClipboardEvent<HTMLTableElement>) => {
      const target = e.target as HTMLElement;
      const startRow = Number(target.getAttribute("data-row"));
      const startCol = Number(target.getAttribute("data-col"));
      if (Number.isNaN(startRow) || Number.isNaN(startCol)) return;

      const text = e.clipboardData.getData("text/plain");
      if (!text) return;
      const rows = text.replace(/\r/g, "").split("\n").map((r) => r.split("\t"));
      // Trim trailing blank line — Excel always appends one.
      while (rows.length > 0 && rows[rows.length - 1].every((c) => c === "")) {
        rows.pop();
      }
      if (rows.length === 0) return;

      e.preventDefault();
      let written = 0;
      let skipped = 0;
      for (let r = 0; r < rows.length; r++) {
        const candIdx = startRow + r;
        const cand = candidates[candIdx];
        if (!cand) {
          skipped += rows[r].filter((v) => v !== "").length;
          continue;
        }
        for (let c = 0; c < rows[r].length; c++) {
          const meta = colMeta[startCol + c];
          if (!meta) {
            if (rows[r][c] !== "") skipped += 1;
            continue;
          }
          const editable =
            Boolean(inviteToken) || meta.evaluatorId === selfEvaluatorId;
          if (!editable) {
            if (rows[r][c] !== "") skipped += 1;
            continue;
          }
          const score = parseScore(rows[r][c]);
          // Skip empty cells silently; otherwise treat invalid number
          // as a skip with a counter so the toast surfaces it.
          if (rows[r][c].trim() === "") continue;
          if (score === null && rows[r][c].trim() !== "") {
            skipped += 1;
            continue;
          }
          setScore(cand.candidate_vacancy_id, meta.competenceId, meta.evaluatorId, score);
          written += 1;
        }
      }
      if (written > 0) {
        toast.success(
          skipped > 0
            ? t("canvasPasteToastSkipped", {
                written: String(written),
                skipped: String(skipped),
              })
            : t("canvasPasteToast", { written: String(written) }),
        );
      } else if (skipped > 0) {
        toast.error(
          t("canvasPasteToastNone", {
            skipped: String(skipped),
            min: String(scale.min),
            max: String(scale.max),
          }),
        );
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [candidates, colMeta, inviteToken, selfEvaluatorId, scale.min, scale.max, setScore, t],
  );

  // Row-level virtualization for fullscreen mode with many candidates.
  // Below threshold we render the regular `<tbody>` so layout stays
  // identical (printable, copy-friendly, predictable column widths).
  const virtualize =
    mode === "fullscreen" && candidates.length >= VIRTUALIZE_THRESHOLD;
  const rowVirtualizer = useVirtualizer({
    count: candidates.length,
    getScrollElement: () => scrollContainerRef.current,
    estimateSize: () => ESTIMATED_ROW_PX,
    overscan: 8,
    enabled: virtualize,
  });

  if (loading) {
    return (
      <div className="flex items-center justify-center py-10 text-sm text-muted-foreground">
        <Loader2 className="mr-2 size-4 animate-spin" />
        {t("canvasLoadingState")}
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

  if (competences.length === 0) {
    return (
      <div className="rounded-lg border border-dashed p-10 text-center text-sm text-muted-foreground">
        {t("canvasEmptyNoProfile")}
      </div>
    );
  }

  if (candidates.length === 0) {
    return (
      <div className="rounded-lg border border-dashed p-10 text-center text-sm text-muted-foreground">
        {t("canvasEmptyNoCandidates")}
      </div>
    );
  }

  return (
    <div data-testid={`canvas-${mode}`} className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <div className="text-xs text-muted-foreground">
          {dirtyCells.size > 0 ? (
            <span className="text-[var(--rec-data-partial)]">
              {t("canvasUnsavedCount", { count: String(dirtyCells.size) })}
            </span>
          ) : pendingCells.size > 0 ? (
            <span className="flex items-center gap-1">
              <Loader2 className="size-3 animate-spin" /> {t("canvasSaving")}
            </span>
          ) : (
            <span>{t("canvasAllSaved")}</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={undo}
            disabled={!canUndo}
            data-testid="canvas-btn-undo"
          >
            <Undo2 className="mr-1 size-3.5" />
            {t("canvasUndo")}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setVersionsOpen(true)}
            data-testid="canvas-btn-versions"
          >
            <History className="mr-1 size-3.5" />
            {t("canvasVersionsButton")}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void flush()}
            disabled={dirtyCells.size === 0}
            data-testid="canvas-btn-save-now"
          >
            <Save className="mr-1 size-3.5" />
            {t("canvasSaveNow")}
          </Button>
        </div>
      </div>
      <CanvasVersionsSheet
        open={versionsOpen}
        onOpenChange={setVersionsOpen}
        vacancyId={vacancyId}
        candidateVacancyId={candidateVacancyId}
        onReverted={() => {
          void reload();
        }}
      />
      <CanvasConflictModal
        conflicts={conflicts}
        onResolve={resolveConflict}
      />

      <div
        ref={scrollContainerRef}
        className="overflow-auto rounded-lg border"
        style={{ maxHeight: mode === "fullscreen" ? "calc(100vh - 12rem)" : "60vh" }}
      >
        <table
          ref={tableRef}
          onKeyDown={handleArrowNav}
          onPaste={handlePaste}
          className="w-full border-collapse text-xs"
        >
          <thead className="sticky top-0 z-10 bg-card shadow-sm">
            <tr>
              <th
                className={cn(
                  "sticky left-0 z-20 min-w-[14rem] border-b border-r bg-card px-3 py-2 text-left font-medium",
                )}
                rowSpan={2}
              >
                {mode === "fullscreen"
                  ? tc("candidate")
                  : t("canvasColEvaluator")}
              </th>
              {competences.map((c) => (
                <th
                  key={competenceId(c)}
                  colSpan={evaluatorList.length || 1}
                  className="border-b border-r px-2 py-1.5 text-left font-medium"
                  title={c.why_important}
                >
                  {c.name}
                </th>
              ))}
            </tr>
            <tr>
              {competences.map((c) =>
                evaluatorList.length > 0 ? (
                  evaluatorList.map((ev) => (
                    <th
                      key={`${competenceId(c)}::${ev.id}`}
                      className="border-b border-r bg-muted/20 px-2 py-1 text-[10px] font-normal text-muted-foreground"
                      title={ev.name}
                    >
                      {ev.name.length > 10
                        ? `${ev.name.slice(0, 10)}…`
                        : ev.name}
                    </th>
                  ))
                ) : (
                  <th
                    key={`${competenceId(c)}::self`}
                    className="border-b border-r bg-muted/20 px-2 py-1 text-[10px] font-normal text-muted-foreground"
                  >
                    {t("canvasEvaluatorYou")}
                  </th>
                ),
              )}
            </tr>
          </thead>
          <tbody>
            {virtualize ? (
              <>
                <SpacerRow
                  height={rowVirtualizer.getVirtualItems()[0]?.start ?? 0}
                  cols={1 + Math.max(colMeta.length, competences.length)}
                />
                {rowVirtualizer.getVirtualItems().map((vRow) => {
                  const cand = candidates[vRow.index];
                  if (!cand) return null;
                  return renderRow(
                    cand,
                    vRow.index,
                    competences,
                    evaluatorList,
                    selfEvaluatorId,
                    Boolean(inviteToken),
                    dirtyCells,
                    pendingCells,
                    scale,
                    setScore,
                    t,
                  );
                })}
                <SpacerRow
                  height={
                    rowVirtualizer.getTotalSize() -
                    ((rowVirtualizer.getVirtualItems().slice(-1)[0]?.end) ?? 0)
                  }
                  cols={1 + Math.max(colMeta.length, competences.length)}
                />
              </>
            ) : (
              candidates.map((cand, rowIdx) =>
                renderRow(
                  cand,
                  rowIdx,
                  competences,
                  evaluatorList,
                  selfEvaluatorId,
                  Boolean(inviteToken),
                  dirtyCells,
                  pendingCells,
                  scale,
                  setScore,
                  t,
                ),
              )
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
