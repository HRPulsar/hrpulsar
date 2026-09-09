"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Loader2,
  Sparkles,
  Trash2,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { ApiError, api } from "@/lib/api";
import { formatDate } from "@/lib/date-format";
import { cn } from "@/lib/utils";
import { BADGE_OUTLINE } from "@/lib/badge-tones";
import { labelForRound } from "@/lib/manager-assessment-rounds";
import { AiVerdictBadge } from "./ai-verdict-badge";
import { AI_ANALYSIS_PRICING } from "@/lib/recruitment-types";
import type {
  BulkAnalyzeResponse,
  CandidateVacancyEnrichedRow,
  VacancyStage,
} from "@/lib/recruitment-types";

// HRP-267 — Sort-control state.
type SortBy = "manager" | "ai" | "custom";
type SortDir = "asc" | "desc";

const SORT_LS_PREFIX = "hrp:vacancy-candidates:sort:";

// HRP-274 introduced a raw/normalized units toggle on the AI column.
// HRP-662 retired the control: "0.92" and "4.6" are the same fact in two
// unit systems, and picking between them is not a hiring decision. The
// table shows the % match — the one number that is directly comparable
// with the manager side — and keeps the tenant-scale normalized score in
// the cell tooltip, or as the value itself when the row has no % match.
// HRP-710: with the toggle gone both call sites asked for the same view,
// so the parameter went with it.
export function formatAiScore(
  row: Pick<CandidateVacancyEnrichedRow, "ai_score_normalized">,
): string {
  // Tenant assessment scale (e.g. 0..5) — one decimal matches how
  // manager scores render.
  const value = row.ai_score_normalized;
  if (value === null || value === undefined) return "—";
  return value.toFixed(1);
}

function readPersistedSort(vacancyId: string): {
  by: SortBy;
  dir: SortDir;
} | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(SORT_LS_PREFIX + vacancyId);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (
      (parsed.by === "manager" ||
        parsed.by === "ai" ||
        parsed.by === "custom") &&
      (parsed.dir === "asc" || parsed.dir === "desc")
    ) {
      return parsed;
    }
  } catch {
    /* corrupted entry — fall back to default */
  }
  return null;
}

function persistSort(
  vacancyId: string,
  value: { by: SortBy; dir: SortDir },
): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(
    SORT_LS_PREFIX + vacancyId,
    JSON.stringify(value),
  );
}

function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${value.toFixed(1)}%`;
}

interface VacancyCandidatesTableProps {
  vacancyId: string;
  reloadToken: number;
  onRowCountChange?: (count: number) => void;
}

// HRP-493: how often the table re-reads itself while an analysis is
// running. Matches the Interviews block, which polls its own statuses
// on the same cadence.
const ANALYSIS_POLL_MS = 5000;

const STAGE_TONE: Record<string, string> = {
  active: BADGE_OUTLINE.blue,
  terminal_positive: BADGE_OUTLINE.emerald,
  terminal_negative: BADGE_OUTLINE.rose,
  terminal_neutral: BADGE_OUTLINE.neutral,
};

// HRP-357: seeded stage colors use ``slate``/``gray``, which have no
// BADGE_OUTLINE entry of their own.
const STAGE_COLOR_ALIASES: Record<string, keyof typeof BADGE_OUTLINE> = {
  slate: "neutral",
  gray: "neutral",
  grey: "neutral",
};

/** HRP-357 REDO: active stages are always blue (per-stage colors made the
 * funnel too loud); only terminal stages keep their own color. */
function stageToneFor(stage: VacancyStage | null | undefined): string {
  if (!stage?.stage_type || stage.stage_type === "active") {
    return STAGE_TONE.active;
  }
  if (stage.color) {
    const key = STAGE_COLOR_ALIASES[stage.color] ?? stage.color;
    const tone = BADGE_OUTLINE[key as keyof typeof BADGE_OUTLINE];
    if (tone) return tone;
  }
  return STAGE_TONE[stage.stage_type] ?? STAGE_TONE.active;
}

export function VacancyCandidatesTable({
  vacancyId,
  reloadToken,
  onRowCountChange,
}: VacancyCandidatesTableProps) {
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const [rows, setRows] = useState<CandidateVacancyEnrichedRow[]>([]);
  const [stages, setStages] = useState<VacancyStage[]>([]);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState<{
    cvId: string;
    targetStage: VacancyStage;
  } | null>(null);
  // HRP-181 REDO #1: confirm before detaching a candidate from the vacancy.
  const [deleting, setDeleting] = useState<{
    cvId: string;
    candidateName: string;
  } | null>(null);

  // ``silent`` is for the HRP-493 poll below: a background re-read must
  // not raise the loading state (the table would blank out every five
  // seconds) and must not toast, or one flaky tick stacks an error
  // notification on the recruiter every five seconds.
  const load = useCallback(
    async (silent = false) => {
      try {
        if (!silent) setLoading(true);
        const [list, funnel] = await Promise.all([
          api.get<CandidateVacancyEnrichedRow[]>(
            `/recruitment/vacancies/${vacancyId}/candidates/enriched`,
          ),
          api.get<VacancyStage[]>(
            `/recruitment/vacancies/${vacancyId}/funnel-stages`,
          ),
        ]);
        setRows(list);
        setStages(funnel);
        onRowCountChange?.(list.length);
      } catch (err) {
        if (!silent) {
          toast.error(
            err instanceof Error
              ? err.message
              : t("candidatesTableLoadFailed"),
          );
        }
      } finally {
        if (!silent) setLoading(false);
      }
    },
    [vacancyId, onRowCountChange, t],
  );

  useEffect(() => {
    load();
  }, [load, reloadToken]);

  // HRP-493 REDO: a row showing "Analyzing…" kept showing it after the
  // run had finished — the table is fetched once and nothing told it the
  // verdict had landed, so only F5 cleared it. Poll while at least one
  // row has a run in flight and stop as soon as none does.
  //
  // ``ai_analysis_in_progress`` is derived server-side from the status
  // of the AIAnalysisRun — the same row AI Insights reads to decide it
  // is still working — so the two surfaces flip on the same fact rather
  // than on two guesses that can drift apart.
  const analysisInFlight = rows.some((r) => r.ai_analysis_in_progress);
  useEffect(() => {
    if (!analysisInFlight) return;
    const timer = setInterval(() => {
      // Nobody is watching a hidden tab; don't keep the backend busy.
      if (document.visibilityState === "visible") void load(true);
    }, ANALYSIS_POLL_MS);
    return () => clearInterval(timer);
  }, [analysisInFlight, load]);

  const applyStageChange = useCallback(
    async (row: CandidateVacancyEnrichedRow, targetStage: VacancyStage) => {
      try {
        // HRP-181 REDO Sweep S2: send the version-based If-Match so the
        // backend's optimistic lock returns 412 when another editor moved
        // this row first — without the header the 412 branch below was
        // unreachable and two recruiters could race a stage move.
        const updated = await api.patch<CandidateVacancyEnrichedRow>(
          `/recruitment/candidate-vacancies/${row.id}`,
          { stage_id: targetStage.id },
          { headers: { "If-Match": `W/"${row.version}"` } },
        );
        setRows((prev) => prev.map((r) => (r.id === row.id ? updated : r)));
        toast.success(
          t("candidatesTableToastMovedTo", { stage: targetStage.name }),
        );
      } catch (err) {
        const msg =
          err instanceof ApiError && err.status === 412
            ? t("candidatesTableRowChanged")
            : err instanceof Error
              ? err.message
              : t("candidatesTableStageChangeFailed");
        toast.error(msg);
        if (err instanceof ApiError && err.status === 412) {
          load();
        }
      }
    },
    [load, t],
  );

  const onStageSelected = useCallback(
    (row: CandidateVacancyEnrichedRow, value: string) => {
      const targetStage = stages.find((s) => s.id === value);
      if (!targetStage || targetStage.id === row.stage_id) return;
      if (
        targetStage.stage_type === "terminal_positive" ||
        targetStage.stage_type === "terminal_negative"
      ) {
        setPending({ cvId: row.id, targetStage });
        return;
      }
      applyStageChange(row, targetStage);
    },
    [applyStageChange, stages],
  );

  const confirmTerminal = useCallback(async () => {
    if (!pending) return;
    const row = rows.find((r) => r.id === pending.cvId);
    if (row) await applyStageChange(row, pending.targetStage);
    setPending(null);
  }, [applyStageChange, pending, rows]);

  const confirmDelete = useCallback(async () => {
    if (!deleting) return;
    try {
      await api.delete(`/recruitment/candidate-vacancies/${deleting.cvId}`);
      setRows((prev) => prev.filter((r) => r.id !== deleting.cvId));
      onRowCountChange?.(rows.length - 1);
      toast.success(
        t("candidatesTableToastRemoved", { name: deleting.candidateName }),
      );
    } catch (err) {
      toast.error(
        err instanceof Error
          ? err.message
          : t("candidatesTableRemoveFailed"),
      );
    } finally {
      setDeleting(null);
    }
  }, [deleting, onRowCountChange, rows.length, t]);

  const pendingCandidate = useMemo(
    () => (pending ? rows.find((r) => r.id === pending.cvId) : null),
    [pending, rows],
  );

  // HRP-204 — bulk resume-only analyze. Recruiter / Admin gate is
  // enforced server-side; we still hide the bar when no row qualifies.
  const eligibleRows = useMemo(
    () =>
      rows.filter(
        (r) =>
          r.ai_verdict === "pending" &&
          r.ai_readiness === "resume_only",
      ),
    [rows],
  );

  // HRP-267 — sort-control state. URL beats localStorage so a shared
  // link reproduces the exact view the sender saw; localStorage is the
  // per-tenant default once the user opens the vacancy fresh.
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialSort = useMemo<{ by: SortBy; dir: SortDir }>(() => {
    const urlBy = searchParams.get("sort");
    const urlDir = searchParams.get("dir");
    if (urlBy === "manager" || urlBy === "ai" || urlBy === "custom") {
      return {
        by: urlBy,
        dir: urlDir === "asc" ? "asc" : "desc",
      };
    }
    return readPersistedSort(vacancyId) ?? { by: "manager", dir: "desc" };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vacancyId]);
  const [sortBy, setSortBy] = useState<SortBy>(initialSort.by);
  const [sortDir, setSortDir] = useState<SortDir>(initialSort.dir);
  // Persist whenever the user changes the sort, and reflect it in the
  // URL without scrolling the page.
  //
  // Two subtleties from the HRP-267 wave-review:
  // 1. ``searchParams`` is intentionally not in the deps — including it
  //    would re-run on every parent re-render. To avoid stale-snapshot
  //    clobbering of unrelated params we read from
  //    ``window.location.search`` *inside* the effect.
  // 2. We skip the initial-mount write when the URL + localStorage
  //    already match the in-memory state — otherwise a clean
  //    ``/vacancy/{id}`` deep link gets two new ``?sort=&dir=`` params
  //    on every open and pollutes browser history.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const current = new URLSearchParams(window.location.search);
    const desiredBy = sortBy;
    const desiredDir = sortDir;
    const urlMatches =
      current.get("sort") === desiredBy && current.get("dir") === desiredDir;
    const persisted = readPersistedSort(vacancyId);
    const persistedMatches =
      persisted?.by === desiredBy && persisted?.dir === desiredDir;
    if (!persistedMatches) {
      persistSort(vacancyId, { by: desiredBy, dir: desiredDir });
    }
    if (!urlMatches) {
      current.set("sort", desiredBy);
      current.set("dir", desiredDir);
      router.replace(`?${current.toString()}`, { scroll: false });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vacancyId, sortBy, sortDir]);

  // Terminal stages live at the bottom regardless of which side the
  // recruiter sorts by — same posture as the backend default.
  const sortedRows = useMemo(() => {
    if (sortBy === "custom") return rows;
    const sign = sortDir === "asc" ? 1 : -1;
    const isTerminal = (s: string | null | undefined): boolean =>
      s === "terminal_positive" ||
      s === "terminal_negative" ||
      // ``terminal_neutral`` (default ``withdrew`` stage) also counts —
      // a withdrawn candidate should not float to the top of an active
      // funnel just because she had a strong manager score.
      s === "terminal_neutral";
    return [...rows].sort((a, b) => {
      const aTerminal = isTerminal(a.stage?.stage_type);
      const bTerminal = isTerminal(b.stage?.stage_type);
      if (aTerminal !== bTerminal) return aTerminal ? 1 : -1;
      const key: keyof CandidateVacancyEnrichedRow =
        sortBy === "manager" ? "manager_percent" : "ai_percent";
      const av = (a[key] ?? null) as number | null;
      const bv = (b[key] ?? null) as number | null;
      if (av === null && bv === null) {
        return (
          new Date(b.added_at).getTime() - new Date(a.added_at).getTime()
        );
      }
      if (av === null) return 1; // nulls last
      if (bv === null) return -1;
      return sign * (av - bv);
    });
  }, [rows, sortBy, sortDir]);

  if (loading && rows.length === 0) {
    return (
      <div
        className="flex items-center justify-center py-8 text-sm text-muted-foreground"
        data-testid="vacancy-candidates-table-loading"
      >
        <Loader2 className="mr-2 size-4 animate-spin" />{" "}
        {t("candidatesTableLoading")}
      </div>
    );
  }

  if (rows.length === 0) {
    return (
      <p
        className="py-6 text-center text-sm text-muted-foreground"
        data-testid="vacancy-candidates-table-empty"
      >
        {t("candidatesTableEmpty")}
      </p>
    );
  }

  return (
    <>
      <BulkAnalyzeBar
        vacancyId={vacancyId}
        eligibleRows={eligibleRows}
        onDone={() => void load()}
      />
      <SortControl
        sortBy={sortBy}
        sortDir={sortDir}
        onChange={(by, dir) => {
          setSortBy(by);
          setSortDir(dir);
        }}
      />
      {/* Desktop ≥ md: 10 columns — HRP-662 dropped the AI DATA one. */}
      <div
        className="hidden md:block overflow-x-auto rounded-md border"
        data-testid="vacancy-candidates-table"
      >
        <table className="min-w-[1200px] w-full text-sm">
          <thead className="bg-muted/50 text-left text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="px-3 py-2 font-medium">{tc("candidate")}</th>
              <th className="px-3 py-2 font-medium">
                {t("candidatesTableColLastPosition")}
              </th>
              <th className="px-3 py-2 text-right font-medium">
                {t("candidatesTableColExp")}
              </th>
              <th className="px-3 py-2 font-medium">
                {t("candidatesTableColStage")}
              </th>
              {/* HRP-662: each of the three comparison columns says what
                  its number is. Two of them are % of the vacancy profile
                  scored by a different assessor; the third counts where
                  the two disagree. None of that was written anywhere. */}
              <th
                className="px-3 py-2 text-center font-medium"
                title={t("candidatesTableColManagerHint")}
              >
                {t("candidatesTableColManager")}
              </th>
              <th
                className="px-3 py-2 text-center font-medium"
                title={t("candidatesTableColAiHint")}
              >
                {t("candidatesTableColAi")}
              </th>
              <th
                className="px-3 py-2 text-center font-medium"
                title={t("candidatesTableColDivergenceHint")}
              >
                {t("candidatesTableColDivergence")}
              </th>
              <th className="px-3 py-2 font-medium">
                {t("candidatesTableColAiVerdict")}
              </th>
              <th className="px-3 py-2 text-right font-medium">
                {t("candidatesTableColAdded")}
              </th>
              <th
                className="px-3 py-2 text-right font-medium"
                aria-label={t("columnActions")}
              />
            </tr>
          </thead>
          <tbody className="divide-y">
            {sortedRows.map((row) => (
              <Row
                key={row.id}
                row={row}
                vacancyId={vacancyId}
                stages={stages}
                onStageSelected={onStageSelected}
                onDelete={(cvId, candidateName) =>
                  setDeleting({ cvId, candidateName })
                }
              />
            ))}
          </tbody>
        </table>
      </div>

      {/* Mobile < md: card list */}
      <div className="md:hidden space-y-2">
        {sortedRows.map((row) => (
          <MobileCard
            key={row.id}
            row={row}
            vacancyId={vacancyId}
            stages={stages}
            onStageSelected={onStageSelected}
            onDelete={(cvId, candidateName) =>
              setDeleting({ cvId, candidateName })
            }
          />
        ))}
      </div>

      <ConfirmDialog
        open={!!pending}
        onOpenChange={(o) => {
          if (!o) setPending(null);
        }}
        title={
          pending
            ? t("candidatesTableMoveTitle", {
                name:
                  pendingCandidate?.candidate_name ??
                  t("candidatesTableCandidateFallback"),
                stage: pending.targetStage.name,
              })
            : ""
        }
        description={t("candidatesTableTerminalDescription")}
        confirmLabel={t("candidatesTableConfirmMove")}
        destructive={pending?.targetStage.stage_type === "terminal_negative"}
        onConfirm={confirmTerminal}
        testId="vacancy-stage-terminal-confirm-modal"
      />
      <ConfirmDialog
        open={!!deleting}
        onOpenChange={(o) => {
          if (!o) setDeleting(null);
        }}
        title={
          deleting
            ? t("candidatesTableRemoveTitle", {
                name: deleting.candidateName,
              })
            : ""
        }
        description={t("candidatesTableRemoveDescription")}
        confirmLabel={t("candidatesTableConfirmRemove")}
        destructive
        onConfirm={confirmDelete}
        testId="vacancy-candidate-delete-confirm-modal"
      />
    </>
  );
}

interface RowProps {
  row: CandidateVacancyEnrichedRow;
  vacancyId: string;
  stages: VacancyStage[];
  onStageSelected: (row: CandidateVacancyEnrichedRow, value: string) => void;
  onDelete: (cvId: string, candidateName: string) => void;
}

function Row({
  row,
  vacancyId,
  stages,
  onStageSelected,
  onDelete,
}: RowProps) {
  const t = useTranslations("recruitment");
  const stageTone = stageToneFor(row.stage);
  const divergent = row.score_divergence;
  return (
    <tr
      data-testid={`vacancy-candidates-row-${row.id}`}
      // HRP-663: same tinting language the divergence cells already use —
      // a conditional Tailwind tone through `cn`, not a second mechanism.
      className={cn(
        "hover:bg-muted/30",
        row.is_employee && "bg-indigo-50/60 dark:bg-indigo-950/20",
      )}
    >
      <td className="px-3 py-2 align-top">
        <Link
          href={`/recruitment/candidates/${row.candidate_id}?vacancyId=${vacancyId}`}
          className="font-medium hover:underline"
        >
          {row.candidate_name}
        </Link>
        {row.is_employee && (
          <Badge
            variant="outline"
            className={cn("ml-2 border text-[10px]", BADGE_OUTLINE.indigo)}
            data-testid={`vacancy-candidates-row-${row.id}-internal-badge`}
          >
            {t("internalCandidateBadge")}
          </Badge>
        )}
      </td>
      <td className="px-3 py-2 align-top text-muted-foreground">
        {row.last_position || "—"}
      </td>
      <td className="px-3 py-2 align-top text-right tabular-nums text-muted-foreground">
        {row.years_of_experience !== null
          ? `${row.years_of_experience}y`
          : "—"}
      </td>
      <td className="px-3 py-2 align-top">
        <Select
          value={row.stage_id ?? undefined}
          onValueChange={(v) => onStageSelected(row, v)}
        >
          <SelectTrigger
            size="sm"
            className={cn("min-w-[140px] border", stageTone)}
            data-testid={`vacancy-candidates-row-${row.id}-stage-select`}
          >
            <SelectValue placeholder={t("candidatesTableSetStage")}>
              {/* HRP-181 REDO #2: render the stage name, not the raw uuid */}
              {(value) =>
                stages.find((s) => s.id === value)?.name ??
                row.stage?.name ??
                t("candidatesTableSetStage")
              }
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            {stages.map((s) => (
              <SelectItem key={s.id} value={s.id}>
                {s.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </td>
      <td
        className={cn(
          "px-3 py-2 align-top text-center tabular-nums",
          divergent && "bg-amber-50",
        )}
        data-testid={`vacancy-candidates-row-${row.id}-manager-score`}
      >
        <ScoreCell
          percent={row.manager_percent}
          score={
            row.manager_score !== null ? row.manager_score.toFixed(1) : null
          }
          percentTestId={`vacancy-candidates-row-${row.id}-manager-percent`}
          emptyLabel={t("candidatesTableManagerNotAssessed")}
          emptyHint={t("candidatesTableManagerNotAssessedHint")}
          emptyTestId={`vacancy-candidates-row-${row.id}-manager-empty`}
          tooltipSuffix={managerRoundLine(t, row)}
        />
      </td>
      <td
        className={cn(
          "px-3 py-2 align-top text-center tabular-nums",
          divergent && "bg-amber-50",
        )}
        data-testid={`vacancy-candidates-row-${row.id}-ai-score`}
      >
        <ScoreCell
          percent={row.ai_percent}
          score={formatAiScore(row)}
          scoreTestId={`vacancy-candidates-row-${row.id}-ai-score-value`}
          percentTestId={`vacancy-candidates-row-${row.id}-ai-percent`}
          emptyLabel={t("candidatesTableAiNotAnalyzed")}
          emptyHint={t("candidatesTableAiNotAnalyzedHint")}
          emptyTestId={`vacancy-candidates-row-${row.id}-ai-empty`}
        />
      </td>
      <td
        className="px-3 py-2 align-top text-center"
        data-testid={`vacancy-candidates-row-${row.id}-divergence`}
      >
        <DivergenceBadge row={row} vacancyId={vacancyId} />
      </td>
      <td className="px-3 py-2 align-top">
        <AiVerdictBadge
          verdict={row.ai_verdict}
          aiReadiness={row.ai_readiness}
          analysisMode={row.ai_analysis_mode ?? null}
          inProgress={row.ai_analysis_in_progress ?? false}
          summary={row.ai_verdict_summary}
          keyStrength={row.ai_key_strength}
          keyRisk={row.ai_key_risk}
          riskMitigation={row.ai_risk_mitigation}
          testIdPrefix={`vacancy-candidates-row-${row.id}`}
        />
        {/* HRP-662: the reason for the verdict belongs next to the
            verdict. It used to live only behind the info popover, so a
            recruiter scanning the list saw a colour and a word and had
            to guess what the model actually found. */}
        {row.ai_verdict_summary && (
          <p
            className="mt-1 line-clamp-2 max-w-[22rem] text-xs text-muted-foreground"
            title={row.ai_verdict_summary}
            data-testid={`vacancy-candidates-row-${row.id}-ai-verdict-reason`}
          >
            {row.ai_verdict_summary}
          </p>
        )}
      </td>
      <td className="px-3 py-2 align-top text-right text-xs text-muted-foreground">
        {formatDate(row.added_at)}
      </td>
      <td className="px-3 py-2 align-top text-right">
        <button
          type="button"
          onClick={() => onDelete(row.id, row.candidate_name)}
          className="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
          aria-label={t("candidatesTableRemoveAria", {
            name: row.candidate_name,
          })}
          data-testid={`vacancy-candidates-row-${row.id}-delete-btn`}
        >
          <Trash2 className="size-4" />
        </button>
      </td>
    </tr>
  );
}

interface MobileCardProps {
  row: CandidateVacancyEnrichedRow;
  vacancyId: string;
  stages: VacancyStage[];
  onStageSelected: (row: CandidateVacancyEnrichedRow, value: string) => void;
  onDelete: (cvId: string, candidateName: string) => void;
}

function MobileCard({
  row,
  vacancyId,
  stages,
  onStageSelected,
  onDelete,
}: MobileCardProps) {
  const t = useTranslations("recruitment");
  const stageTone = stageToneFor(row.stage);
  return (
    <div
      className={cn(
        "rounded-md border p-3",
        row.is_employee && "bg-indigo-50/60 dark:bg-indigo-950/20",
      )}
      data-testid={`vacancy-candidates-mobile-row-${row.id}`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <Link
            href={`/recruitment/candidates/${row.candidate_id}?vacancyId=${vacancyId}`}
            className="block truncate text-sm font-semibold hover:underline"
          >
            {row.candidate_name}
          </Link>
          {row.is_employee && (
            <Badge
              variant="outline"
              className={cn("mt-1 border text-[10px]", BADGE_OUTLINE.indigo)}
              data-testid={`vacancy-candidates-mobile-row-${row.id}-internal-badge`}
            >
              {t("internalCandidateBadge")}
            </Badge>
          )}
          {row.last_position && (
            <p className="truncate text-xs text-muted-foreground">
              {row.last_position}
            </p>
          )}
        </div>
        <Badge variant="outline" className={cn("border", stageTone)}>
          {row.stage?.name ?? "—"}
        </Badge>
      </div>
      <div className="mt-2 grid grid-cols-3 gap-2 text-xs text-muted-foreground">
        <div>
          <p className="uppercase tracking-wide">
            {t("candidatesTableMobileExp")}
          </p>
          <p className="text-foreground tabular-nums">
            {row.years_of_experience !== null
              ? `${row.years_of_experience}y`
              : "—"}
          </p>
        </div>
        <div>
          <p className="uppercase tracking-wide">
            {t("candidatesTableColManager")}
          </p>
          <ScoreCell
            percent={row.manager_percent}
            score={
              row.manager_score !== null ? row.manager_score.toFixed(1) : null
            }
            percentTestId={`vacancy-candidates-mobile-row-${row.id}-manager-percent`}
            emptyLabel={t("candidatesTableManagerNotAssessed")}
            emptyHint={t("candidatesTableManagerNotAssessedHint")}
            emptyTestId={`vacancy-candidates-mobile-row-${row.id}-manager-empty`}
            tooltipSuffix={managerRoundLine(t, row)}
          />
        </div>
        <div>
          <p className="uppercase tracking-wide">
            {t("candidatesTableColAi")}
          </p>
          <ScoreCell
            percent={row.ai_percent}
            score={formatAiScore(row)}
            scoreTestId={`vacancy-candidates-mobile-row-${row.id}-ai-score-value`}
            percentTestId={`vacancy-candidates-mobile-row-${row.id}-ai-percent`}
            emptyLabel={t("candidatesTableAiNotAnalyzed")}
            emptyHint={t("candidatesTableAiNotAnalyzedHint")}
            emptyTestId={`vacancy-candidates-mobile-row-${row.id}-ai-empty`}
          />
        </div>
      </div>
      {(row.divergence_count ?? 0) > 0 && (
        <div className="mt-2">
          <DivergenceBadge row={row} vacancyId={vacancyId} />
        </div>
      )}
      <div className="mt-2 flex items-center justify-between gap-2">
        <Select
          value={row.stage_id ?? undefined}
          onValueChange={(v) => onStageSelected(row, v)}
        >
          <SelectTrigger
            size="sm"
            className={cn("border", stageTone)}
            data-testid={`vacancy-candidates-mobile-row-${row.id}-stage-select`}
          >
            <SelectValue placeholder={t("candidatesTableSetStage")}>
              {(value) =>
                stages.find((s) => s.id === value)?.name ??
                row.stage?.name ??
                t("candidatesTableSetStage")
              }
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            {stages.map((s) => (
              <SelectItem key={s.id} value={s.id}>
                {s.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <AiVerdictBadge
          verdict={row.ai_verdict}
          aiReadiness={row.ai_readiness}
          analysisMode={row.ai_analysis_mode ?? null}
          inProgress={row.ai_analysis_in_progress ?? false}
          summary={row.ai_verdict_summary}
          keyStrength={row.ai_key_strength}
          keyRisk={row.ai_key_risk}
          riskMitigation={row.ai_risk_mitigation}
          testIdPrefix={`vacancy-candidates-mobile-row-${row.id}`}
        />
        <button
          type="button"
          onClick={() => onDelete(row.id, row.candidate_name)}
          className="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
          aria-label={t("candidatesTableRemoveAria", {
            name: row.candidate_name,
          })}
          data-testid={`vacancy-candidates-mobile-row-${row.id}-delete-btn`}
        >
          <Trash2 className="size-4" />
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// HRP-267 — Sort-control + Divergence badge.
// ---------------------------------------------------------------------------


interface SortControlProps {
  sortBy: SortBy;
  sortDir: SortDir;
  onChange: (by: SortBy, dir: SortDir) => void;
}

interface SortButtonProps<TValue extends string> {
  value: TValue;
  label: string;
  testid: string;
  active: boolean;
  onSelect: (value: TValue) => void;
}

function SortButton<TValue extends string>({
  value,
  label,
  testid,
  active,
  onSelect,
}: SortButtonProps<TValue>) {
  return (
    <button
      type="button"
      onClick={() => onSelect(value)}
      className={cn(
        "rounded-md border px-2 py-1 text-xs",
        active
          ? "border-foreground/30 bg-muted font-medium"
          : "border-transparent text-muted-foreground hover:text-foreground",
      )}
      data-testid={testid}
      aria-pressed={active}
    >
      {label}
    </button>
  );
}

function SortControl({ sortBy, sortDir, onChange }: SortControlProps) {
  const t = useTranslations("recruitment");
  const selectBy = (next: SortBy) => onChange(next, sortDir);
  return (
    <div
      className="flex flex-wrap items-center gap-2 px-1 pb-2 text-xs"
      data-testid="vacancy-candidates-sort-control"
    >
      <span className="text-muted-foreground">
        {t("candidatesTableSortBy")}
      </span>
      <SortButton
        value="manager"
        label={t("candidatesTableSortByManager")}
        testid="vacancy-candidates-sort-by-manager"
        active={sortBy === "manager"}
        onSelect={selectBy}
      />
      <SortButton
        value="ai"
        label={t("candidatesTableSortByAi")}
        testid="vacancy-candidates-sort-by-ai"
        active={sortBy === "ai"}
        onSelect={selectBy}
      />
      <SortButton
        value="custom"
        label={t("candidatesTableSortCustom")}
        testid="vacancy-candidates-sort-custom"
        active={sortBy === "custom"}
        onSelect={selectBy}
      />
      <button
        type="button"
        onClick={() =>
          onChange(sortBy, sortDir === "asc" ? "desc" : "asc")
        }
        disabled={sortBy === "custom"}
        className="ml-1 inline-flex size-7 items-center justify-center rounded-md border text-muted-foreground hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40"
        aria-label={t("candidatesTableSortDirAria", { dir: sortDir })}
        data-testid="vacancy-candidates-sort-dir-toggle"
      >
        {sortBy === "custom" ? (
          <ArrowUpDown className="size-3.5" />
        ) : sortDir === "asc" ? (
          <ArrowUp className="size-3.5" />
        ) : (
          <ArrowDown className="size-3.5" />
        )}
      </button>
    </div>
  );
}


/**
 * HRP-662 — one shape for the MANAGER and AI columns.
 *
 * Two changes over what the two hand-rolled cells did before:
 *
 * 1. The % match leads. It is the only number the two sides share —
 *    a manager level (1..4 of the vacancy scale) and an AI score
 *    (0..1 rebased onto the tenant scale) printed side by side read as
 *    a comparison they are not. The underlying score stays as the
 *    second line for anyone who wants it.
 * 2. "No opinion yet" says so. A bare em dash cannot tell "nobody has
 *    assessed this candidate" from "the value failed to load".
 */
/** HRP-727: "Round: Final" — the second tooltip line on the Manager cell,
 * naming the round the score was computed from. Absent for a score with no
 * round behind it (a hand-typed one). */
function managerRoundLine(
  t: (key: string, values?: Record<string, string | number>) => string,
  row: CandidateVacancyEnrichedRow,
): string | null {
  const round = row.manager_score_round;
  return round
    ? t("candidatesTableScoreRoundTooltip", { round: labelForRound(t, round) })
    : null;
}

function ScoreCell({
  percent,
  score,
  scoreTestId,
  percentTestId,
  emptyLabel,
  emptyHint,
  emptyTestId,
  tooltipSuffix,
}: {
  percent: number | null | undefined;
  score: string | null;
  scoreTestId?: string;
  percentTestId: string;
  emptyLabel: string;
  emptyHint: string;
  emptyTestId: string;
  /** HRP-727: extra tooltip line under "Underlying score" — the Manager
   * column uses it to name the round the score was computed from. */
  tooltipSuffix?: string | null;
}) {
  const t = useTranslations("recruitment");
  const hasScore = score !== null && score !== "—";
  const hasPercent = percent !== null && percent !== undefined;
  if (!hasScore && !hasPercent) {
    return (
      <span
        className="text-xs text-muted-foreground"
        title={emptyHint}
        data-testid={emptyTestId}
      >
        {emptyLabel}
      </span>
    );
  }
  // One number per cell. The % is what the two columns share; the
  // underlying score moves into the tooltip rather than sitting under
  // it as a second, differently-scaled number.
  if (hasPercent) {
    const scoreLine = hasScore
      ? t("candidatesTableScoreTooltip", { score })
      : null;
    const tooltip =
      scoreLine && tooltipSuffix
        ? `${scoreLine}\n${tooltipSuffix}`
        : (scoreLine ?? undefined);
    return (
      <span
        className="font-medium tabular-nums"
        title={tooltip}
        data-testid={percentTestId}
      >
        {formatPercent(percent)}
      </span>
    );
  }
  return (
    <span className="tabular-nums" data-testid={scoreTestId}>
      {score}
    </span>
  );
}


interface DivergenceBadgeProps {
  row: CandidateVacancyEnrichedRow;
  vacancyId: string;
}

function DivergenceBadge({ row, vacancyId }: DivergenceBadgeProps) {
  const t = useTranslations("recruitment");
  const count = row.divergence_count ?? 0;
  if (count === 0) {
    return (
      <span
        className="text-muted-foreground"
        data-testid={`vacancy-candidates-row-${row.id}-divergence-empty`}
      >
        —
      </span>
    );
  }
  // HRP-507: the preview is capped server-side at 5 competences; anything
  // beyond that is summarised by the trailing "and N more" line.
  const preview = row.divergence_top ?? [];
  const lines = preview.map((c) => {
    const m = c.manager_score === null ? "—" : c.manager_score.toFixed(1);
    const ai = c.ai_score === null ? "—" : c.ai_score.toFixed(1);
    return {
      key: c.competence_id,
      text: t("candidatesTableDivergenceLine", {
        name: c.competence_name,
        manager: m,
        ai,
      }),
    };
  });
  const remaining = count - lines.length;
  return (
    <Tooltip>
      <TooltipTrigger
        render={<span className="inline-flex" />}
        data-testid={`vacancy-candidates-row-${row.id}-divergence-trigger`}
      >
        <Link
          href={`/recruitment/requisitions/${vacancyId}/canvas?filter=divergences`}
          data-testid={`vacancy-candidates-row-${row.id}-divergence-badge`}
          aria-label={t("candidatesTableDivergenceAria", { count })}
        >
          <Badge className="border-amber-400 bg-amber-50 text-amber-900 hover:bg-amber-100 dark:bg-amber-950/30 dark:text-amber-200">
            <AlertTriangle className="mr-1 size-3" />
            {count}
          </Badge>
        </Link>
      </TooltipTrigger>
      <TooltipContent
        className="max-w-xs"
        data-testid={`vacancy-candidates-row-${row.id}-divergence-tooltip`}
      >
        <p className="font-medium">
          {t("candidatesTableDivergentCount", { count })}
        </p>
        {lines.length > 0 && (
          <ul className="mt-1 space-y-0.5">
            {lines.map((line) => (
              <li key={line.key}>• {line.text}</li>
            ))}
          </ul>
        )}
        {remaining > 0 && (
          <p className="mt-0.5">
            {t("candidatesTableDivergenceMore", { count: remaining })}
          </p>
        )}
        <p className="mt-1.5 opacity-80">
          {t("candidatesTableDivergenceCanvasHint")}
        </p>
      </TooltipContent>
    </Tooltip>
  );
}


// ---------------------------------------------------------------------------
// HRP-204 — bulk resume-only analyze bar.
// ---------------------------------------------------------------------------


interface BulkAnalyzeBarProps {
  vacancyId: string;
  eligibleRows: CandidateVacancyEnrichedRow[];
  onDone: () => void;
}


function BulkAnalyzeBar({
  vacancyId,
  eligibleRows,
  onDone,
}: BulkAnalyzeBarProps) {
  const t = useTranslations("recruitment");
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  if (eligibleRows.length === 0) return null;

  const totalCost = eligibleRows.length * AI_ANALYSIS_PRICING.resume_only;

  const confirm = async () => {
    setBusy(true);
    try {
      const res = await api.post<BulkAnalyzeResponse>(
        `/recruitment/vacancies/${vacancyId}/ai-analyses/bulk`,
        {
          candidate_vacancy_ids: eligibleRows.map((r) => r.id),
        },
      );
      const queued = res.queued.length;
      const failed = res.failed.length;
      if (failed > 0) {
        toast(t("candidatesTableBulkQueuedPartial", { queued, failed }));
      } else {
        toast.success(t("candidatesTableBulkQueued", { count: queued }));
      }
      onDone();
    } catch (err) {
      toast.error(
        err instanceof ApiError
          ? err.message
          : t("candidatesTableBulkFailed"),
      );
    } finally {
      setBusy(false);
      setOpen(false);
    }
  };

  return (
    <>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-md border border-dashed bg-amber-50/60 p-3 text-sm">
        <div className="flex items-center gap-2">
          <Sparkles className="size-4 text-amber-700" aria-hidden />
          <span>
            {t.rich("candidatesTableBulkBanner", {
              count: eligibleRows.length,
              strong: (chunks) => (
                <span className="font-medium">{chunks}</span>
              ),
            })}
          </span>
        </div>
        <button
          type="button"
          onClick={() => setOpen(true)}
          disabled={busy}
          className="inline-flex items-center gap-1 rounded-md bg-amber-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-amber-700 disabled:opacity-60"
          data-testid="vacancy-candidates-bulk-analyze-btn"
        >
          {busy ? (
            <Loader2 className="size-3.5 animate-spin" aria-hidden />
          ) : (
            <Sparkles className="size-3.5" aria-hidden />
          )}
          {t("candidatesTableBulkAnalyzeBtn", { cost: totalCost })}
        </button>
      </div>
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title={t("candidatesTableBulkTitle")}
        description={t("candidatesTableBulkDescription", {
          count: eligibleRows.length,
          price: AI_ANALYSIS_PRICING.resume_only,
          total: totalCost,
        })}
        confirmLabel={t("candidatesTableBulkConfirm")}
        onConfirm={confirm}
        testId="vacancy-candidates-bulk-analyze-modal"
      />
    </>
  );
}
