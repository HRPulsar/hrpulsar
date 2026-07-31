"use client";

import { useEffect, useMemo, useState } from "react";
import { HelpCircle, Pencil, Plus, Sparkles, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  Sheet,
  SheetContent,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { api } from "@/lib/api";
import { skillLevelLabel } from "@/lib/reference-labels";
import type { CompetenceDetail, Indicator, SkillLevel } from "@/lib/types";

interface IndicatorsEditorProps {
  competenceId: string;
  /** Disabled with explanation when an AI generation is busy. */
  disabledReason?: string | null;
  /** Triggered when the user clicks "Generate with AI" — opens the AI flow owned by the parent. */
  onGenerateAi: () => void;
  /** Optional callback after any successful CRUD so the parent can refresh the tree. */
  onChanged?: () => void;
}

export function IndicatorsEditor({
  competenceId,
  disabledReason,
  onGenerateAi,
  onChanged,
}: IndicatorsEditorProps) {
  const t = useTranslations("competences");
  const tc = useTranslations("common");
  const tRef = useTranslations("reference");
  const [detail, setDetail] = useState<CompetenceDetail | null>(null);
  const [skillLevels, setSkillLevels] = useState<SkillLevel[]>([]);
  const [loading, setLoading] = useState(true);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState<Indicator | null>(null);
  const [deleting, setDeleting] = useState<Indicator | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [showHelp, setShowHelp] = useState(false);

  async function refresh() {
    setLoading(true);
    try {
      const [d, levels] = await Promise.all([
        api.get<CompetenceDetail>(`/competences/${competenceId}`),
        api.get<SkillLevel[]>("/skill-levels").catch(() => [] as SkillLevel[]),
      ]);
      setDetail(d);
      setSkillLevels(levels);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("errorLoad"));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [competenceId]);

  const grouped = useMemo(() => {
    const order = new Map(skillLevels.map((l) => [l.id, l.sort_index]));
    const groups = new Map<string, { level: SkillLevel; items: Indicator[] }>();
    if (!detail) return [] as { level: SkillLevel; items: Indicator[] }[];
    for (const ind of detail.indicators) {
      const level: SkillLevel =
        skillLevels.find((l) => l.id === ind.skill_level_id) ?? {
          id: ind.skill_level_id,
          title: ind.skill_level_title || t("unknownLevel"),
          sort_index: 999,
          i18n_key: null,
          is_active: true,
          tenant_id: null,
        };
      const bucket = groups.get(level.id);
      if (bucket) bucket.items.push(ind);
      else groups.set(level.id, { level, items: [ind] });
    }
    for (const bucket of groups.values()) {
      bucket.items.sort((a, b) => a.sort_index - b.sort_index);
    }
    return [...groups.values()].sort(
      (a, b) =>
        (order.get(a.level.id) ?? a.level.sort_index) -
        (order.get(b.level.id) ?? b.level.sort_index),
    );
  }, [detail, skillLevels, t]);

  function openCreate() {
    setEditing({
      id: "",
      title: "",
      weight: 0,
      sort_index: detail?.indicators.length ?? 0,
      skill_level_id: skillLevels[0]?.id ?? "",
      skill_level_title: null,
      competence_id: competenceId,
      is_active: true,
      tenant_id: null,
      created_at: "",
    });
    setEditorOpen(true);
  }

  function openEdit(ind: Indicator) {
    setEditing(ind);
    setEditorOpen(true);
  }

  function openDelete(ind: Indicator) {
    setDeleting(ind);
    setDeleteOpen(true);
  }

  async function saveIndicator(payload: Indicator) {
    const isCreate = !payload.id;
    const body = {
      title: payload.title.trim(),
      weight: payload.weight,
      sort_index: payload.sort_index,
      skill_level_id: payload.skill_level_id,
    };
    if (!body.title || !body.skill_level_id) {
      toast.error(t("errorTitleAndLevelRequired"));
      return;
    }
    try {
      if (isCreate) {
        await api.post(`/competences/${competenceId}/indicators`, body);
        toast.success(t("toastIndicatorAdded"));
      } else {
        await api.put(`/indicators/${payload.id}`, body);
        toast.success(t("toastIndicatorUpdated"));
      }
      setEditorOpen(false);
      setEditing(null);
      await refresh();
      onChanged?.();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("errorSave"));
    }
  }

  async function confirmDelete() {
    if (!deleting) return;
    try {
      await api.delete(`/indicators/${deleting.id}`);
      toast.success(t("toastIndicatorDeleted"));
      setDeleteOpen(false);
      setDeleting(null);
      await refresh();
      onChanged?.();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("errorDelete"));
    }
  }

  return (
    <div data-testid="indicators-editor" className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Label className="text-sm font-medium">{t("sectionIndicators")}</Label>
        <button
          type="button"
          onClick={() => setShowHelp((v) => !v)}
          className="text-muted-foreground transition-colors hover:text-foreground"
          aria-label={t("indicatorsEditorHelpAria")}
          data-testid="indicators-editor-help-toggle"
        >
          <HelpCircle className="h-4 w-4" />
        </button>
        <span className="ml-auto text-xs text-muted-foreground">
          {t("indicatorsEditorTotal", {
            count: detail ? detail.indicators.length : 0,
          })}
        </span>
        <Button
          data-testid="indicators-editor-btn-add"
          size="sm"
          variant="outline"
          onClick={openCreate}
          disabled={skillLevels.length === 0}
          title={
            skillLevels.length === 0
              ? t("indicatorsEditorNoLevels")
              : undefined
          }
        >
          <Plus className="mr-1 h-3.5 w-3.5" />
          {t("addIndicator")}
        </Button>
        {disabledReason ? (
          <Tooltip>
            <TooltipTrigger
              render={<span tabIndex={-1} className="inline-flex" />}
            >
              <Button
                data-testid="indicators-editor-btn-ai"
                size="sm"
                disabled
              >
                <Sparkles className="mr-1 h-3.5 w-3.5" />
                {t("generateWithAi")}
              </Button>
            </TooltipTrigger>
            <TooltipContent>{disabledReason}</TooltipContent>
          </Tooltip>
        ) : (
          <Button
            data-testid="indicators-editor-btn-ai"
            size="sm"
            onClick={onGenerateAi}
          >
            <Sparkles className="mr-1 h-3.5 w-3.5" />
            {t("generateWithAi")}
          </Button>
        )}
      </div>

      {showHelp && (
        <p
          data-testid="indicators-editor-help"
          className="rounded-md border bg-muted/40 px-3 py-2 text-xs text-muted-foreground"
        >
          {t("indicatorsEditorHelp")}
        </p>
      )}

      {loading ? (
        <p className="text-sm text-muted-foreground">
          {t("loadingIndicators")}
        </p>
      ) : grouped.length === 0 ? (
        <p className="rounded-md border border-dashed px-3 py-4 text-sm text-muted-foreground">
          {t("indicatorsEditorEmpty")}
        </p>
      ) : (
        <div className="space-y-3">
          {grouped.map(({ level, items }) => (
            <div
              key={level.id}
              data-testid={`indicators-editor-level-${level.id}`}
              className="rounded-md border"
            >
              <div className="flex items-center justify-between border-b bg-muted/30 px-3 py-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                <span>{skillLevelLabel(tRef, level)}</span>
                <span>{t("indicatorCount", { count: items.length })}</span>
              </div>
              <ul className="divide-y">
                {items.map((ind) => (
                  <li
                    key={ind.id}
                    data-testid={`indicators-editor-item-${ind.id}`}
                    className="flex items-center gap-2 px-3 py-2 text-sm"
                  >
                    <span className="flex-1">{ind.title}</span>
                    {ind.weight > 0 && (
                      <span className="text-xs text-muted-foreground">
                        {t("weightInline", { value: ind.weight })}
                      </span>
                    )}
                    <Button
                      size="icon-xs"
                      variant="ghost"
                      onClick={() => openEdit(ind)}
                      data-testid={`indicators-editor-item-${ind.id}-edit`}
                      aria-label={t("editIndicator")}
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </Button>
                    <Button
                      size="icon-xs"
                      variant="ghost"
                      onClick={() => openDelete(ind)}
                      data-testid={`indicators-editor-item-${ind.id}-delete`}
                      aria-label={t("deleteIndicator")}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}

      {editing && (
        <Sheet
          open={editorOpen}
          onOpenChange={(v) => {
            setEditorOpen(v);
            if (!v) setEditing(null);
          }}
        >
          <SheetContent className="w-full max-w-md">
            <SheetHeader>
              <SheetTitle>
                {editing.id ? t("editIndicator") : t("addIndicator")}
              </SheetTitle>
            </SheetHeader>
            <div className="space-y-4 py-2">
              <div className="space-y-2">
                <Label>{t("fieldTitle")}</Label>
                <Input
                  data-testid="indicators-editor-input-title"
                  value={editing.title}
                  onChange={(e) =>
                    setEditing({ ...editing, title: e.target.value })
                  }
                  autoFocus
                />
              </div>
              <div className="space-y-2">
                <Label>{t("fieldSkillLevel")}</Label>
                <Select
                  value={editing.skill_level_id}
                  onValueChange={(val) =>
                    setEditing({ ...editing, skill_level_id: val })
                  }
                >
                  <SelectTrigger data-testid="indicators-editor-select-level">
                    <SelectValue placeholder={t("selectLevel")}>
                      {(() => {
                        const sel = skillLevels.find(
                          (l) => l.id === editing.skill_level_id,
                        );
                        return (
                          (sel ? skillLevelLabel(tRef, sel) : "") ||
                          t("selectLevel")
                        );
                      })()}
                    </SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {skillLevels.map((level) => (
                      <SelectItem key={level.id} value={level.id}>
                        {skillLevelLabel(tRef, level)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>{t("fieldWeightOptional")}</Label>
                <Input
                  type="number"
                  min={0}
                  max={1000}
                  value={editing.weight}
                  onChange={(e) =>
                    setEditing({
                      ...editing,
                      weight: Math.max(0, Number(e.target.value) || 0),
                    })
                  }
                />
                <p className="text-xs text-muted-foreground">
                  {t("indicatorsEditorWeightHint")}
                </p>
              </div>
            </div>
            <SheetFooter>
              <Button
                variant="outline"
                onClick={() => {
                  setEditorOpen(false);
                  setEditing(null);
                }}
              >
                {tc("cancel")}
              </Button>
              <Button
                data-testid="indicators-editor-btn-save"
                onClick={() => saveIndicator(editing)}
              >
                {editing.id ? t("save") : t("add")}
              </Button>
            </SheetFooter>
          </SheetContent>
        </Sheet>
      )}

      <ConfirmDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        title={t("deleteIndicatorTitle")}
        description={
          deleting
            ? t("deleteIndicatorDescription", { title: deleting.title })
            : ""
        }
        onConfirm={confirmDelete}
      />
    </div>
  );
}
