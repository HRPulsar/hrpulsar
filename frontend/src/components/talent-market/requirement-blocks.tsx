"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { api } from "@/lib/api";
import {
  type RequiredCompetenceBulkPayload,
  talentMarketApi,
} from "@/lib/api/talent-market";
import type { SpecializationGrade } from "@/lib/api/specializations";
import type {
  Competence,
  CompetenceGroupTree,
  DictionaryItem,
  SkillLevel,
  TalentCardDetail,
  TalentRequiredSpecialization,
} from "@/lib/types";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { CompetenceTreePicker } from "@/components/competence/competence-tree-picker";

// ---------------------------------------------------------------------------
// Required Specialization
// ---------------------------------------------------------------------------

interface SpecForm {
  specialization_id: string;
  grade_id: string;
  min_experience_years: string; // raw input value
}

const EMPTY_SPEC_FORM: SpecForm = {
  specialization_id: "",
  grade_id: "",
  min_experience_years: "",
};

export interface RequiredSpecializationsBlockProps {
  card: TalentCardDetail;
  specializations: DictionaryItem[];
  grades: DictionaryItem[];
  readOnly?: boolean;
  onChanged: () => Promise<void> | void;
}

export function RequiredSpecializationsBlock({
  card,
  specializations,
  grades,
  readOnly = false,
  onChanged,
}: RequiredSpecializationsBlockProps) {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<TalentRequiredSpecialization | null>(
    null,
  );
  const [form, setForm] = useState<SpecForm>(EMPTY_SPEC_FORM);
  const [saving, setSaving] = useState(false);
  const [gradeOptions, setGradeOptions] = useState<SpecializationGrade[]>([]);
  const [loadingGrades, setLoadingGrades] = useState(false);
  const [deleting, setDeleting] = useState<TalentRequiredSpecialization | null>(
    null,
  );
  const [removing, setRemoving] = useState(false);
  // HRP-171: warn-before-mutate dialog. Adding a 2nd+ specialization, or
  // editing any existing one, recomputes the auto-filled Required
  // Competences block — recruiters need to confirm because their previous
  // tweaks to that block disappear.
  const [pendingSpecConfirm, setPendingSpecConfirm] = useState(false);

  const specTitle = useCallback(
    (id: string) => specializations.find((s) => s.id === id)?.title ?? "—",
    [specializations],
  );
  const gradeTitle = useCallback(
    (id: string | null) =>
      id ? (grades.find((g) => g.id === id)?.title ?? "—") : "—",
    [grades],
  );

  // Pull the spec → grades mapping from the configured ladder. Falls back to
  // the raw dictionary when the spec has no grade configuration (cold-start)
  // so the dialog isn't dead on arrival.
  useEffect(() => {
    let cancelled = false;
    if (!form.specialization_id) {
      setGradeOptions([]);
      return;
    }
    setLoadingGrades(true);
    api
      .get<SpecializationGrade[]>(
        `/specializations/${form.specialization_id}/grades`,
      )
      .then((rows) => {
        if (cancelled) return;
        setGradeOptions(rows ?? []);
      })
      .catch(() => {
        if (cancelled) return;
        setGradeOptions([]);
      })
      .finally(() => {
        if (!cancelled) setLoadingGrades(false);
      });
    return () => {
      cancelled = true;
    };
  }, [form.specialization_id]);

  function openCreate() {
    setEditing(null);
    setForm(EMPTY_SPEC_FORM);
    setDialogOpen(true);
  }

  function openEdit(row: TalentRequiredSpecialization) {
    setEditing(row);
    setForm({
      specialization_id: row.specialization_id,
      grade_id: row.grade_id ?? "",
      min_experience_years:
        row.min_experience_years != null
          ? String(row.min_experience_years)
          : "",
    });
    setDialogOpen(true);
  }

  function submit() {
    if (!form.specialization_id || !form.grade_id) {
      toast.error("Specialization and Grade are required");
      return;
    }
    // HRP-171: warn before mutating Required specializations on a
    // non-empty block. Cold-start (first spec added) goes straight
    // through — there are no competences to invalidate yet.
    const itemsCount = card.specializations?.length ?? 0;
    const needsWarn = editing !== null || itemsCount > 0;
    if (needsWarn) {
      setPendingSpecConfirm(true);
      return;
    }
    void runSubmit();
  }

  async function runSubmit() {
    setSaving(true);
    try {
      const payload = {
        specialization_id: form.specialization_id,
        grade_id: form.grade_id,
        min_experience_years: form.min_experience_years
          ? Number(form.min_experience_years)
          : null,
      };
      if (editing) {
        await talentMarketApi.updateRequiredSpecialization(
          card.id,
          editing.id,
          payload,
        );
      } else {
        await talentMarketApi.addRequiredSpecialization(card.id, payload);
      }
      toast.success(editing ? "Specialization updated" : "Specialization added");
      setPendingSpecConfirm(false);
      setDialogOpen(false);
      await onChanged();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed");
    } finally {
      setSaving(false);
    }
  }

  async function confirmRemove() {
    if (!deleting) return;
    setRemoving(true);
    try {
      await talentMarketApi.deleteRequiredSpecialization(card.id, deleting.id);
      setDeleting(null);
      await onChanged();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed");
    } finally {
      setRemoving(false);
    }
  }

  const items = card.specializations ?? [];

  // HRP-292: drop grades deactivated on the Dictionaries level
  // (tenant-effective flag from the ladder API), keeping the row's saved
  // grade selectable so an edited row doesn't lose its stored selection.
  const visibleGrades = gradeOptions.filter(
    (g) => g.grade_is_active || g.grade_id === form.grade_id,
  );

  return (
    <Card data-testid="talent-card-required-specs">
      <CardHeader className="flex-row items-center justify-between">
        {/* HRP-171: title is plural — recruiters can attach more than one
            spec, and adding/editing/removing any of them recomputes the
            Required Competencies block. */}
        <CardTitle className="text-base">Required specializations</CardTitle>
        {!readOnly && (
          <Button
            size="sm"
            variant="outline"
            onClick={openCreate}
            data-testid="talent-card-required-specs-btn-add"
          >
            <Plus className="mr-1 h-4 w-4" />
            Add
          </Button>
        )}
      </CardHeader>
      <CardContent>
        {items.length === 0 ? (
          <p className="py-4 text-center text-sm text-muted-foreground">
            No required specializations
          </p>
        ) : (
          <div className="space-y-2">
            {items.map((row) => (
              <div
                key={row.id}
                data-testid={`talent-card-required-spec-${row.id}`}
                className="flex items-center gap-3 rounded-md border p-3 text-sm"
              >
                <div className="flex-1">
                  <div className="font-medium">
                    {specTitle(row.specialization_id)}
                    <span className="ml-2 text-muted-foreground">
                      · {gradeTitle(row.grade_id)}
                    </span>
                  </div>
                  {/* HRP-127: 0 means "no floor"; render only positive years. */}
                  {row.min_experience_years != null &&
                    row.min_experience_years > 0 && (
                      <div className="text-xs text-muted-foreground">
                        Min. experience: {row.min_experience_years} year(s)
                      </div>
                    )}
                </div>
                {!readOnly && (
                  <div className="flex shrink-0 items-center gap-1">
                    <Button
                      size="icon-sm"
                      variant="ghost"
                      onClick={() => openEdit(row)}
                      data-testid={`talent-card-required-spec-${row.id}-btn-edit`}
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </Button>
                    <Button
                      size="icon-sm"
                      variant="ghost"
                      onClick={() => setDeleting(row)}
                      data-testid={`talent-card-required-spec-${row.id}-btn-delete`}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </CardContent>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent data-testid="talent-card-required-spec-dialog">
          <DialogHeader>
            <DialogTitle>
              {editing ? "Edit required specialization" : "Add required specialization"}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label>Specialization</Label>
              <Select
                value={form.specialization_id}
                onValueChange={(v) =>
                  setForm({ ...form, specialization_id: v, grade_id: "" })
                }
              >
                <SelectTrigger
                  data-testid="talent-card-required-spec-dialog-select-spec"
                  className="w-full"
                >
                  <SelectValue placeholder="Pick a specialization">
                    {(value) =>
                      specializations.find((s) => s.id === value)?.title ??
                      "Pick a specialization"
                    }
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {/* HRP-292: active items only, plus the row's saved
                      specialization so an edited row doesn't lose its
                      (now deactivated) stored selection. */}
                  {specializations
                    .filter(
                      (s) => s.is_active || s.id === form.specialization_id,
                    )
                    .map((s) => (
                      <SelectItem key={s.id} value={s.id}>
                        {s.title}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label>Grade</Label>
              <Select
                value={form.grade_id}
                onValueChange={(v) => setForm({ ...form, grade_id: v })}
                disabled={!form.specialization_id || loadingGrades}
              >
                <SelectTrigger
                  data-testid="talent-card-required-spec-dialog-select-grade"
                  className="w-full"
                >
                  <SelectValue
                    placeholder={
                      loadingGrades
                        ? "Loading grades…"
                        : "Pick a grade for the specialization"
                    }
                  >
                    {(value) =>
                      gradeOptions.find((g) => g.grade_id === value)?.grade_title ??
                      "Pick a grade"
                    }
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {visibleGrades.map((g) => (
                    <SelectItem key={g.grade_id} value={g.grade_id}>
                      {g.grade_title}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {form.specialization_id && !loadingGrades && visibleGrades.length === 0 && (
                <p className="text-xs text-amber-600">
                  No grades configured for this specialization. Set them up on
                  the specialization page first.
                </p>
              )}
            </div>
            <div className="space-y-1.5">
              <Label>Min. experience (years, optional)</Label>
              <Input
                type="number"
                min={0}
                value={form.min_experience_years}
                onChange={(e) =>
                  setForm({ ...form, min_experience_years: e.target.value })
                }
                data-testid="talent-card-required-spec-dialog-input-experience"
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDialogOpen(false)}
              disabled={saving}
            >
              Cancel
            </Button>
            <Button
              onClick={submit}
              disabled={saving || !form.specialization_id || !form.grade_id}
              data-testid="talent-card-required-spec-dialog-btn-save"
            >
              {saving ? "Saving…" : editing ? "Save" : "Add"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* HRP-127 + HRP-171: deleting recomputes the auto-filled Required
        Competences block, so the confirm message names the side-effect. */}
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(o) => !o && setDeleting(null)}
        title="Delete required specialization"
        description={
          deleting
            ? `Remove ${specTitle(deleting.specialization_id)} · ${gradeTitle(
                deleting.grade_id,
              )}? Required competencies will be recomputed without this row. This action cannot be undone.`
            : ""
        }
        onConfirm={confirmRemove}
        loading={removing}
      />

      {/* HRP-171: add-second / edit warning before the API call.
        Required competencies on the card are auto-derived from the
        spec(s) on save — recruiters need to confirm because any manual
        tweaks they made disappear in the recompute. */}
      <ConfirmDialog
        open={pendingSpecConfirm}
        onOpenChange={(o) => !o && setPendingSpecConfirm(false)}
        title={editing ? "Edit required specialization" : "Add required specialization"}
        description="Required competencies will be recomputed based on the updated Required specializations. Continue?"
        confirmLabel="Continue"
        loadingLabel="Saving..."
        confirmVariant="default"
        onConfirm={runSubmit}
        loading={saving}
      />
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Required Competence (HRP-128: 2-step Change/Add dialog)
// ---------------------------------------------------------------------------

interface CompPickedRow {
  competence_id: string;
  competence_title: string;
  skill_level_id: string;
}

export interface RequiredCompetencesBlockProps {
  card: TalentCardDetail;
  tree: CompetenceGroupTree[];
  skillLevels: SkillLevel[];
  competenceById: Map<string, Competence>;
  readOnly?: boolean;
  onChanged: () => Promise<void> | void;
}

export function RequiredCompetencesBlock({
  card,
  tree,
  skillLevels,
  competenceById,
  readOnly = false,
  onChanged,
}: RequiredCompetencesBlockProps) {
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState<1 | 2>(1);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [pickedRows, setPickedRows] = useState<CompPickedRow[]>([]);
  const [saving, setSaving] = useState(false);

  const orderedLevels = useMemo(
    () => [...skillLevels].sort((a, b) => a.sort_index - b.sort_index),
    [skillLevels],
  );

  const items = card.competences ?? [];
  // HRP-128: Add when the block is empty, Change once at least one row exists.
  const hasItems = items.length > 0;

  function openDialog() {
    // Pre-fill from the existing selection so unchecking a row in step 1
    // *removes* it on save (replace semantics on the backend).
    const initialIds = new Set(items.map((it) => it.competence_id));
    setSelectedIds(initialIds);
    setPickedRows(
      items.map((it) => {
        const c = competenceById.get(it.competence_id);
        return {
          competence_id: it.competence_id,
          competence_title: c?.title ?? "—",
          skill_level_id: it.skill_level_id ?? "",
        };
      }),
    );
    setStep(1);
    setOpen(true);
  }

  function proceedToStep2() {
    // Preserve skill levels already chosen for competences that survive
    // a back-and-forth through step 1; reset only the rows that are new
    // to the selection.
    const prevLevels = new Map(
      pickedRows.map((r) => [r.competence_id, r.skill_level_id]),
    );
    const rows: CompPickedRow[] = [];
    for (const id of selectedIds) {
      const c = competenceById.get(id);
      if (!c) continue;
      rows.push({
        competence_id: id,
        competence_title: c.title,
        skill_level_id: prevLevels.get(id) ?? "",
      });
    }
    setPickedRows(rows);
    setStep(2);
  }

  function setRowLevel(competenceId: string, skillLevelId: string) {
    setPickedRows((rows) =>
      rows.map((r) =>
        r.competence_id === competenceId
          ? { ...r, skill_level_id: skillLevelId }
          : r,
      ),
    );
  }

  const step2Ready =
    pickedRows.length > 0 && pickedRows.every((r) => r.skill_level_id);

  async function submit() {
    setSaving(true);
    try {
      const body: RequiredCompetenceBulkPayload = {
        items: pickedRows.map((r) => ({
          competence_id: r.competence_id,
          skill_level_id: r.skill_level_id,
        })),
      };
      await talentMarketApi.addRequiredCompetences(card.id, body);
      toast.success("Required competences saved");
      setOpen(false);
      await onChanged();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card data-testid="talent-card-required-competences">
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle className="text-base">Required competencies</CardTitle>
        {!readOnly && (
          <Button
            size="sm"
            variant="outline"
            onClick={openDialog}
            data-testid={
              hasItems
                ? "talent-card-required-competences-btn-change"
                : "talent-card-required-competences-btn-add"
            }
          >
            {hasItems ? (
              <Pencil className="mr-1 h-4 w-4" />
            ) : (
              <Plus className="mr-1 h-4 w-4" />
            )}
            {hasItems ? "Change" : "Add"}
          </Button>
        )}
      </CardHeader>
      <CardContent>
        {items.length === 0 ? (
          <p className="py-4 text-center text-sm text-muted-foreground">
            No required competences
          </p>
        ) : (
          <div
            className="flex flex-wrap gap-1.5"
            data-testid="talent-card-required-competences-list"
          >
            {items.map((row) => {
              const comp = competenceById.get(row.competence_id);
              const lv = skillLevels.find((l) => l.id === row.skill_level_id);
              return (
                <Badge
                  key={row.id}
                  variant="secondary"
                  data-testid={`talent-card-required-competence-${row.id}`}
                >
                  {comp?.title ?? "—"}
                  {lv && (
                    <span className="ml-1 text-muted-foreground">
                      · {lv.title}
                    </span>
                  )}
                </Badge>
              );
            })}
          </div>
        )}
      </CardContent>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent
          data-testid="talent-card-required-competences-dialog"
          className="max-h-[80vh] overflow-y-auto sm:max-w-xl"
        >
          <DialogHeader>
            <DialogTitle>
              {hasItems
                ? "Change required competences"
                : "Add required competences"}
              {" — "}step {step} of 2
            </DialogTitle>
          </DialogHeader>

          {step === 1 && (
            <div
              className="space-y-2"
              data-testid="talent-card-required-competences-step-1"
            >
              <CompetenceTreePicker
                tree={tree}
                selectedIds={selectedIds}
                onChange={setSelectedIds}
                testIdPrefix="talent-card-required-competences-step-1"
              />
            </div>
          )}

          {step === 2 && (
            <div
              className="space-y-2"
              data-testid="talent-card-required-competences-step-2"
            >
              {pickedRows.map((row) => (
                <div
                  key={row.competence_id}
                  className="flex items-center gap-3 rounded-md border p-2 text-sm"
                >
                  <div className="flex-1 truncate">{row.competence_title}</div>
                  <Select
                    value={row.skill_level_id}
                    onValueChange={(v) => setRowLevel(row.competence_id, v)}
                  >
                    <SelectTrigger
                      className="w-40"
                      data-testid={`talent-card-required-competences-step-2-${row.competence_id}`}
                    >
                      <SelectValue placeholder="Level">
                        {(value) =>
                          orderedLevels.find((lv) => lv.id === value)?.title ??
                          "Level"
                        }
                      </SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                      {orderedLevels.map((lv) => (
                        <SelectItem key={lv.id} value={lv.id}>
                          {lv.title}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              ))}
            </div>
          )}

          <DialogFooter className="flex flex-row items-center justify-between gap-2">
            <Button
              variant="ghost"
              onClick={() => (step === 1 ? setOpen(false) : setStep(1))}
              disabled={saving}
            >
              {step === 1 ? "Cancel" : "Back"}
            </Button>
            {step === 1 && (
              <Button
                onClick={proceedToStep2}
                disabled={selectedIds.size === 0}
                data-testid="talent-card-required-competences-btn-next-1"
              >
                Next
              </Button>
            )}
            {step === 2 && (
              <Button
                onClick={submit}
                disabled={!step2Ready || saving}
                data-testid="talent-card-required-competences-btn-save"
              >
                {saving ? "Saving…" : "Save"}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
