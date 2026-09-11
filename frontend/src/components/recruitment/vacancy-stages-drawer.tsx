"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
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
import { GripVertical, Plus, RotateCcw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { ApiError, api } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  BADGE_OUTLINE,
  type BadgeColor,
  resolveBadgeColor,
} from "@/lib/badge-tones";
import type { StageType, VacancyStage } from "@/lib/recruitment-types";
import {
  type StageDraftRow,
  buildStagesPayload,
  stageFromDefault,
  stageFromServer,
  stagesValidationError,
} from "@/lib/recruitment-helpers";

interface Props {
  vacancyId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved?: (stages: VacancyStage[]) => void;
}

type DraftStage = StageDraftRow;

// The stage-type set is frontend-owned, so the labels live in the
// `recruitment` catalog and each row resolves them with its own `t`.
const STAGE_TYPE_OPTIONS: Array<{ value: StageType; labelKey: string }> = [
  { value: "active", labelKey: "stagesTypeActive" },
  { value: "terminal_positive", labelKey: "stagesTypeTerminalPositive" },
  { value: "terminal_negative", labelKey: "stagesTypeTerminalNegative" },
  { value: "terminal_neutral", labelKey: "stagesTypeTerminalNeutral" },
];

const STAGE_TYPE_COLOR: Record<StageType, BadgeColor> = {
  active: "blue",
  terminal_positive: "emerald",
  terminal_negative: "rose",
  terminal_neutral: "neutral",
};

const STAGE_TYPE_TONE: Record<StageType, string> = {
  active: BADGE_OUTLINE[STAGE_TYPE_COLOR.active],
  terminal_positive: BADGE_OUTLINE[STAGE_TYPE_COLOR.terminal_positive],
  terminal_negative: BADGE_OUTLINE[STAGE_TYPE_COLOR.terminal_negative],
  terminal_neutral: BADGE_OUTLINE[STAGE_TYPE_COLOR.terminal_neutral],
};

// HRP-781: the colour used to be a free-text field holding a palette token,
// so a Russian workspace read "emerald" and anything mistyped was stored and
// then silently ignored at render time. Swatches need no wording in any
// language — the token stays as each option's accessible name, which is
// enough because the colour only tints a badge that already carries the
// stage name.
const STAGE_COLORS: readonly BadgeColor[] = [
  "neutral",
  "blue",
  "cyan",
  "teal",
  "green",
  "emerald",
  "yellow",
  "amber",
  "orange",
  "red",
  "rose",
  "pink",
  "purple",
  "violet",
  "indigo",
];

// Saturated fills for the swatches, keyed by the same palette. The badge
// tones themselves are bg-*-50 — made to sit behind text, so as swatches
// they read as fifteen near-white bars, and on an active stage's own
// blue-tinted row the control looks empty. currentColor is no good either:
// a highlighted option inherits the accent foreground, so the swatch turns
// white exactly while the pointer is on it.
const SWATCH_FILL: Record<BadgeColor, string> = {
  // Grey, not the theme's near-black muted-foreground: as a swatch that
  // reads as "black" rather than "no colour".
  neutral: "bg-slate-400",
  blue: "bg-blue-500",
  cyan: "bg-cyan-500",
  teal: "bg-teal-500",
  green: "bg-green-500",
  emerald: "bg-emerald-500",
  yellow: "bg-yellow-500",
  amber: "bg-amber-500",
  orange: "bg-orange-500",
  red: "bg-red-500",
  rose: "bg-rose-500",
  pink: "bg-pink-500",
  purple: "bg-purple-500",
  violet: "bg-violet-500",
  indigo: "bg-indigo-500",
};

function ColorSwatch({ color }: { color: BadgeColor }) {
  return (
    <span
      aria-hidden
      className={cn("block h-4 w-full min-w-4 rounded-sm", SWATCH_FILL[color])}
    />
  );
}

function genKey() {
  return Math.random().toString(36).slice(2, 10);
}

const fromServer = stageFromServer;
const freshFromDefault = (s: VacancyStage) => stageFromDefault(s, genKey);

export function VacancyStagesDrawer({
  vacancyId,
  open,
  onOpenChange,
  onSaved,
}: Props) {
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const [draft, setDraft] = useState<DraftStage[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [conflict, setConflict] = useState<{
    affected_candidate_count: number;
  } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.get<VacancyStage[]>(
        `/recruitment/vacancies/${vacancyId}/funnel-stages`,
      );
      setDraft(data.map(fromServer));
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("stagesLoadFailed"),
      );
    } finally {
      setLoading(false);
    }
  }, [vacancyId, t]);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );

  const handleDragEnd = useCallback((event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    setDraft((prev) => {
      const oldIndex = prev.findIndex((s) => s.key === active.id);
      const newIndex = prev.findIndex((s) => s.key === over.id);
      if (oldIndex === -1 || newIndex === -1) return prev;
      return arrayMove(prev, oldIndex, newIndex);
    });
  }, []);

  const updateField = useCallback(
    (key: string, patch: Partial<DraftStage>) => {
      setDraft((prev) =>
        prev.map((s) => (s.key === key ? { ...s, ...patch } : s)),
      );
    },
    [],
  );

  const removeStage = useCallback((key: string) => {
    setDraft((prev) => prev.filter((s) => s.key !== key));
  }, []);

  const addStage = useCallback(() => {
    setDraft((prev) => [
      ...prev,
      {
        key: genKey(),
        id: null,
        name: t("stagesNewStageName"),
        code: `stage_${prev.length + 1}`,
        color: "slate",
        stage_type: "active",
      },
    ]);
  }, [t]);

  const restoreDefault = useCallback(async () => {
    try {
      const defaults = await api.get<VacancyStage[]>(
        `/recruitment/recruitment-stages`,
      );
      setDraft(defaults.map(freshFromDefault));
      toast.success(t("stagesToastRestoredDefaults"));
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("stagesLoadDefaultsFailed"),
      );
    }
  }, [t]);

  const save = useCallback(async () => {
    const err = stagesValidationError(t, draft);
    if (err) {
      toast.error(err);
      return;
    }
    setSaving(true);
    try {
      const updated = await api.put<VacancyStage[]>(
        `/recruitment/vacancies/${vacancyId}/funnel-stages`,
        { stages: buildStagesPayload(draft) },
      );
      onSaved?.(updated);
      toast.success(t("stagesToastSaved"));
      onOpenChange(false);
    } catch (err) {
      if (
        err instanceof ApiError &&
        err.status === 409 &&
        err.detail &&
        typeof err.detail === "object" &&
        (err.detail as { code?: unknown }).code === "stage_has_candidates"
      ) {
        const d = err.detail as { affected_candidate_count?: number };
        setConflict({
          affected_candidate_count: d.affected_candidate_count ?? 0,
        });
      } else {
        toast.error(err instanceof Error ? err.message : t("stagesSaveFailed"));
      }
    } finally {
      setSaving(false);
    }
  }, [draft, onOpenChange, onSaved, vacancyId, t]);

  const items = useMemo(() => draft.map((s) => s.key), [draft]);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="w-full max-w-lg sm:max-w-2xl"
        data-testid="vacancy-stage-manage-drawer"
      >
        <SheetHeader>
          <SheetTitle>{t("stagesDrawerTitle")}</SheetTitle>
          <SheetDescription>{t("stagesDrawerDescription")}</SheetDescription>
        </SheetHeader>

        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={restoreDefault}
            disabled={loading || saving}
            data-testid="vacancy-stage-manage-restore-default-btn"
          >
            <RotateCcw className="mr-1 size-3.5" /> {t("stagesRestoreDefault")}
          </Button>
          <Button
            size="sm"
            onClick={addStage}
            disabled={loading || saving}
            data-testid="vacancy-stage-manage-add-btn"
          >
            <Plus className="mr-1 size-3.5" /> {t("stagesAddStage")}
          </Button>
        </div>

        <div className="flex-1 overflow-y-auto pr-1">
          {loading ? (
            <p className="py-6 text-center text-sm text-muted-foreground">
              {t("stagesLoading")}
            </p>
          ) : draft.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">
              {t("stagesEmpty")}
            </p>
          ) : (
            <DndContext
              sensors={sensors}
              collisionDetection={closestCenter}
              onDragEnd={handleDragEnd}
            >
              <SortableContext
                items={items}
                strategy={verticalListSortingStrategy}
              >
                <ul className="space-y-2">
                  {draft.map((s) => (
                    <SortableStageRow
                      key={s.key}
                      stage={s}
                      onChange={(patch) => updateField(s.key, patch)}
                      onRemove={() => removeStage(s.key)}
                    />
                  ))}
                </ul>
              </SortableContext>
            </DndContext>
          )}
        </div>

        <SheetFooter>
          <Button
            variant="ghost"
            onClick={() => onOpenChange(false)}
            disabled={saving}
          >
            {tc("cancel")}
          </Button>
          <Button
            onClick={save}
            disabled={loading || saving || draft.length === 0}
            data-testid="vacancy-stage-manage-save-btn"
          >
            {saving ? t("actionSaving") : t("stagesSaveButton")}
          </Button>
        </SheetFooter>

        <ConfirmDialog
          open={!!conflict}
          onOpenChange={(o) => {
            if (!o) setConflict(null);
          }}
          title={t("stagesConflictTitle")}
          description={
            conflict
              ? t("stagesConflictDescription", {
                  count: conflict.affected_candidate_count,
                })
              : ""
          }
          confirmLabel={t("stagesConflictConfirm")}
          cancelLabel={t("stagesConflictClose")}
          onConfirm={() => setConflict(null)}
        />
      </SheetContent>
    </Sheet>
  );
}

interface SortableStageRowProps {
  stage: DraftStage;
  onChange: (patch: Partial<DraftStage>) => void;
  onRemove: () => void;
}

function SortableStageRow({
  stage,
  onChange,
  onRemove,
}: SortableStageRowProps) {
  const t = useTranslations("recruitment");
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: stage.key });

  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.6 : 1,
  };

  // Active stages always render blue whatever is stored; a terminal stage
  // falls back to its type's colour when the stored value names none, which
  // is what the funnel table paints for the same row.
  const swatch =
    stage.stage_type === "active"
      ? STAGE_TYPE_COLOR.active
      : (resolveBadgeColor(stage.color) ?? STAGE_TYPE_COLOR[stage.stage_type]);

  return (
    <li
      ref={setNodeRef}
      style={style}
      className={cn(
        "space-y-2 rounded-md border bg-card p-3 text-sm",
        STAGE_TYPE_TONE[stage.stage_type],
      )}
      data-testid={`vacancy-stage-manage-item-${stage.id ?? stage.key}`}
    >
      <div className="flex items-center gap-2">
        <button
          type="button"
          className="cursor-grab text-muted-foreground hover:text-foreground focus:outline-none"
          aria-label={t("stagesDragHandle")}
          {...attributes}
          {...listeners}
        >
          <GripVertical className="size-4" />
        </button>
        <Input
          value={stage.name}
          onChange={(e) => onChange({ name: e.target.value })}
          placeholder={t("stagesNamePlaceholder")}
          className="flex-1"
          data-testid={`vacancy-stage-manage-item-${stage.id ?? stage.key}-name`}
        />
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={onRemove}
          aria-label={t("stagesRemoveStage")}
          data-testid={`vacancy-stage-manage-item-${stage.id ?? stage.key}-delete-btn`}
        >
          <Trash2 className="size-4" />
        </Button>
      </div>
      <div className="grid grid-cols-3 gap-2">
        <Input
          value={stage.code}
          onChange={(e) => onChange({ code: e.target.value })}
          placeholder={t("stagesCodePlaceholder")}
          data-testid={`vacancy-stage-manage-item-${stage.id ?? stage.key}-code`}
        />
        {/* HRP-357 REDO: active stages always render blue — the stored
            color only applies to terminal stages. */}
        <Select
          value={swatch}
          onValueChange={(v) => onChange({ color: v })}
          disabled={stage.stage_type === "active"}
        >
          <SelectTrigger
            className="w-full"
            aria-label={t("stagesColorLabel")}
            title={
              stage.stage_type === "active"
                ? t("stagesActiveColorHint")
                : t("stagesColorLabel")
            }
            data-testid={`vacancy-stage-manage-item-${stage.id ?? stage.key}-color`}
          >
            <SelectValue>
              <ColorSwatch color={swatch} />
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            {STAGE_COLORS.map((c) => (
              <SelectItem key={c} value={c} aria-label={c}>
                <ColorSwatch color={c} />
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select
          value={stage.stage_type}
          onValueChange={(v) => onChange({ stage_type: v as StageType })}
        >
          <SelectTrigger
            size="sm"
            data-testid={`vacancy-stage-manage-item-${stage.id ?? stage.key}-type`}
          >
            <SelectValue>
              {(() => {
                const opt = STAGE_TYPE_OPTIONS.find(
                  (o) => o.value === stage.stage_type,
                );
                return opt ? t(opt.labelKey) : stage.stage_type;
              })()}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            {STAGE_TYPE_OPTIONS.map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>
                {t(opt.labelKey)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </li>
  );
}
