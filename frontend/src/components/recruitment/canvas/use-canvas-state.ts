"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { api, ApiError } from "@/lib/api";
import type { AssessmentConflictState, CanvasData } from "@/lib/types";
import { toast } from "sonner";

interface UseCanvasStateOptions {
  vacancyId: string;
  /** Limit canvas to one candidate (compact mode). */
  candidateVacancyId?: string;
  /** Use a token-based mutation endpoint (invited evaluator). */
  inviteToken?: string;
  autosaveDelay?: number;
}

export interface CellAddress {
  candidateVacancyId: string;
  competenceId: string;
  evaluatorId: string;
}

export interface CellEdit extends CellAddress {
  previous: number | null;
  next: number | null;
}

interface UseCanvasStateResult {
  data: CanvasData | null;
  loading: boolean;
  error: string | null;
  pendingCells: Set<string>;
  dirtyCells: Set<string>;
  selfEvaluatorId: string | null;
  reload: () => Promise<void>;
  setScore: (
    candidateVacancyId: string,
    competenceId: string,
    evaluatorId: string,
    score: number | null,
  ) => void;
  flush: () => Promise<void>;
  undo: () => void;
  canUndo: boolean;
  /** Cells the backend rejected with HTTP 412 (HRP-266 conflict
   * detection). Each entry carries the local score the user tried to
   * write so the conflict dialog can render "Yours" vs "Theirs". */
  conflicts: Map<string, AssessmentConflictState>;
  /** Caller picks ``mine`` (refetch + retry POST with fresh If-Match) or
   * ``theirs`` (refetch and drop the local edit). Both clear the entry
   * from ``conflicts``. */
  resolveConflict: (
    cellKey: string,
    choice: "mine" | "theirs",
  ) => Promise<void>;
}

const HISTORY_LIMIT = 20;

function cellKey(addr: CellAddress) {
  return `${addr.candidateVacancyId}::${addr.competenceId}::${addr.evaluatorId}`;
}

export function useCanvasState({
  vacancyId,
  candidateVacancyId,
  inviteToken,
  autosaveDelay = 500,
}: UseCanvasStateOptions): UseCanvasStateResult {
  const t = useTranslations("recruitment");
  const [data, setData] = useState<CanvasData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dirtyCells, setDirtyCells] = useState<Set<string>>(new Set());
  const [pendingCells, setPendingCells] = useState<Set<string>>(new Set());
  const [history, setHistory] = useState<CellEdit[]>([]);
  const [selfEvaluatorId, setSelfEvaluatorId] = useState<string | null>(null);
  const [conflicts, setConflicts] = useState<
    Map<string, AssessmentConflictState>
  >(() => new Map());
  const flushTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const queue = useRef<Map<string, CellEdit>>(new Map());
  // HRP-266: version snapshot per cell — populated from each successful
  // write so subsequent autosaves on the same cell ship If-Match and
  // the backend can race-detect a parallel editor with a 412.
  const versionMap = useRef<Map<string, number>>(new Map());

  const selfEvaluatorRef = useRef<string | null>(null);
  selfEvaluatorRef.current = selfEvaluatorId;

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const url = inviteToken
        ? `/recruitment/invite/${inviteToken}/canvas`
        : `/recruitment/vacancies/${vacancyId}/canvas`;
      const result = await api.get<CanvasData & { evaluator_id?: string }>(url);
      const filtered = candidateVacancyId
        ? {
            ...result,
            candidates: result.candidates.filter(
              (c) => c.candidate_vacancy_id === candidateVacancyId,
            ),
          }
        : result;
      setData(filtered);
      // The reload acts as a snapshot reset for the conflict detection —
      // the versions we cached are stale by definition.
      versionMap.current.clear();
      if (result.evaluator_id) {
        setSelfEvaluatorId(result.evaluator_id);
      } else if (!inviteToken && !selfEvaluatorRef.current) {
        try {
          const me = await api.get<{ id: string }>("/auth/me");
          setSelfEvaluatorId(me.id);
        } catch {
          /* ignore */
        }
      }
    } catch (err) {
      setError(
        err instanceof Error ? err.message : t("canvasLoadFailed"),
      );
    } finally {
      setLoading(false);
    }
  }, [vacancyId, candidateVacancyId, inviteToken, t]);

  useEffect(() => {
    reload();
  }, [reload]);

  const flush = useCallback(async () => {
    if (queue.current.size === 0) return;
    const edits = Array.from(queue.current.values());
    queue.current.clear();
    const editKeys = edits.map(cellKey);
    setDirtyCells((prev) => {
      const next = new Set(prev);
      for (const k of editKeys) next.delete(k);
      return next;
    });
    setPendingCells((prev) => {
      const next = new Set(prev);
      for (const k of editKeys) next.add(k);
      return next;
    });

    const failed: CellEdit[] = [];
    const conflicted: {
      edit: CellEdit;
      expectedVersion: number | null;
      serverMessage: string;
    }[] = [];
    await Promise.all(
      edits.map(async (edit) => {
        const key = cellKey(edit);
        try {
          if (inviteToken) {
            await api.post(
              `/recruitment/invite/${inviteToken}/assessments`,
              {
                candidate_vacancy_id: edit.candidateVacancyId,
                competence_id: edit.competenceId,
                score: edit.next,
              },
            );
          } else {
            const knownVersion = versionMap.current.get(key);
            // ``!== undefined`` so a hypothetical version 0 still ships
            // ``If-Match`` — backend currently starts at 1 but a future
            // 0-indexed schema would silently disable conflict detection
            // under a plain truthy check.
            const headers =
              knownVersion !== undefined
                ? { "If-Match": `W/"${knownVersion}"` }
                : undefined;
            const response = await api.post<{ version: number }>(
              `/recruitment/candidate-vacancies/${edit.candidateVacancyId}/assessments`,
              {
                competence_id: edit.competenceId,
                score: edit.next,
              },
              headers ? { headers } : undefined,
            );
            if (response && typeof response.version === "number") {
              versionMap.current.set(key, response.version);
            }
          }
        } catch (err) {
          if (err instanceof ApiError && err.status === 412) {
            conflicted.push({
              edit,
              expectedVersion: versionMap.current.get(key) ?? null,
              serverMessage: err.message,
            });
          } else {
            failed.push(edit);
          }
        }
      }),
    );

    setPendingCells((prev) => {
      const next = new Set(prev);
      for (const k of editKeys) next.delete(k);
      return next;
    });

    if (failed.length > 0) {
      // Re-queue failed edits (don't clobber any newer edits made by the
      // user for the same cell — keep whatever is already in
      // queue.current for that key).
      for (const edit of failed) {
        const key = cellKey(edit);
        if (!queue.current.has(key)) {
          queue.current.set(key, edit);
        }
      }
      setDirtyCells((prev) => {
        const next = new Set(prev);
        for (const edit of failed) {
          if (queue.current.has(cellKey(edit))) {
            next.add(cellKey(edit));
          }
        }
        return next;
      });
      toast.error(t("canvasSaveFailedCount", { count: failed.length }));
    }

    if (conflicted.length > 0) {
      // 412 → freeze the cell with a conflict marker; the parent grid
      // shows a modal so the user can pick Yours / Theirs. The edit is
      // not re-queued — autosave-retrying with the same stale If-Match
      // would only loop on 412.
      setConflicts((prev) => {
        const next = new Map(prev);
        for (const c of conflicted) {
          const key = cellKey(c.edit);
          next.set(key, {
            cellKey: key,
            candidateVacancyId: c.edit.candidateVacancyId,
            competenceId: c.edit.competenceId,
            evaluatorId: c.edit.evaluatorId,
            mine: c.edit.next,
            expectedVersion: c.expectedVersion,
            serverMessage: c.serverMessage,
          });
        }
        return next;
      });
      toast.warning(
        t("canvasConflictToast", { count: conflicted.length }),
      );
    }
  }, [inviteToken, t]);

  const scheduleFlush = useCallback(() => {
    if (flushTimer.current) clearTimeout(flushTimer.current);
    flushTimer.current = setTimeout(() => {
      void flush();
    }, autosaveDelay);
  }, [flush, autosaveDelay]);

  const dataRef = useRef<CanvasData | null>(null);
  dataRef.current = data;

  const setScore = useCallback(
    (
      candidateVacancyId: string,
      competenceId: string,
      evaluatorId: string,
      score: number | null,
    ) => {
      // Compute previous from the latest committed state via ref — avoids
      // running side effects inside the setData updater (StrictMode would
      // double-invoke them).
      const current = dataRef.current;
      const cand = current?.candidates.find(
        (c) => c.candidate_vacancy_id === candidateVacancyId,
      );
      const previous = cand?.human_scores[competenceId]?.[evaluatorId] ?? null;
      const key = cellKey({ candidateVacancyId, competenceId, evaluatorId });
      const edit: CellEdit = {
        candidateVacancyId,
        competenceId,
        evaluatorId,
        previous,
        next: score,
      };

      setData((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          candidates: prev.candidates.map((c) => {
            if (c.candidate_vacancy_id !== candidateVacancyId) return c;
            const compMap = { ...(c.human_scores[competenceId] ?? {}) };
            if (score === null) {
              delete compMap[evaluatorId];
            } else {
              compMap[evaluatorId] = score;
            }
            return {
              ...c,
              human_scores: {
                ...c.human_scores,
                [competenceId]: compMap,
              },
            };
          }),
        };
      });

      queue.current.set(key, edit);
      setDirtyCells((s) => new Set(s).add(key));
      setHistory((h) => [edit, ...h].slice(0, HISTORY_LIMIT));
      scheduleFlush();
    },
    [scheduleFlush],
  );

  const undo = useCallback(() => {
    setHistory((h) => {
      if (h.length === 0) return h;
      const [last, ...rest] = h;
      setScore(
        last.candidateVacancyId,
        last.competenceId,
        last.evaluatorId,
        last.previous,
      );
      return rest;
    });
  }, [setScore]);

  const canUndo = useMemo(() => history.length > 0, [history]);

  const resolveConflict = useCallback(
    async (key: string, choice: "mine" | "theirs") => {
      const entry = conflicts.get(key);
      if (!entry) return;
      // Always refetch first — versionMap is stale on a conflict by
      // definition and "Theirs" needs the actual server state on screen.
      await reload();
      if (choice === "mine") {
        const editKey = cellKey({
          candidateVacancyId: entry.candidateVacancyId,
          competenceId: entry.competenceId,
          evaluatorId: entry.evaluatorId,
        });
        // Local optimistic update so the UI matches what the user is
        // about to send; flush will reconcile when it returns.
        setData((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            candidates: prev.candidates.map((c) => {
              if (c.candidate_vacancy_id !== entry.candidateVacancyId) return c;
              const compMap = { ...(c.human_scores[entry.competenceId] ?? {}) };
              if (entry.mine === null) {
                delete compMap[entry.evaluatorId];
              } else {
                compMap[entry.evaluatorId] = entry.mine;
              }
              return {
                ...c,
                human_scores: {
                  ...c.human_scores,
                  [entry.competenceId]: compMap,
                },
              };
            }),
          };
        });
        // Use the server snapshot we just reloaded as ``previous`` so a
        // later Undo restores the upstream value (their edit) instead of
        // wiping the cell with ``null``.
        const refreshed = dataRef.current?.candidates.find(
          (c) => c.candidate_vacancy_id === entry.candidateVacancyId,
        );
        const previousFromServer =
          refreshed?.human_scores?.[entry.competenceId]?.[entry.evaluatorId] ??
          null;
        queue.current.set(editKey, {
          candidateVacancyId: entry.candidateVacancyId,
          competenceId: entry.competenceId,
          evaluatorId: entry.evaluatorId,
          previous: previousFromServer,
          next: entry.mine,
        });
        setDirtyCells((s) => new Set(s).add(editKey));
        await flush();
      }
      setConflicts((prev) => {
        const next = new Map(prev);
        next.delete(key);
        return next;
      });
    },
    [conflicts, reload, flush],
  );

  return {
    data,
    loading,
    error,
    pendingCells,
    dirtyCells,
    selfEvaluatorId,
    reload,
    setScore,
    flush,
    undo,
    canUndo,
    conflicts,
    resolveConflict,
  };
}

export { cellKey };
