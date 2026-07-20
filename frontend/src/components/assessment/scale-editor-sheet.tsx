"use client";

import { useEffect, useMemo, useRef, useState } from "react";
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
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical, Plus, X } from "lucide-react";
import { toast } from "sonner";

import { api } from "@/lib/api";
import type {
  AnswerScaleDetail,
  AnswerScalePayload,
} from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Sheet,
  SheetContent,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";

const MAX_OPTIONS = 10;
const MIN_OPTIONS = 2;

interface OptionDraft {
  uid: string;
  title: string;
  description: string;
}

interface LevelDraft {
  uid: string;
  percent_from: string;
  percent_to: string;
  system_title: string;
  description: string;
}

let uidCounter = 0;
function nextUid(prefix: string): string {
  uidCounter += 1;
  return `${prefix}_${Date.now()}_${uidCounter}`;
}

function emptyOption(): OptionDraft {
  return { uid: nextUid("opt"), title: "", description: "" };
}

function emptyLevel(): LevelDraft {
  return {
    uid: nextUid("lvl"),
    percent_from: "",
    percent_to: "",
    system_title: "",
    description: "",
  };
}

function levelErrors(levels: LevelDraft[]): Record<string, string> {
  const errs: Record<string, string> = {};
  if (levels.length === 0) return errs;
  const parsed = levels.map((lv) => ({
    uid: lv.uid,
    from: Number(lv.percent_from),
    to: Number(lv.percent_to),
  }));
  for (const p of parsed) {
    if (
      Number.isNaN(p.from) ||
      Number.isNaN(p.to) ||
      p.from < 0 ||
      p.from > 100 ||
      p.to < 0 ||
      p.to > 100
    ) {
      errs[p.uid] = "Value must be between 0 and 100";
      continue;
    }
    if (p.from > p.to) {
      errs[p.uid] = "From cannot exceed To";
    }
  }
  const sorted = [...parsed]
    .filter((p) => !errs[p.uid])
    .sort((a, b) => a.from - b.from);
  if (sorted.length > 0) {
    if (sorted[0].from !== 0) {
      errs[sorted[0].uid] = errs[sorted[0].uid] ?? "First level must start at 0";
    }
    if (sorted[sorted.length - 1].to !== 100) {
      const last = sorted[sorted.length - 1];
      errs[last.uid] = errs[last.uid] ?? "Last level must end at 100";
    }
    for (let i = 0; i + 1 < sorted.length; i += 1) {
      const cur = sorted[i];
      const nxt = sorted[i + 1];
      if (nxt.from !== cur.to + 1) {
        errs[nxt.uid] = errs[nxt.uid] ?? "Overlap or gap with the previous level";
      }
    }
  }
  return errs;
}

interface SortableOptionProps {
  option: OptionDraft;
  index: number;
  canRemove: boolean;
  onChange: (uid: string, patch: Partial<OptionDraft>) => void;
  onRemove: (uid: string) => void;
}

function SortableOption({
  option,
  index,
  canRemove,
  onChange,
  onRemove,
}: SortableOptionProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: option.uid });

  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : undefined,
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      data-testid={`scale-editor-option-row-${index}`}
      className="flex items-start gap-2 rounded-md border bg-background p-2"
    >
      <button
        type="button"
        className="mt-1 cursor-grab text-muted-foreground"
        {...attributes}
        {...listeners}
        aria-label="Drag to reorder"
      >
        <GripVertical className="size-4" />
      </button>
      <div className="flex flex-1 flex-col gap-1.5">
        <Input
          placeholder="Option title"
          value={option.title}
          onChange={(e) => onChange(option.uid, { title: e.target.value })}
          data-testid={`scale-editor-option-row-${index}-input-title`}
        />
        <Input
          placeholder="Description (optional)"
          value={option.description}
          onChange={(e) =>
            onChange(option.uid, { description: e.target.value })
          }
          data-testid={`scale-editor-option-row-${index}-input-description`}
        />
      </div>
      <div className="flex flex-col items-end gap-1">
        <span className="text-xs text-muted-foreground">Score: {index}</span>
        <Button
          variant="ghost"
          size="icon-sm"
          disabled={!canRemove}
          onClick={() => onRemove(option.uid)}
          data-testid={`scale-editor-option-row-${index}-btn-remove`}
        >
          <X className="size-3.5" />
        </Button>
      </div>
    </div>
  );
}

export interface ScaleEditorSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  mode: "create" | "edit";
  initial?: AnswerScaleDetail | null;
  onSaved: (scale: AnswerScaleDetail) => void;
}

interface ScaleEditorBodyProps {
  mode: "create" | "edit";
  initial?: AnswerScaleDetail | null;
  onClose: () => void;
  onSaved: (scale: AnswerScaleDetail) => void;
  dirtyRef: React.MutableRefObject<boolean>;
  onRequestCancel: () => void;
}

function ScaleEditorBody({
  mode,
  initial,
  onClose,
  onSaved,
  dirtyRef,
  onRequestCancel,
}: ScaleEditorBodyProps) {
  const [title, setTitle] = useState(initial?.title ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [options, setOptions] = useState<OptionDraft[]>(() => {
    if (initial) {
      return initial.options
        .filter((o) => !o.is_neutral)
        .sort((a, b) => a.sort_index - b.sort_index)
        .map((o) => ({
          uid: nextUid("opt"),
          title: o.title,
          description: o.description ?? "",
        }));
    }
    return [emptyOption(), emptyOption()];
  });
  const [neutralEnabled, setNeutralEnabled] = useState<boolean>(
    initial?.options.some((o) => o.is_neutral) ?? false,
  );
  const [neutralTitle, setNeutralTitle] = useState<string>(() => {
    const n = initial?.options.find((o) => o.is_neutral);
    return n?.title ?? "Don't know";
  });
  const [levels, setLevels] = useState<LevelDraft[]>(() => {
    if (initial && initial.levels.length > 0) {
      return [...initial.levels]
        .sort((a, b) => a.sort_index - b.sort_index)
        .map((lv) => ({
          uid: nextUid("lvl"),
          percent_from: String(lv.percent_from),
          percent_to: String(lv.percent_to),
          // Origin/seeded levels (system_code set, system_title null) are
          // not editable by tenants; the editor only opens for custom
          // scales, where system_title is always populated. Coerce null →
          // "" defensively in case a future flow ever loads a seeded row.
          system_title: lv.system_title ?? "",
          description: lv.description ?? "",
        }));
    }
    return [];
  });

  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [confirmSaveOpen, setConfirmSaveOpen] = useState(false);
  const initialMount = useRef(true);

  useEffect(() => {
    if (initialMount.current) {
      initialMount.current = false;
      return;
    }
    setDirty(true);
    dirtyRef.current = true;
  }, [title, description, options, neutralEnabled, neutralTitle, levels, dirtyRef]);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const lvlErrs = useMemo(() => levelErrors(levels), [levels]);
  const hasLevelErrors = Object.keys(lvlErrs).length > 0;

  const optionsValid = options.length >= MIN_OPTIONS &&
    options.length <= MAX_OPTIONS &&
    options.every((o) => o.title.trim().length > 0);

  const levelsValid = levels.length === 0 ||
    (levels.every(
      (lv) => lv.system_title.trim().length > 0,
    ) && !hasLevelErrors);

  const canSave = title.trim().length > 0 && optionsValid && levelsValid;

  function attemptClose() {
    if (dirty) {
      onRequestCancel();
    } else {
      onClose();
    }
  }

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (over && active.id !== over.id) {
      setOptions((items) => {
        const oldIndex = items.findIndex((i) => i.uid === active.id);
        const newIndex = items.findIndex((i) => i.uid === over.id);
        return arrayMove(items, oldIndex, newIndex);
      });
    }
  }

  function updateOption(uid: string, patch: Partial<OptionDraft>) {
    setOptions((items) =>
      items.map((it) => (it.uid === uid ? { ...it, ...patch } : it)),
    );
  }

  function removeOption(uid: string) {
    setOptions((items) =>
      items.length > MIN_OPTIONS ? items.filter((it) => it.uid !== uid) : items,
    );
  }

  function addOption() {
    setOptions((items) =>
      items.length < MAX_OPTIONS ? [...items, emptyOption()] : items,
    );
  }

  function updateLevel(uid: string, patch: Partial<LevelDraft>) {
    setLevels((items) =>
      items.map((it) => (it.uid === uid ? { ...it, ...patch } : it)),
    );
  }

  function removeLevel(uid: string) {
    setLevels((items) => items.filter((it) => it.uid !== uid));
  }

  function addLevel() {
    setLevels((items) => [...items, emptyLevel()]);
  }

  function buildPayload(): AnswerScalePayload {
    const optsPayload = options.map((o, idx) => ({
      title: o.title.trim(),
      description: o.description.trim() || null,
      sort_index: idx,
      is_neutral: false,
    }));
    if (neutralEnabled) {
      optsPayload.push({
        title: neutralTitle.trim() || "Don't know",
        description: null,
        sort_index: optsPayload.length,
        is_neutral: true,
      });
    }
    const levelsPayload = levels.map((lv, idx) => ({
      percent_from: Number(lv.percent_from),
      percent_to: Number(lv.percent_to),
      system_title: lv.system_title.trim(),
      description: lv.description.trim() || null,
      sort_index: idx,
    }));
    return {
      title: title.trim(),
      description: description.trim() || null,
      options: optsPayload,
      levels: levelsPayload,
    };
  }

  async function performSave() {
    setSaving(true);
    try {
      const payload = buildPayload();
      const saved = mode === "create"
        ? await api.post<AnswerScaleDetail>("/answer-scales", payload)
        : await api.put<AnswerScaleDetail>(
            `/answer-scales/${initial!.id}`,
            payload,
          );
      toast.success(
        mode === "create" ? "Scale created" : "Scale updated",
      );
      onSaved(saved);
      setDirty(false);
      onClose();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to save scale",
      );
    } finally {
      setSaving(false);
    }
  }

  function attemptSave() {
    if (mode === "edit") {
      setConfirmSaveOpen(true);
    } else {
      void performSave();
    }
  }

  return (
    <>
      <SheetContent
        className="max-w-2xl"
        data-testid="scale-editor-sheet"
      >
        <SheetHeader>
          <SheetTitle>
            {mode === "create" ? "Create scale" : "Edit scale"}
          </SheetTitle>
        </SheetHeader>

        <div className="flex-1 space-y-5 overflow-y-auto pr-1">
          <div className="space-y-1.5">
            <Label htmlFor="scale-title">Title</Label>
            <Input
              id="scale-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              data-testid="scale-editor-input-title"
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="scale-description">Description</Label>
            <Textarea
              id="scale-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              data-testid="scale-editor-input-description"
            />
          </div>

          <section className="space-y-2">
            <div className="flex items-center justify-between">
              <Label>Scale levels</Label>
              <Button
                size="xs"
                variant="outline"
                onClick={addLevel}
                data-testid="scale-editor-levels-btn-add"
              >
                <Plus className="mr-1 size-3" />
                Add level
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              Levels must cover the 0–100% range without overlaps or gaps.
              Adjacent intervals are separated by 1% (e.g. 0–50 and
              51–100).
            </p>
            {levels.length === 0 ? (
              <p className="rounded-md border border-dashed py-3 text-center text-xs text-muted-foreground">
                No levels defined — results will be shown as percentages only.
              </p>
            ) : (
              <div
                className="space-y-1.5"
                data-testid="scale-editor-levels-table"
              >
                {levels.map((lv, idx) => (
                  <div
                    key={lv.uid}
                    data-testid={`scale-editor-level-row-${idx}`}
                    className="space-y-1.5 rounded-md border p-2"
                  >
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Input
                        type="number"
                        min={0}
                        max={100}
                        placeholder="From"
                        className="w-20"
                        value={lv.percent_from}
                        onChange={(e) =>
                          updateLevel(lv.uid, { percent_from: e.target.value })
                        }
                        data-testid={`scale-editor-level-row-${idx}-input-from`}
                      />
                      <span className="text-xs text-muted-foreground">–</span>
                      <Input
                        type="number"
                        min={0}
                        max={100}
                        placeholder="To"
                        className="w-20"
                        value={lv.percent_to}
                        onChange={(e) =>
                          updateLevel(lv.uid, { percent_to: e.target.value })
                        }
                        data-testid={`scale-editor-level-row-${idx}-input-to`}
                      />
                      <Input
                        placeholder="Level title"
                        className="flex-1 min-w-40"
                        value={lv.system_title}
                        onChange={(e) =>
                          updateLevel(lv.uid, {
                            system_title: e.target.value,
                          })
                        }
                        data-testid={`scale-editor-level-row-${idx}-input-title`}
                      />
                      <Button
                        size="icon-sm"
                        variant="ghost"
                        onClick={() => removeLevel(lv.uid)}
                        data-testid={`scale-editor-level-row-${idx}-btn-remove`}
                      >
                        <X className="size-3.5" />
                      </Button>
                    </div>
                    <Input
                      placeholder="Level description (optional)"
                      value={lv.description}
                      onChange={(e) =>
                        updateLevel(lv.uid, { description: e.target.value })
                      }
                      data-testid={`scale-editor-level-row-${idx}-input-description`}
                    />
                    {lvlErrs[lv.uid] && (
                      <p className="text-xs text-destructive">
                        {lvlErrs[lv.uid]}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className="space-y-2">
            <div className="flex items-center justify-between">
              <Label>Answer options</Label>
              <Button
                size="xs"
                variant="outline"
                onClick={addOption}
                disabled={options.length >= MAX_OPTIONS}
                data-testid="scale-editor-options-btn-add"
              >
                <Plus className="mr-1 size-3" />
                Add option
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              Score is assigned by position (0 — lowest). Drag options to
              reorder.
            </p>
            <DndContext
              sensors={sensors}
              collisionDetection={closestCenter}
              onDragEnd={handleDragEnd}
            >
              <SortableContext
                items={options.map((o) => o.uid)}
                strategy={verticalListSortingStrategy}
              >
                <div
                  className="space-y-1.5"
                  data-testid="scale-editor-options-list"
                >
                  {options.map((opt, idx) => (
                    <SortableOption
                      key={opt.uid}
                      option={opt}
                      index={idx}
                      canRemove={options.length > MIN_OPTIONS}
                      onChange={updateOption}
                      onRemove={removeOption}
                    />
                  ))}
                </div>
              </SortableContext>
            </DndContext>

            <label
              className="mt-2 flex items-center gap-2 text-sm"
              data-testid="scale-editor-checkbox-neutral"
            >
              <Checkbox
                checked={neutralEnabled}
                onCheckedChange={(c) => setNeutralEnabled(c === true)}
              />
              <span>Add a &quot;Don&apos;t know&quot; option (excluded from score)</span>
            </label>
            {neutralEnabled && (
              <Input
                value={neutralTitle}
                onChange={(e) => setNeutralTitle(e.target.value)}
                placeholder="Option title"
                className="ml-6 max-w-xs"
              />
            )}
          </section>
        </div>

        <SheetFooter>
          <Button
            variant="outline"
            onClick={attemptClose}
            disabled={saving}
            data-testid="scale-editor-btn-cancel"
          >
            Cancel
          </Button>
          <Button
            onClick={attemptSave}
            disabled={!canSave || saving}
            data-testid="scale-editor-btn-save"
          >
            {saving ? "Saving…" : "Save"}
          </Button>
        </SheetFooter>
      </SheetContent>

      <ConfirmDialog
        open={confirmSaveOpen}
        onOpenChange={setConfirmSaveOpen}
        title="Save changes?"
        description="The changes will be applied to every draft assessment that uses this scale."
        confirmLabel="Save"
        onConfirm={performSave}
        testId="scale-confirm-save"
      />
    </>
  );
}

export function ScaleEditorSheet({
  open,
  onOpenChange,
  mode,
  initial,
  onSaved,
}: ScaleEditorSheetProps) {
  const dirtyRef = useRef(false);
  const [confirmCancelOpen, setConfirmCancelOpen] = useState(false);

  function handleOpenChange(next: boolean) {
    if (!next && dirtyRef.current) {
      setConfirmCancelOpen(true);
      return;
    }
    onOpenChange(next);
  }

  function forceClose() {
    dirtyRef.current = false;
    onOpenChange(false);
  }

  useEffect(() => {
    if (!open) {
      dirtyRef.current = false;
    }
  }, [open]);

  return (
    <>
      <Sheet open={open} onOpenChange={handleOpenChange}>
        {open && (
          <ScaleEditorBody
            mode={mode}
            initial={initial}
            onClose={() => onOpenChange(false)}
            onSaved={onSaved}
            dirtyRef={dirtyRef}
            onRequestCancel={() => setConfirmCancelOpen(true)}
          />
        )}
      </Sheet>
      <ConfirmDialog
        open={confirmCancelOpen}
        onOpenChange={setConfirmCancelOpen}
        title="Discard changes?"
        description="Are you sure you want to discard your edits?"
        confirmLabel="Discard"
        onConfirm={forceClose}
        testId="scale-confirm-cancel"
      />
    </>
  );
}
