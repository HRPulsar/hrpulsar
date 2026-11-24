"use client";

// HRP-1228: what can be done with a process or a project - Edit, Access,
// Archive, Delete - behind one kebab, the same on its page and on its row
// of the list, as on a vacancy. Each item shows by the rule its button had.

import { useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { Archive, Lock, MoreVertical, Pencil, Trash2 } from "lucide-react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { AccessDialog } from "@/components/coverage/access-dialog";
import { Button } from "@/components/ui/button";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { type WorkContainer, workApi } from "@/lib/api/work";

export function ContainerActions({
  container,
  testIdPrefix,
  disabled = false,
  onChanged,
  onDeleted,
  onBusyChange,
}: {
  container: WorkContainer;
  /** `coverage-btn` on the page, `coverage-row-{id}-btn` on a row of the list. */
  testIdPrefix: string;
  /** The page is busy with the process: no archiving or deleting meanwhile. */
  disabled?: boolean;
  /** Saved or archived - with the container the answer carried - or its
   * owner changed, which only a reload shows. */
  onChanged: (updated?: WorkContainer) => void;
  onDeleted: () => void;
  /** Archiving or deleting is on its way: the page holds its own buttons,
   * so no breakdown starts on a process about to be archived. */
  onBusyChange?: (busy: boolean) => void;
}) {
  const t = useTranslations("coverage");
  const [open, setOpen] = useState<"edit" | "access" | "delete" | null>(null);
  const [busy, setOwnBusy] = useState(false);
  function setBusy(next: boolean) {
    setOwnBusy(next);
    onBusyChange?.(next);
  }

  // HRP-810: the process says what this caller may do with it. A reader
  // has no item at all, so no kebab either.
  const access = container.my_access ?? "read";
  if (access === "read") return null;
  const archived = container.status === "archived";
  // A process created by mistake stays visible to the whole company until
  // it is archived or deleted; both are the section's roles only.
  const canManage = access === "manage";

  async function archive() {
    setBusy(true);
    try {
      onChanged(await workApi.updateContainer(container.id, { status: "archived" }));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("saveFailed"));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    try {
      await workApi.deleteContainer(container.id);
      setOpen(null);
      onDeleted();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("saveFailed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={t("actionsAria")}
              data-testid={`${testIdPrefix}-actions`}
            />
          }
        >
          <MoreVertical />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {!archived && (
            <DropdownMenuItem data-testid={`${testIdPrefix}-edit`} onClick={() => setOpen("edit")}>
              <Pencil />
              {t("editContainer")}
            </DropdownMenuItem>
          )}
          <DropdownMenuItem data-testid={`${testIdPrefix}-access`} onClick={() => setOpen("access")}>
            <Lock />
            {t("accessButton")}
          </DropdownMenuItem>
          {canManage && !archived && (
            <DropdownMenuItem
              disabled={busy || disabled}
              data-testid={`${testIdPrefix}-archive`}
              onClick={() => void archive()}
            >
              <Archive />
              {t("archiveContainer")}
            </DropdownMenuItem>
          )}
          {canManage && (
            <DropdownMenuItem
              variant="destructive"
              disabled={busy || disabled}
              data-testid={`${testIdPrefix}-delete`}
              onClick={() => setOpen("delete")}
            >
              <Trash2 />
              {t("deleteContainer")}
            </DropdownMenuItem>
          )}
        </DropdownMenuContent>
      </DropdownMenu>

      {open === "edit" && (
        <EditContainerDialog
          container={container}
          onClose={() => setOpen(null)}
          onSaved={(updated) => {
            setOpen(null);
            onChanged(updated);
          }}
        />
      )}

      {open === "access" && (
        <AccessDialog
          containerId={container.id}
          canChangeOwner={canManage}
          onClose={() => setOpen(null)}
          onOwnerChanged={() => onChanged()}
        />
      )}

      <ConfirmDialog
        open={open === "delete"}
        onOpenChange={(next) => !next && setOpen(null)}
        title={t("deleteContainer")}
        description={t("deleteContainerConfirm", { title: container.title })}
        onConfirm={() => void remove()}
        loading={busy}
        confirmTestId="coverage-btn-delete-confirm"
      />
    </>
  );
}

function EditContainerDialog({
  container,
  onClose,
  onSaved,
}: {
  container: WorkContainer;
  onClose: () => void;
  onSaved: (container: WorkContainer) => void;
}) {
  const t = useTranslations("coverage");
  const [title, setTitle] = useState(container.title);
  const [description, setDescription] = useState(container.description ?? "");
  const [goal, setGoal] = useState(container.goal ?? "");
  const [saving, setSaving] = useState(false);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim() || !description.trim()) return;
    setSaving(true);
    try {
      onSaved(
        await workApi.updateContainer(container.id, {
          title: title.trim(),
          description: description.trim(),
          goal: goal.trim() || null,
        }),
      );
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("saveFailed"));
      setSaving(false);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent data-testid="coverage-modal-edit">
        <form onSubmit={save} className="space-y-4">
          <DialogHeader>
            <DialogTitle>{t("editContainer")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-1.5">
            <Label htmlFor="coverage-edit-title">{t("fieldTitle")}</Label>
            <Input
              id="coverage-edit-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              maxLength={300}
              required
              data-testid="coverage-edit-input-title"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="coverage-edit-description">{t("fieldDescription")}</Label>
            <Textarea
              id="coverage-edit-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={6}
              required
              data-testid="coverage-edit-textarea-description"
            />
            {!description.trim() && (
              <p
                className="text-xs text-muted-foreground"
                data-testid="coverage-edit-description-required"
              >
                {t("descriptionRequired")}
              </p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="coverage-edit-goal">{t("fieldGoal")}</Label>
            <Textarea
              id="coverage-edit-goal"
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
              rows={2}
              data-testid="coverage-edit-textarea-goal"
            />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              {t("cancel")}
            </Button>
            <Button
              type="submit"
              disabled={saving || !title.trim() || !description.trim()}
              data-testid="coverage-btn-edit-save"
            >
              {t("save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
