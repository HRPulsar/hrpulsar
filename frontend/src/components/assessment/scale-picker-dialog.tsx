"use client";

import { useEffect, useState } from "react";
import { MoreHorizontal, Plus, Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { api } from "@/lib/api";
import type {
  AnswerScaleDeleteResult,
  AnswerScaleDetail,
} from "@/lib/types";
import {
  answerScaleDescription,
  scaleOptionLabel,
} from "@/lib/reference-labels";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { RadioGroup, RadioItem } from "@/components/ui/radio";

import { ScaleEditorSheet } from "./scale-editor-sheet";
import { ScalePreviewDialog } from "./scale-preview-dialog";

interface ScalePickerDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Currently assigned scale id (used to disable Save when unchanged). */
  currentScaleId: string | null;
  /** Persist the picked scale (or null to unassign). */
  onSave: (scaleId: string | null) => Promise<void>;
  /** Show inline create/edit/delete affordances. */
  canManage?: boolean;
  /** Test-id prefix for the picker dialog and its items. */
  testIdPrefix?: string;
}

export function ScalePickerDialog({
  open,
  onOpenChange,
  currentScaleId,
  onSave,
  canManage = false,
  testIdPrefix = "scale-picker",
}: ScalePickerDialogProps) {
  const t = useTranslations("assessments");
  const tc = useTranslations("common");
  const tRef = useTranslations("reference");
  const [scales, setScales] = useState<AnswerScaleDetail[]>([]);
  const [pick, setPick] = useState<string>("");
  const [saving, setSaving] = useState(false);

  const [editorOpen, setEditorOpen] = useState(false);
  const [editorMode, setEditorMode] = useState<"create" | "edit">("create");
  const [editorInitial, setEditorInitial] = useState<AnswerScaleDetail | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteId, setDeleteId] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setPick(currentScaleId ?? "");
    api
      .get<AnswerScaleDetail[]>("/answer-scales")
      .then(setScales)
      .catch(() => toast.error(t("errorLoadScales")));
  }, [open, currentScaleId, t]);

  async function reloadScales(): Promise<AnswerScaleDetail[]> {
    const fresh = await api.get<AnswerScaleDetail[]>("/answer-scales");
    setScales(fresh);
    return fresh;
  }

  function handleScaleSaved(saved: AnswerScaleDetail) {
    setScales((prev) => {
      const idx = prev.findIndex((s) => s.id === saved.id);
      if (idx >= 0) {
        const next = [...prev];
        next[idx] = saved;
        return next;
      }
      return [...prev, saved];
    });
    setPick(saved.id);
  }

  async function confirmDelete() {
    if (!deleteId) return;
    try {
      const result = await api.delete<AnswerScaleDeleteResult>(
        `/answer-scales/${deleteId}`,
      );
      toast.success(
        result.reassigned_drafts > 0
          ? t("toastScaleDeletedReassigned", {
              count: result.reassigned_drafts,
            })
          : t("toastScaleDeleted"),
      );
      const fresh = await reloadScales();
      if (pick === deleteId) {
        setPick(fresh.find((s) => s.is_default)?.id ?? "");
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("errorScaleDeleteFailed"));
    } finally {
      setDeleteOpen(false);
      setDeleteId(null);
    }
  }

  async function handleSave() {
    setSaving(true);
    try {
      await onSave(pick || null);
      onOpenChange(false);
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent
          data-testid={`${testIdPrefix}-modal`}
          className="sm:max-w-xl"
        >
          <DialogHeader>
            <DialogTitle>{t("ratingScale")}</DialogTitle>
          </DialogHeader>
          {scales.length === 0 ? (
            <p className="py-4 text-center text-sm text-muted-foreground">
              {t("noScalesAvailable")}
            </p>
          ) : (
            <RadioGroup
              value={pick}
              onValueChange={setPick}
              className="max-h-96 space-y-2 overflow-y-auto"
            >
              {[...scales]
                .sort((a, b) => {
                  if (a.is_default !== b.is_default) return a.is_default ? -1 : 1;
                  // Raw-title sort is safe: these lists exclude snapshots
                  // and tenant scales always have i18n_key NULL, so only
                  // the default scale localizes — and it sorts first via
                  // is_default above (HRP-479).
                  return a.title.localeCompare(b.title);
                })
                .map((s) => (
                  <div
                    key={s.id}
                    className="flex items-start gap-3 rounded-md border p-3 transition-colors hover:bg-accent/40"
                    data-testid={`${testIdPrefix}-modal-item-${s.id}`}
                  >
                    <label className="flex flex-1 cursor-pointer items-start gap-3">
                      <RadioItem value={s.id} className="mt-1" />
                      <div className="flex-1">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium">
                            {s.is_default ? t("defaultAnswerScale") : s.title}
                          </span>
                          {s.is_default && (
                            <Badge
                              variant="outline"
                              className="border-primary/40 text-primary"
                            >
                              <Sparkles className="mr-1 h-3 w-3" />
                              {t("systemBadge")}
                            </Badge>
                          )}
                        </div>
                        {(() => {
                          const description = answerScaleDescription(tRef, s);
                          return description ? (
                            <p className="mt-0.5 text-xs text-muted-foreground">
                              {description}
                            </p>
                          ) : null;
                        })()}
                        <div className="mt-1.5 flex flex-wrap gap-1">
                          {[...s.options]
                            .sort((a, b) => a.sort_index - b.sort_index)
                            .map((opt) => (
                              <Badge
                                key={opt.id}
                                variant="secondary"
                                className="text-xs"
                              >
                                {scaleOptionLabel(tRef, opt)}
                                {!opt.is_neutral && opt.weight !== null && (
                                  <span className="ml-1 text-muted-foreground">
                                    ({opt.weight})
                                  </span>
                                )}
                              </Badge>
                            ))}
                        </div>
                      </div>
                    </label>
                    <DropdownMenu>
                      <DropdownMenuTrigger
                        render={
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            data-testid={`${testIdPrefix}-modal-item-${s.id}-menu`}
                          />
                        }
                      >
                        <MoreHorizontal className="h-4 w-4" />
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem
                          onClick={() => {
                            setPreviewId(s.id);
                            setPreviewOpen(true);
                          }}
                          data-testid={`${testIdPrefix}-modal-item-${s.id}-menu-preview`}
                        >
                          {t("preview")}
                        </DropdownMenuItem>
                        {canManage && !s.is_default && (
                          <>
                            <DropdownMenuItem
                              onClick={() => {
                                setEditorMode("edit");
                                setEditorInitial(s);
                                setEditorOpen(true);
                              }}
                              data-testid={`${testIdPrefix}-modal-item-${s.id}-menu-edit`}
                            >
                              {t("edit")}
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              variant="destructive"
                              onClick={() => {
                                setDeleteId(s.id);
                                setDeleteOpen(true);
                              }}
                              data-testid={`${testIdPrefix}-modal-item-${s.id}-menu-delete`}
                            >
                              {tc("delete")}
                            </DropdownMenuItem>
                          </>
                        )}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                ))}
            </RadioGroup>
          )}
          {canManage && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setEditorMode("create");
                setEditorInitial(null);
                setEditorOpen(true);
              }}
              data-testid={`${testIdPrefix}-modal-btn-create`}
            >
              <Plus className="mr-1 h-4 w-4" />
              {t("createScale")}
            </Button>
          )}
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={saving}
            >
              {tc("cancel")}
            </Button>
            <Button
              data-testid={`${testIdPrefix}-modal-btn-save`}
              onClick={handleSave}
              disabled={saving || !pick || pick === (currentScaleId ?? "")}
            >
              {saving ? t("savingEllipsis") : t("save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ScaleEditorSheet
        open={editorOpen}
        onOpenChange={setEditorOpen}
        mode={editorMode}
        initial={editorInitial}
        onSaved={handleScaleSaved}
      />

      <ScalePreviewDialog
        open={previewOpen}
        onOpenChange={setPreviewOpen}
        scaleId={previewId}
      />

      <ConfirmDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        title={t("deleteScaleTitle")}
        description={t("deleteScaleDescription")}
        confirmLabel={tc("delete")}
        destructive
        onConfirm={confirmDelete}
      />
    </>
  );
}
