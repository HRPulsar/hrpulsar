"use client";

// HRP-756: the Steps tab of a work container — a flat, draggable list of
// steps with inline edits of title, description, the S1-S4 attributes and
// the capability chips. Every edit is saved on its own (PATCH / PUT) and
// the backend flips the step to `tenant_edited`; "Accept all" closes the
// breakdown. The word "primitive" never reaches the screen: chips show
// reference.primitive.{key}.label.

import { useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { Check, GripVertical, Plus, Sparkles, Trash2, X } from "lucide-react";
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

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { ConfirmDialog } from "@/components/confirm-dialog";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  HOURS_PER_RUN_MIN,
  HoursFields,
  draftOf,
  hoursOutOfRange,
  parseHours,
} from "@/components/coverage/hours-fields";
import { BADGE_COLOR } from "@/lib/badge-tones";
import { EECreditCostBadge } from "@/lib/ee-hooks";
import {
  HOURS_PER_RUN_MAX,
  RECLASSIFY_ACTION,
  RUNS_PER_YEAR_MAX,
  isTentative,
  type OutputType,
  type Primitive,
  type Responsibility,
  type Reversibility,
  type StepCapability,
  type StepPatch,
  type StepState,
  type WorkStep,
  workApi,
} from "@/lib/api/work";

const RESPONSIBILITIES: Responsibility[] = ["none", "reputational", "formal", "regulatory"];
const REVERSIBILITIES: Reversibility[] = ["reversible", "costly", "irreversible"];
const OUTPUT_TYPES: OutputType[] = ["draft", "external_change"];
const UNSET = "__unset__";

const STATE_COLOR: Record<StepState, string> = {
  system_suggested: BADGE_COLOR.blue,
  tenant_edited: BADGE_COLOR.neutral,
  accepted: BADGE_COLOR.green,
};

type Translate = (key: string, values?: Record<string, string | number>) => string;
type StepsUpdater = (prev: WorkStep[]) => WorkStep[];

/** The reorder response carries the whole list, and writing it back drops
 * the answer of a PATCH that landed while the reorder was in flight. Take
 * the order and the positions from the server, every other field from the
 * row the state already holds. */
export function mergeReordered(prev: WorkStep[], fresh: WorkStep[]): WorkStep[] {
  const byId = new Map(prev.map((s) => [s.id, s]));
  return fresh.map((row) => {
    const local = byId.get(row.id);
    return local ? { ...local, position: row.position } : row;
  });
}

interface StepsEditorProps {
  containerId: string;
  steps: WorkStep[];
  primitives: Primitive[];
  canEdit: boolean;
  canAccept: boolean;
  /** Functional updates only: two rows saving at once must not lose each
   * other's response. */
  onStepsChange: (updater: StepsUpdater) => void;
  onAccepted: () => void;
}

export function StepsEditor({
  containerId,
  steps,
  primitives,
  canEdit,
  canAccept,
  onStepsChange,
  onAccepted,
}: StepsEditorProps) {
  const t = useTranslations("coverage");
  const tRef = useTranslations("reference");
  const [newTitle, setNewTitle] = useState("");
  const [adding, setAdding] = useState(false);
  const [accepting, setAccepting] = useState(false);
  const labelOf = useMemo(() => {
    const byCode = new Map(primitives.map((p) => [p.code, p.i18n_key]));
    return (code: string) => {
      const key = byCode.get(code);
      return key ? tRef(`primitive.${key}.label`) : code;
    };
  }, [primitives, tRef]);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  function replace(updated: WorkStep) {
    onStepsChange((prev) => prev.map((s) => (s.id === updated.id ? updated : s)));
  }

  async function handleDragEnd(e: DragEndEvent) {
    const overId = e.over ? String(e.over.id) : null;
    if (!overId || overId === String(e.active.id)) return;
    const from = steps.findIndex((s) => s.id === e.active.id);
    const to = steps.findIndex((s) => s.id === overId);
    if (from < 0 || to < 0) return;
    const order = arrayMove(steps, from, to).map((s) => s.id);
    const beforeOrder = steps.map((s) => s.id);
    // Reorders the rows the state already holds instead of writing this
    // snapshot back: a row saving at the same time keeps its response, both
    // on the optimistic write and on the rollback.
    const applyOrder = (ids: string[]) => (prev: WorkStep[]) => {
      const byId = new Map(prev.map((s) => [s.id, s]));
      const next = ids.map((id) => byId.get(id)).filter((s) => s !== undefined);
      // A row added or deleted mid-drag makes the order stale; the reload
      // that follows is the authority then.
      return next.length === prev.length ? next : prev;
    };
    onStepsChange(applyOrder(order));
    try {
      const fresh = await workApi.reorderSteps(containerId, order);
      onStepsChange((prev) => mergeReordered(prev, fresh));
    } catch (err) {
      onStepsChange(applyOrder(beforeOrder));
      toast.error(err instanceof Error ? err.message : t("saveFailed"));
    }
  }

  async function addStep(e: React.FormEvent) {
    e.preventDefault();
    const title = newTitle.trim();
    if (!title) return;
    setAdding(true);
    try {
      const created = await workApi.createStep(containerId, { title });
      onStepsChange((prev) => [...prev, created]);
      setNewTitle("");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("saveFailed"));
    } finally {
      setAdding(false);
    }
  }

  async function acceptAll() {
    setAccepting(true);
    try {
      await workApi.accept(containerId);
      onAccepted();
      toast.success(t("acceptedToast"));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("saveFailed"));
    } finally {
      setAccepting(false);
    }
  }

  const allAccepted = steps.length > 0 && steps.every((s) => s.state === "accepted");

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">
          {t("stepsCount", { count: steps.length })}
        </p>
        {canAccept && steps.length > 0 && !allAccepted && (
          <Button onClick={acceptAll} disabled={accepting} data-testid="coverage-btn-accept-all">
            <Check className="size-4" />
            {t("acceptAll")}
          </Button>
        )}
      </div>

      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
        <SortableContext items={steps.map((s) => s.id)} strategy={verticalListSortingStrategy}>
          <ol className="space-y-3" data-testid="coverage-steps-list">
            {steps.map((step, index) => (
              <StepRow
                key={step.id}
                step={step}
                index={index}
                canEdit={canEdit}
                primitives={primitives}
                labelOf={labelOf}
                t={t}
                onChange={replace}
                onDeleted={() => onStepsChange((prev) => prev.filter((s) => s.id !== step.id))}
              />
            ))}
          </ol>
        </SortableContext>
      </DndContext>

      {canEdit && (
        <form onSubmit={addStep} className="flex gap-2">
          <Input
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            placeholder={t("newStepPlaceholder")}
            maxLength={300}
            data-testid="coverage-step-input-new"
          />
          <Button type="submit" variant="outline" disabled={adding || !newTitle.trim()} data-testid="coverage-step-btn-add">
            <Plus className="size-4" />
            {t("addStep")}
          </Button>
        </form>
      )}
    </div>
  );
}

interface StepRowProps {
  step: WorkStep;
  index: number;
  canEdit: boolean;
  primitives: Primitive[];
  labelOf: (code: string) => string;
  t: Translate;
  onChange: (step: WorkStep) => void;
  onDeleted: () => void;
}

function StepRow({ step, index, canEdit, primitives, labelOf, t, onChange, onDeleted }: StepRowProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: step.id, disabled: !canEdit });
  const [title, setTitle] = useState(step.title);
  const [description, setDescription] = useState(step.description ?? "");
  const [hours, setHours] = useState(() => draftOf(step));
  // What the last PATCH carried. Both hour inputs commit on blur, and
  // tabbing from one to the other fires the second before the first
  // response has updated the prop - without this the same edit is sent
  // (and billed as ``work_step.update``) twice.
  const sentHours = useRef({
    hours_per_run: step.hours_per_run,
    runs_per_year: step.runs_per_year,
  });
  // The record can change under the row (reorder response, Accept all,
  // another editor): follow it - the "adjust state when a prop changes"
  // pattern, so an unsaved draft survives only until the server disagrees.
  const [synced, setSynced] = useState({
    title: step.title,
    description: step.description,
    hours_per_run: step.hours_per_run,
    runs_per_year: step.runs_per_year,
  });
  // Field by field: the response to one PATCH must not wipe what is being
  // typed in a sibling input.
  if (synced.title !== step.title) {
    setSynced((prev) => ({ ...prev, title: step.title }));
    setTitle(step.title);
  }
  if (synced.description !== step.description) {
    setSynced((prev) => ({ ...prev, description: step.description }));
    setDescription(step.description ?? "");
  }
  if (synced.hours_per_run !== step.hours_per_run) {
    setSynced((prev) => ({ ...prev, hours_per_run: step.hours_per_run }));
    setHours((prev) => ({ ...prev, hours: draftOf(step).hours }));
    sentHours.current = { ...sentHours.current, hours_per_run: step.hours_per_run };
  }
  if (synced.runs_per_year !== step.runs_per_year) {
    setSynced((prev) => ({ ...prev, runs_per_year: step.runs_per_year }));
    setHours((prev) => ({ ...prev, runs: draftOf(step).runs }));
    sentHours.current = { ...sentHours.current, runs_per_year: step.runs_per_year };
  }
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [reclassifyOpen, setReclassifyOpen] = useState(false);
  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : undefined,
  };
  const testId = `coverage-step-row-${step.id}`;

  async function patch(body: StepPatch): Promise<boolean> {
    try {
      onChange(await workApi.updateStep(step.id, body));
      return true;
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("saveFailed"));
      return false;
    }
  }

  // One PATCH for both numbers, on blur: the update is a billed action.
  function commitHours() {
    // A number the backend would refuse with a 422 on every blur never
    // leaves the browser; `sentHours` stays put so a corrected value is
    // still sent.
    if (hoursOutOfRange(hours)) {
      toast.error(
        t("hoursRangeError", {
          minHours: HOURS_PER_RUN_MIN,
          maxHours: HOURS_PER_RUN_MAX,
          maxRuns: RUNS_PER_YEAR_MAX,
        }),
      );
      return;
    }
    const next = parseHours(hours);
    const sent = sentHours.current;
    const body: StepPatch = {};
    if (next.hours_per_run !== sent.hours_per_run) body.hours_per_run = next.hours_per_run;
    if (next.runs_per_year !== sent.runs_per_year) body.runs_per_year = next.runs_per_year;
    if (Object.keys(body).length === 0) return;
    sentHours.current = next;
    void patch(body).then((ok) => {
      // A value the server refused must not stay marked as sent: the next
      // blur would compute an empty body and return, leaving the row showing
      // a number that was never saved and cannot be re-sent. Guarded by
      // identity so a later commit is not rolled back.
      if (!ok && sentHours.current === next) sentHours.current = sent;
    });
  }

  async function remove() {
    try {
      await workApi.deleteStep(step.id);
      onDeleted();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("saveFailed"));
    } finally {
      setConfirmDelete(false);
    }
  }

  // HRP-776: a suggested chip is confirmed or removed in place; the
  // outcome lands on the step-to-code link.
  async function confirmCapability(code: string) {
    try {
      onChange(await workApi.confirmCapability(step.id, code));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("saveFailed"));
    }
  }

  async function removeCapability(code: string) {
    try {
      onChange(await workApi.removeCapability(step.id, code));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("saveFailed"));
    }
  }

  return (
    <li ref={setNodeRef} style={style} data-testid={testId} className="rounded-lg border bg-background p-3">
      <div className="flex items-start gap-2">
        {canEdit && (
          <button
            type="button"
            className="mt-2 cursor-grab text-muted-foreground"
            aria-label={t("dragStepAria")}
            data-testid={`${testId}-handle`}
            {...attributes}
            {...listeners}
          >
            <GripVertical className="size-4" />
          </button>
        )}
        <span className="mt-2 w-6 shrink-0 text-sm tabular-nums text-muted-foreground">
          {index + 1}
        </span>
        <div className="flex-1 space-y-2">
          <div className="flex items-center gap-2">
            {canEdit ? (
              <Input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                onBlur={() => {
                  const next = title.trim();
                  if (next && next !== step.title) void patch({ title: next });
                  else setTitle(step.title);
                }}
                maxLength={300}
                aria-label={t("attrTitle")}
                className="font-medium"
                data-testid={`${testId}-title`}
              />
            ) : (
              <p className="font-medium" data-testid={`${testId}-title`}>{step.title}</p>
            )}
            <Badge className={STATE_COLOR[step.state]} data-testid={`${testId}-state`}>
              {t(`state_${step.state}`)}
            </Badge>
          </div>
          {canEdit ? (
            <Textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              onBlur={() => {
                const next = description.trim() || null;
                if (next !== (step.description ?? null)) void patch({ description: next });
              }}
              rows={2}
              placeholder={t("stepDescriptionPlaceholder")}
              aria-label={t("attrDescription")}
              data-testid={`${testId}-description`}
            />
          ) : (
            step.description && <p className="text-sm text-muted-foreground">{step.description}</p>
          )}

          {/* §5.7: five selects on every row was most of the input and
              little of the answer. Folded away behind a native disclosure -
              open it when a number or an owner is actually wrong. */}
          <details className="group" data-testid={`${testId}-details`}>
            <summary className="cursor-pointer list-none text-xs text-muted-foreground hover:text-foreground">
              {t("stepDetails")}
            </summary>
            <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
              <AttributeSelect
                label={t("attrResponsibility")}
                value={step.responsibility}
                options={RESPONSIBILITIES}
                optionLabel={(v) => t(`responsibility_${v}`)}
                disabled={!canEdit}
                testId={`${testId}-select-responsibility`}
                onChange={(v) => v && patch({ responsibility: v as Responsibility })}
              />
              <AttributeSelect
                label={t("attrReversibility")}
                value={step.reversibility}
                options={REVERSIBILITIES}
                optionLabel={(v) => t(`reversibility_${v}`)}
                unsetLabel={t("notSet")}
                disabled={!canEdit}
                testId={`${testId}-select-reversibility`}
                onChange={(v) => patch({ reversibility: v as Reversibility | null })}
              />
              <AttributeSelect
                label={t("attrOutput")}
                value={step.output_type}
                options={OUTPUT_TYPES}
                optionLabel={(v) => t(`output_${v}`)}
                disabled={!canEdit}
                testId={`${testId}-select-output`}
                onChange={(v) => v && patch({ output_type: v as OutputType })}
              />
              <HoursFields
                value={hours}
                disabled={!canEdit}
                testId={testId}
                labels={{ hours: t("attrHoursPerRun"), runs: t("attrRunsPerYear") }}
                onChange={setHours}
                onBlur={commitHours}
              />
            </div>
          </details>

          <div className="flex flex-wrap items-center gap-1.5" data-testid={`${testId}-capabilities`}>
            {step.capabilities.length === 0 && (
              <span className="text-xs text-muted-foreground">{t("noCapabilities")}</span>
            )}
            {step.capabilities.map((c) => (
              <CapabilityChip
                key={c.code}
                capability={c}
                label={labelOf(c.code)}
                canEdit={canEdit}
                t={t}
                testId={`${testId}-capability-${c.code}`}
                onConfirm={() => confirmCapability(c.code)}
                onRemove={() => removeCapability(c.code)}
              />
            ))}
            {canEdit && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setPickerOpen(true)}
                data-testid={`${testId}-btn-capabilities`}
              >
                {t("editCapabilities")}
              </Button>
            )}
            {canEdit && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setReclassifyOpen(true)}
                data-testid={`${testId}-btn-reclassify`}
              >
                <Sparkles className="size-3.5" />
                {t("reclassify")}
              </Button>
            )}
          </div>
        </div>
        {canEdit && (
          <Button
            size="icon"
            variant="ghost"
            aria-label={t("deleteStep")}
            onClick={() => setConfirmDelete(true)}
            data-testid={`${testId}-btn-delete`}
          >
            <Trash2 className="size-4" />
          </Button>
        )}
      </div>

      <ConfirmDialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        title={t("deleteStep")}
        description={t("deleteStepConfirm", { title: step.title })}
        onConfirm={remove}
      />
      {pickerOpen && (
        <CapabilityPicker
          step={step}
          primitives={primitives}
          labelOf={labelOf}
          t={t}
          onClose={() => setPickerOpen(false)}
          onSaved={(updated) => {
            onChange(updated);
            setPickerOpen(false);
          }}
        />
      )}
      {reclassifyOpen && (
        <ReclassifyDialog
          step={step}
          t={t}
          onClose={() => setReclassifyOpen(false)}
          onSaved={(updated) => {
            onChange(updated);
            setReclassifyOpen(false);
            toast.success(t("reclassifiedToast"));
          }}
        />
      )}
    </li>
  );
}

// A capability chip. A code the model reported below the tentative
// threshold, and nobody confirmed, is drawn as a suggestion: dashed, with
// the model's quote as its tooltip, and - for an editor - a confirm and a
// remove button. Its testid does not change; `data-tentative` does.
function CapabilityChip({
  capability,
  label,
  canEdit,
  t,
  testId,
  onConfirm,
  onRemove,
}: {
  capability: StepCapability;
  label: string;
  canEdit: boolean;
  t: Translate;
  testId: string;
  onConfirm: () => void;
  onRemove: () => void;
}) {
  const tentative = isTentative(capability);
  const percent = capability.confidence === null ? null : Math.round(capability.confidence * 100);
  const tooltip =
    capability.quote && percent !== null
      ? t("capabilityEvidence", { percent, quote: capability.quote })
      : undefined;
  return (
    <Badge
      variant="outline"
      className={
        tentative ? "gap-1 border-dashed border-amber-500/70 text-amber-800 dark:text-amber-300" : undefined
      }
      title={tooltip}
      data-testid={testId}
      data-tentative={tentative ? "true" : undefined}
      data-confirmed={capability.confirmed ? "true" : undefined}
    >
      {label}
      {tentative && (
        <span className="text-[10px] font-normal opacity-80">{t("capabilitySuggested")}</span>
      )}
      {tentative && canEdit && (
        <>
          <button
            type="button"
            className="ml-0.5 rounded hover:bg-amber-500/20"
            aria-label={t("confirmCapability")}
            title={t("confirmCapability")}
            onClick={onConfirm}
            data-testid={`${testId}-confirm`}
          >
            <Check className="size-3" />
          </button>
          <button
            type="button"
            className="rounded hover:bg-amber-500/20"
            aria-label={t("removeCapability")}
            title={t("removeCapability")}
            onClick={onRemove}
            data-testid={`${testId}-remove`}
          >
            <X className="size-3" />
          </button>
        </>
      )}
    </Badge>
  );
}

function AttributeSelect({
  label,
  value,
  options,
  optionLabel,
  unsetLabel,
  disabled,
  testId,
  onChange,
}: {
  label: string;
  value: string | null;
  options: string[];
  optionLabel: (value: string) => string;
  /** Present for nullable attributes: adds a "not set" option. Without it
   * a cleared value is never reported - the column is NOT NULL. */
  unsetLabel?: string;
  disabled: boolean;
  testId: string;
  onChange: (value: string | null) => void;
}) {
  const current = value ?? UNSET;
  return (
    <div className="flex flex-col gap-1 text-xs text-muted-foreground">
      <span>{label}</span>
      <Select
        value={current}
        onValueChange={(v) => {
          if (v == null || v === UNSET) {
            if (unsetLabel && value !== null) onChange(null);
            return;
          }
          if (v !== value) onChange(v);
        }}
        disabled={disabled}
      >
        <SelectTrigger className="h-8 w-full text-sm" aria-label={label} data-testid={testId}>
          <SelectValue>{value ? optionLabel(value) : unsetLabel}</SelectValue>
        </SelectTrigger>
        <SelectContent>
          {unsetLabel && <SelectItem value={UNSET}>{unsetLabel}</SelectItem>}
          {options.map((o) => (
            <SelectItem key={o} value={o}>
              {optionLabel(o)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

function CapabilityPicker({
  step,
  primitives,
  labelOf,
  t,
  onClose,
  onSaved,
}: {
  step: WorkStep;
  primitives: Primitive[];
  labelOf: (code: string) => string;
  t: Translate;
  onClose: () => void;
  onSaved: (step: WorkStep) => void;
}) {
  const [selected, setSelected] = useState<Set<string>>(new Set(step.primitive_codes));
  const [saving, setSaving] = useState(false);
  const groups: Array<{ kind: Primitive["kind"]; key: string }> = [
    { kind: "cognitive", key: "capabilitiesCognitive" },
    { kind: "boundary", key: "capabilitiesBoundary" },
  ];

  function toggle(code: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  }

  async function save() {
    setSaving(true);
    try {
      onSaved(await workApi.setStepPrimitives(step.id, [...selected]));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("saveFailed"));
      setSaving(false);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent data-testid="coverage-modal-capabilities">
        <DialogHeader>
          <DialogTitle>{t("capabilitiesTitle")}</DialogTitle>
        </DialogHeader>
        <p className="text-sm text-muted-foreground">{t("capabilitiesText")}</p>
        <div className="max-h-[50vh] space-y-4 overflow-y-auto">
          {groups.map((g) => (
            <div key={g.kind} className="space-y-1.5">
              <p className="text-xs font-medium uppercase text-muted-foreground">{t(g.key)}</p>
              {primitives
                .filter((p) => p.kind === g.kind)
                .map((p) => (
                  <label key={p.code} className="flex cursor-pointer items-center gap-2 text-sm">
                    <Checkbox
                      checked={selected.has(p.code)}
                      onCheckedChange={() => toggle(p.code)}
                      data-testid={`coverage-capability-option-${p.code}`}
                    />
                    {labelOf(p.code)}
                  </label>
                ))}
            </div>
          ))}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button onClick={save} disabled={saving} data-testid="coverage-btn-capabilities-save">
            {t("save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// HRP-775: the company's comment on a step goes to the model with the whole
// breakdown as context; the answer replaces this step's capabilities,
// responsibility and output type. One synchronous call.
function ReclassifyDialog({
  step,
  t,
  onClose,
  onSaved,
}: {
  step: WorkStep;
  t: Translate;
  onClose: () => void;
  onSaved: (step: WorkStep) => void;
}) {
  const [comment, setComment] = useState("");
  const [saving, setSaving] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const text = comment.trim();
    if (!text) return;
    setSaving(true);
    try {
      onSaved(await workApi.reclassifyStep(step.id, text));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("saveFailed"));
      setSaving(false);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !saving && onClose()}>
      <DialogContent data-testid="coverage-modal-reclassify">
        <form onSubmit={submit} className="space-y-4">
          <DialogHeader>
            <DialogTitle>{t("reclassifyTitle")}</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">{t("reclassifyText")}</p>
          <Textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            rows={3}
            maxLength={2000}
            placeholder={t("reclassifyPlaceholder")}
            aria-label={t("reclassifyTitle")}
            disabled={saving}
            data-testid="coverage-reclassify-input"
          />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose} disabled={saving}>
              {t("cancel")}
            </Button>
            <Button
              type="submit"
              disabled={saving || !comment.trim()}
              data-testid="coverage-btn-reclassify-submit"
            >
              <Sparkles className="size-4" />
              {t("reclassify")}
              <EECreditCostBadge action={RECLASSIFY_ACTION} />
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
