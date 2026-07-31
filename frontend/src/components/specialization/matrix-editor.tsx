"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { AlertCircle, ExternalLink, Plus, X } from "lucide-react";
import {
  DndContext,
  type DragEndEvent,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  horizontalListSortingStrategy,
  sortableKeyboardCoordinates,
} from "@dnd-kit/sortable";
import { toast } from "sonner";
import {
  specializationsApi,
  type MatrixBulk,
  type MatrixBulkWriteGrade,
  type SpecializationGrade,
} from "@/lib/api/specializations";
import type { Competence, CompetenceGroupTree, SkillLevel } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { AddCompetencesDialog } from "@/components/specialization/add-competences-dialog";
import { MatrixCell } from "@/components/specialization/matrix-cell";
import { GradeHeaderCell } from "@/components/specialization/grade-header-cell";
import { IndicatorsTooltip } from "@/components/specialization/indicators-tooltip";
import { SingleGradeList } from "@/components/specialization/single-grade-list";
import { UnsavedChangesBar } from "@/components/specialization/unsaved-changes-bar";
import { ActiveAiSessionBadge } from "@/components/competence-generation/ActiveAiSessionBadge";
import type { ActiveAiSession } from "@/hooks/use-active-ai-sessions";
import { activeAiSessionsKey } from "@/hooks/use-active-ai-sessions";
import { coverageGapMessage } from "@/lib/matrix-grading";

type MatrixState = Record<string, Record<string, string | null>>;

type Props = {
  specId: string;
  bulk: MatrixBulk;
  skillLevels: SkillLevel[];
  competencesPool: Competence[];
  /** HRP-100: full competence tree so the Add-dialog can render groups
   *  with their nesting, not a flat dropdown list. */
  competenceTree: CompetenceGroupTree[];
  highlightedGradeId: string | null;
  gradeMeta: SpecializationGrade[];
  onSaved: (next: MatrixBulk) => void;
  onGradesChanged: (next: SpecializationGrade[]) => void;
  /** HRP-93 Part 2: live AI sessions, indexed via activeAiSessionsKey. */
  activeSessionsMap?: Map<string, ActiveAiSession[]>;
  /** HRP-93 Part 2: open the drawer for a specific session id. */
  onOpenActiveSession?: (sessionId: string) => void;
};

function bulkToState(bulk: MatrixBulk): MatrixState {
  const out: MatrixState = {};
  for (const block of bulk.grades) {
    const inner: Record<string, string | null> = {};
    for (const link of block.links) {
      inner[link.competence_id] = link.skill_level_id;
    }
    out[block.grade_id] = inner;
  }
  return out;
}

function gradesFromMeta(
  meta: SpecializationGrade[],
): SpecializationGrade[] {
  return [...meta].sort((a, b) => a.sort_index - b.sort_index);
}

function competencesInState(
  state: MatrixState,
  pool: Competence[],
): Competence[] {
  const ids = new Set<string>();
  for (const inner of Object.values(state)) {
    for (const compId of Object.keys(inner)) {
      ids.add(compId);
    }
  }
  return pool
    .filter((c) => ids.has(c.id))
    .sort((a, b) => a.title.localeCompare(b.title));
}

export function MatrixEditor({
  specId,
  bulk,
  skillLevels,
  competencesPool,
  competenceTree,
  highlightedGradeId,
  gradeMeta,
  onSaved,
  onGradesChanged,
  activeSessionsMap,
  onOpenActiveSession,
}: Props) {
  const t = useTranslations("company");
  const grades = useMemo(() => gradesFromMeta(gradeMeta), [gradeMeta]);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );
  const sortedLevels = useMemo(
    () => [...skillLevels].sort((a, b) => a.sort_index - b.sort_index),
    [skillLevels],
  );
  const levelSortById = useMemo(() => {
    const map = new Map<string, number>();
    for (const lvl of skillLevels) map.set(lvl.id, lvl.sort_index);
    return map;
  }, [skillLevels]);

  const [savedState, setSavedState] = useState<MatrixState>(() => bulkToState(bulk));
  const [editState, setEditState] = useState<MatrixState>(() => bulkToState(bulk));

  // Re-sync when `bulk` changes shape — e.g. the page added a grade via
  // the Add Grades modal or a reorder. We preserve unsaved per-cell edits
  // for grade_ids that already existed; new grade columns start empty.
  useEffect(() => {
    const next = bulkToState(bulk);
    setSavedState(next);
    setEditState((prev) => {
      const merged: MatrixState = {};
      for (const gradeId of Object.keys(next)) {
        merged[gradeId] = { ...next[gradeId], ...(prev[gradeId] ?? {}) };
      }
      return merged;
    });
  }, [bulk]);
  const [saving, setSaving] = useState(false);
  const [tooltip, setTooltip] = useState<
    | {
        competenceId: string;
        competenceTitle: string | null;
        levelId: string | null;
      }
    | null
  >(null);
  const [addDialogOpen, setAddDialogOpen] = useState(false);
  // Two-step remove for matrix rows: the icon stages the row here, the
  // ConfirmDialog at the bottom commits. Avoids dropping a whole row on
  // an accidental click during a long matrix edit session.
  const [pendingRemoveCompId, setPendingRemoveCompId] = useState<string | null>(
    null,
  );

  const currentCompetences = useMemo(
    () => competencesInState(editState, competencesPool),
    [editState, competencesPool],
  );

  const competenceTitles = useMemo(() => {
    const out = new Map<string, string>();
    for (const comp of competencesPool) out.set(comp.id, comp.title);
    return out;
  }, [competencesPool]);

  const diffCount = useMemo(() => {
    let n = 0;
    for (const grade of grades) {
      const inner = editState[grade.grade_id] ?? {};
      const base = savedState[grade.grade_id] ?? {};
      const keys = new Set([...Object.keys(inner), ...Object.keys(base)]);
      for (const key of keys) {
        if ((inner[key] ?? null) !== (base[key] ?? null)) n += 1;
      }
    }
    return n;
  }, [grades, editState, savedState]);

  const hasChanges = diffCount > 0;

  const cellIsDirty = useCallback(
    (gradeId: string, compId: string): boolean => {
      const cur = editState[gradeId]?.[compId] ?? null;
      const base = savedState[gradeId]?.[compId] ?? null;
      return cur !== base;
    },
    [editState, savedState],
  );

  const applyCascade = useCallback(
    (state: MatrixState, gradeId: string, compId: string, newLevelId: string | null): MatrixState => {
      const next: MatrixState = {};
      for (const g of grades) {
        next[g.grade_id] = { ...(state[g.grade_id] ?? {}) };
      }
      next[gradeId][compId] = newLevelId;

      if (newLevelId === null) {
        return next;
      }

      const newSort = levelSortById.get(newLevelId) ?? 0;
      const targetIdx = grades.findIndex((g) => g.grade_id === gradeId);
      if (targetIdx < 0) return next;

      // Promotion → up: bump higher grades whose level is missing or lower.
      for (let i = targetIdx + 1; i < grades.length; i += 1) {
        const gid = grades[i].grade_id;
        const cur = next[gid][compId] ?? null;
        const curSort = cur ? levelSortById.get(cur) ?? 0 : -Infinity;
        if (cur == null || curSort < newSort) {
          next[gid][compId] = newLevelId;
        }
      }
      // Demotion → down: lower grades whose level is higher → drop them.
      for (let i = targetIdx - 1; i >= 0; i -= 1) {
        const gid = grades[i].grade_id;
        const cur = next[gid][compId] ?? null;
        if (cur != null) {
          const curSort = levelSortById.get(cur) ?? 0;
          if (curSort > newSort) {
            next[gid][compId] = newLevelId;
          }
        }
      }
      return next;
    },
    [grades, levelSortById],
  );

  function handleCellChange(gradeId: string, compId: string, levelId: string | null) {
    setEditState((prev) => applyCascade(prev, gradeId, compId, levelId));
  }

  function handleAddCompetences(ids: string[]) {
    if (ids.length === 0) return;
    setEditState((prev) => {
      const next: MatrixState = {};
      for (const g of grades) {
        const inner = { ...(prev[g.grade_id] ?? {}) };
        for (const compId of ids) {
          if (!(compId in inner)) inner[compId] = null;
        }
        next[g.grade_id] = inner;
      }
      return next;
    });
  }

  function handleRemoveCompetence(compId: string) {
    setEditState((prev) => {
      const next: MatrixState = {};
      for (const g of grades) {
        const inner = { ...(prev[g.grade_id] ?? {}) };
        delete inner[compId];
        next[g.grade_id] = inner;
      }
      return next;
    });
  }

  function handleCancel() {
    setEditState(savedState);
  }

  async function handleReorderDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIdx = grades.findIndex((g) => g.grade_id === active.id);
    const newIdx = grades.findIndex((g) => g.grade_id === over.id);
    if (oldIdx < 0 || newIdx < 0) return;
    const reordered = arrayMove(grades, oldIdx, newIdx);
    // Optimistic update through the parent — keeps matrix cells in sync via
    // re-sort of `gradeMeta`.
    const optimistic = reordered.map((g, i) => ({ ...g, sort_index: i }));
    onGradesChanged(optimistic);
    try {
      const next = await specializationsApi.reorderGrades(
        specId,
        optimistic.map((g) => ({ grade_id: g.grade_id, sort_index: g.sort_index })),
      );
      onGradesChanged(next);
    } catch (err) {
      // Roll back to the parent's pre-drag state.
      onGradesChanged(gradeMeta);
      toast.error(
        err instanceof Error ? err.message : t("toastReorderGradesFailed"),
      );
    }
  }

  async function handleSave() {
    setSaving(true);
    try {
      const payload: MatrixBulkWriteGrade[] = grades.map((g) => ({
        grade_id: g.grade_id,
        links: Object.entries(editState[g.grade_id] ?? {})
          .filter(([, levelId]) => levelId != null)
          .map(([competence_id, skill_level_id]) => ({
            competence_id,
            skill_level_id: skill_level_id as string,
          })),
      }));
      const next = await specializationsApi.upsertMatrixBulk(specId, payload);
      const nextState = bulkToState(next);
      setSavedState(nextState);
      setEditState(nextState);
      onSaved(next);
      toast.success(t("toastMatrixSaved"));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toastSaveFailedShort"));
    } finally {
      setSaving(false);
    }
  }

  const currentCompetenceIds = useMemo(
    () => new Set(currentCompetences.map((c) => c.id)),
    [currentCompetences],
  );

  const pendingRemoveCompTitle = useMemo(() => {
    if (!pendingRemoveCompId) return null;
    return competenceTitles.get(pendingRemoveCompId) ?? null;
  }, [pendingRemoveCompId, competenceTitles]);

  return (
    <div className="space-y-4" data-testid="matrix-editor">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button
          data-testid="matrix-add-competence-btn"
          size="sm"
          variant="outline"
          onClick={() => setAddDialogOpen(true)}
        >
          <Plus className="mr-1 h-3.5 w-3.5" />
          {t("addCompetences")}
        </Button>
        <span className="text-xs text-muted-foreground">
          {t("matrixCounts", {
            competences: currentCompetences.length,
            grades: grades.length,
          })}
        </span>
      </div>

      {currentCompetences.length === 0 ? (
        <p
          data-testid="matrix-empty"
          className="rounded-lg border bg-muted/30 py-12 text-center text-sm text-muted-foreground"
        >
          {t("matrixEmpty")}
        </p>
      ) : grades.length === 1 ? (
        // HRP-157 REDO: with a single grade the matrix is not really a
        // matrix — it is a list of "competence → required level". The
        // previous attempt forced a 50/40/10 table-fixed layout, which
        // QA flagged as still reading like a broken table (selectors
        // marooned in the middle, delete icons floating).
        //
        // The list view here renders the grade as a section header
        // (title + salary pill + remove control) and one row per
        // competence with the canonical layout described in the QA
        // spec: flex justify-between, fixed-width selector, 32×32
        // delete button on a perfectly right-aligned axis, divide-y
        // between rows, hover row highlight, focus-visible rings.
        <SingleGradeList
          specId={specId}
          grade={grades[0]}
          highlighted={grades[0].grade_id === highlightedGradeId}
          competences={currentCompetences}
          competenceTitles={competenceTitles}
          editState={editState[grades[0].grade_id] ?? {}}
          sortedLevels={sortedLevels}
          activeSessionsMap={activeSessionsMap}
          onOpenActiveSession={onOpenActiveSession}
          saving={saving}
          onLevelChange={(compId, next) =>
            handleCellChange(grades[0].grade_id, compId, next)
          }
          cellIsDirty={(compId) => cellIsDirty(grades[0].grade_id, compId)}
          onShowIndicators={(compId, levelId) =>
            setTooltip({
              competenceId: compId,
              competenceTitle: competenceTitles.get(compId) ?? null,
              levelId,
            })
          }
          onRemoveCompetence={setPendingRemoveCompId}
          onGradeUpdated={(next) =>
            onGradesChanged(
              gradeMeta.map((x) =>
                x.grade_id === next.grade_id ? next : x,
              ),
            )
          }
          onGradeRemoved={(removedId) =>
            onGradesChanged(
              gradeMeta.filter((x) => x.grade_id !== removedId),
            )
          }
        />
      ) : (
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragEnd={handleReorderDragEnd}
        >
        <div
          className="overflow-x-auto rounded-lg border"
          data-single-grade="false"
        >
          <table
            className="w-full"
            data-testid="matrix-table"
          >
            <thead className="bg-muted/40 text-xs">
              <tr>
                <th className="sticky left-0 z-10 border-b bg-muted/40 px-3 py-2 text-left font-medium">
                  {t("competence")}
                </th>
                <SortableContext
                  items={grades.map((g) => g.grade_id)}
                  strategy={horizontalListSortingStrategy}
                >
                  {grades.map((g) => (
                    <GradeHeaderCell
                      key={g.grade_id}
                      specId={specId}
                      grade={g}
                      highlighted={g.grade_id === highlightedGradeId}
                      onGradeUpdated={(next) =>
                        onGradesChanged(
                          gradeMeta.map((x) =>
                            x.grade_id === next.grade_id ? next : x,
                          ),
                        )
                      }
                      onGradeRemoved={(removedId) =>
                        onGradesChanged(
                          gradeMeta.filter((x) => x.grade_id !== removedId),
                        )
                      }
                    />
                  ))}
                </SortableContext>
                <th
                  className="border-b px-2 py-2"
                  aria-label={t("colActionsAria")}
                />
              </tr>
            </thead>
            <tbody>
              {currentCompetences.map((comp) => {
                const compSessions =
                  activeSessionsMap?.get(
                    activeAiSessionsKey("competence_indicators", comp.id),
                  ) ?? [];
                const compIsLitUp = compSessions.length > 0;
                // Flag rows whose assigned skill levels still lack indicators
                // or development materials so reviewers can drill into the
                // competence detail page to fill the gap.
                const coverageWarning = coverageGapMessage(t, comp);
                return (
                <tr
                  key={comp.id}
                  data-testid={`matrix-row-${comp.id}`}
                  className={`border-b last:border-0 ${
                    compIsLitUp ? "bg-primary/5" : ""
                  }`}
                >
                  <td className="sticky left-0 z-10 max-w-[16rem] truncate bg-background px-3 py-2 text-sm font-medium">
                    {/* HRP-102: competence title routes to its detail page so
                        the user can add / edit indicators + materials (and
                        run AI indicator generation with the matrix context)
                        without leaving the flow. `from=matrix` lets the
                        detail page render a "Back to matrix" breadcrumb and
                        the AI launcher pick up the spec context. */}
                    <div className="flex items-center gap-2">
                      {/* HRP-157 item 3: open the competence page in a new
                          tab so the matrix editing state stays untouched
                          while the operator inspects indicators or runs AI
                          generation on the other surface. */}
                      <Link
                        href={`/competences/${comp.id}?from=matrix&specialization_id=${specId}`}
                        data-testid={`matrix-row-${comp.id}-competence-link`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-primary hover:underline min-w-0"
                      >
                        <span className="truncate">{comp.title}</span>
                        <ExternalLink className="h-3 w-3 flex-shrink-0 opacity-60" />
                      </Link>
                      {compIsLitUp && onOpenActiveSession && (
                        <ActiveAiSessionBadge
                          sessions={compSessions}
                          onOpen={onOpenActiveSession}
                          testIdSuffix={`matrix-comp-${comp.id}`}
                        />
                      )}
                      {coverageWarning && (
                        <Link
                          href={`/competences/${comp.id}?from=matrix&specialization_id=${specId}`}
                          data-testid={`matrix-row-${comp.id}-coverage-warning`}
                          target="_blank"
                          rel="noopener noreferrer"
                          aria-label={coverageWarning}
                          title={coverageWarning}
                          className="text-amber-600 hover:text-amber-700"
                        >
                          <AlertCircle className="h-4 w-4" />
                        </Link>
                      )}
                    </div>
                  </td>
                  {grades.map((g) => {
                    const levelId = editState[g.grade_id]?.[comp.id] ?? null;
                    return (
                      <td key={g.grade_id} className="px-3 py-2">
                        <MatrixCell
                          competenceId={comp.id}
                          gradeId={g.grade_id}
                          levelId={levelId}
                          skillLevels={sortedLevels}
                          isDirty={cellIsDirty(g.grade_id, comp.id)}
                          onChange={(next) => handleCellChange(g.grade_id, comp.id, next)}
                          onShowIndicators={() =>
                            setTooltip({
                              competenceId: comp.id,
                              competenceTitle: competenceTitles.get(comp.id) ?? null,
                              levelId,
                            })
                          }
                          disabled={saving}
                        />
                      </td>
                    );
                  })}
                  <td className="px-2 py-2 text-right">
                    <button
                      type="button"
                      data-testid={`matrix-row-${comp.id}-btn-remove`}
                      aria-label={t("removeCompetenceFromMatrix", {
                        competence: comp.title,
                      })}
                      title={t("removeCompetenceFromMatrixTitle")}
                      className="rounded p-1 text-muted-foreground transition hover:bg-destructive/10 hover:text-destructive disabled:opacity-50"
                      onClick={() => setPendingRemoveCompId(comp.id)}
                      disabled={saving}
                    >
                      <X className="h-4 w-4" />
                    </button>
                  </td>
                </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        </DndContext>
      )}

      <UnsavedChangesBar
        hasChanges={hasChanges}
        saving={saving}
        onSave={handleSave}
        onCancel={handleCancel}
        diffCount={diffCount}
      />

      {tooltip && (
        <IndicatorsTooltip
          competenceId={tooltip.competenceId}
          competenceTitle={tooltip.competenceTitle}
          selectedLevelId={tooltip.levelId}
          selectedLevelSortIndex={
            tooltip.levelId ? levelSortById.get(tooltip.levelId) ?? null : null
          }
          onClose={() => setTooltip(null)}
        />
      )}

      <AddCompetencesDialog
        open={addDialogOpen}
        onOpenChange={setAddDialogOpen}
        tree={competenceTree}
        alreadyInMatrix={currentCompetenceIds}
        onConfirm={handleAddCompetences}
      />

      <ConfirmDialog
        open={pendingRemoveCompId !== null}
        onOpenChange={(next) => {
          if (!next) setPendingRemoveCompId(null);
        }}
        title={t("removeCompetenceConfirmTitle")}
        description={t("removeCompetenceConfirmBody", {
          competence: pendingRemoveCompTitle ?? t("thisCompetence"),
        })}
        confirmLabel={t("remove")}
        destructive
        onConfirm={() => {
          if (pendingRemoveCompId) handleRemoveCompetence(pendingRemoveCompId);
          setPendingRemoveCompId(null);
        }}
        testId="matrix-row-remove-confirm"
      />
    </div>
  );
}
