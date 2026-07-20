"use client";

import { useEffect, useState } from "react";
import { MoreHorizontal, Plus, Sparkles } from "lucide-react";
import { toast } from "sonner";

import { api } from "@/lib/api";
import type {
  AnswerScaleDeleteResult,
  AnswerScaleDetail,
} from "@/lib/types";
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
      .catch(() => toast.error("Failed to load scales"));
  }, [open, currentScaleId]);

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
          ? `Scale deleted. Drafts reassigned: ${result.reassigned_drafts}`
          : "Scale deleted",
      );
      const fresh = await reloadScales();
      if (pick === deleteId) {
        setPick(fresh.find((s) => s.is_default)?.id ?? "");
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete scale");
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
            <DialogTitle>Rating scale</DialogTitle>
          </DialogHeader>
          {scales.length === 0 ? (
            <p className="py-4 text-center text-sm text-muted-foreground">
              No scales available
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
                            {s.is_default ? "Default answer scale" : s.title}
                          </span>
                          {s.is_default && (
                            <Badge
                              variant="outline"
                              className="border-primary/40 text-primary"
                            >
                              <Sparkles className="mr-1 h-3 w-3" />
                              System
                            </Badge>
                          )}
                        </div>
                        {s.description && (
                          <p className="mt-0.5 text-xs text-muted-foreground">
                            {s.description}
                          </p>
                        )}
                        <div className="mt-1.5 flex flex-wrap gap-1">
                          {[...s.options]
                            .sort((a, b) => a.sort_index - b.sort_index)
                            .map((opt) => (
                              <Badge
                                key={opt.id}
                                variant="secondary"
                                className="text-xs"
                              >
                                {opt.title}
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
                          Preview
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
                              Edit
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              variant="destructive"
                              onClick={() => {
                                setDeleteId(s.id);
                                setDeleteOpen(true);
                              }}
                              data-testid={`${testIdPrefix}-modal-item-${s.id}-menu-delete`}
                            >
                              Delete
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
              Create scale
            </Button>
          )}
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={saving}
            >
              Cancel
            </Button>
            <Button
              data-testid={`${testIdPrefix}-modal-btn-save`}
              onClick={handleSave}
              disabled={saving || !pick || pick === (currentScaleId ?? "")}
            >
              {saving ? "Saving…" : "Save"}
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
        title="Delete this scale?"
        description="Drafts using this scale will be reassigned to the system default."
        confirmLabel="Delete"
        destructive
        onConfirm={confirmDelete}
      />
    </>
  );
}
