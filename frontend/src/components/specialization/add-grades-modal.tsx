"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { api } from "@/lib/api";
import {
  specializationsApi,
  type SpecializationGrade,
} from "@/lib/api/specializations";
import { computeGradeDiff } from "@/lib/grade-diff";
import { dictionaryItemLabel } from "@/lib/reference-labels";
import type { DictionaryItem } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

type Props = {
  open: boolean;
  specId: string;
  alreadyAdded: SpecializationGrade[];
  onClose: () => void;
  /** Receives the fresh server-side grade list after add+remove are applied. */
  onAdded: (grades: SpecializationGrade[]) => void;
};

export function AddGradesModal({
  open,
  specId,
  alreadyAdded,
  onClose,
  onAdded,
}: Props) {
  const t = useTranslations("company");
  const tc = useTranslations("common");
  const tRef = useTranslations("reference");
  const [pool, setPool] = useState<DictionaryItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  // HRP-158: the dialog manages the full attachment set — already-added
  // grades come in pre-checked; unchecking one queues a removal. `selected`
  // is insertion-ordered so newly added grades land in the matrix header in
  // the order the operator ticked them (sort_index respects that).
  const [selected, setSelected] = useState<string[]>([]);
  const [search, setSearch] = useState("");

  const addedIds = useMemo(
    () => new Set(alreadyAdded.map((g) => g.grade_id)),
    [alreadyAdded],
  );

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    // HRP-158: pre-check every already-attached grade so the dialog shows
    // the current state on open. Unchecking one stages a delete, ticking a
    // new one stages an add — same surface for both directions.
    setSelected(alreadyAdded.map((g) => g.grade_id));
    setSearch("");
    (async () => {
      try {
        const items = await api.get<DictionaryItem[]>("/dictionaries/grade");
        if (!cancelled) {
          // HRP-288 task 1: pool = active items ∪ already-attached items.
          // A grade that was attached to the specialization before being
          // deactivated must keep showing in the dialog with its checkbox
          // ticked so the operator can detach it explicitly. Brand-new
          // attachments still pick from active rows only.
          const attachedIds = new Set(alreadyAdded.map((g) => g.grade_id));
          setPool(
            items
              .filter((g) => g.is_active || attachedIds.has(g.id))
              .sort(
                (a, b) =>
                  a.sort_index - b.sort_index ||
                  // Raw-title tie-break: sort_index is the real order;
                  // ties only occur between tenant rows, whose labels
                  // render verbatim anyway (HRP-479).
                  a.title.localeCompare(b.title),
              ),
          );
        }
      } catch (err) {
        if (!cancelled) {
          toast.error(
            err instanceof Error ? err.message : t("toastGradesLoadFailed"),
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, alreadyAdded, t]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return pool;
    // HRP-479: the rows render the localized label, so the search must
    // match it too (raw title kept as a secondary match).
    return pool.filter(
      (g) =>
        g.title.toLowerCase().includes(q) ||
        dictionaryItemLabel(tRef, g).toLowerCase().includes(q),
    );
  }, [pool, search, tRef]);

  const diff = useMemo(
    () => computeGradeDiff(selected, addedIds),
    [selected, addedIds],
  );

  function toggle(id: string) {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  }

  async function handleSave() {
    if (diff.toAdd.length === 0 && diff.toRemove.length === 0) return;
    setSaving(true);
    try {
      // Process removals first — `add_grades` is idempotent and the order
      // matters only for the inserts (sort_index appends after the existing
      // max). Failing a delete (409 = position uses pair) aborts the whole
      // save, mirroring the GradeHeaderCell remove flow.
      for (const gradeId of diff.toRemove) {
        await specializationsApi.deleteGrade(specId, gradeId);
      }
      if (diff.toAdd.length > 0) {
        await specializationsApi.addGrades(specId, diff.toAdd);
      }
      const next = await specializationsApi.grades(specId);
      onAdded(next);
      const parts: string[] = [];
      if (diff.toAdd.length > 0) {
        parts.push(t("toastGradesAdded", { count: diff.toAdd.length }));
      }
      if (diff.toRemove.length > 0) {
        parts.push(t("toastGradesRemoved", { count: diff.toRemove.length }));
      }
      toast.success(parts.join(" · "));
      onClose();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toastGradesSaveFailed"));
    } finally {
      setSaving(false);
    }
  }

  const totalChanges = diff.toAdd.length + diff.toRemove.length;

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent
        data-testid="add-grades-modal"
        className="max-w-lg"
      >
        <DialogHeader>
          <DialogTitle>{t("manageGrades")}</DialogTitle>
          <DialogDescription>{t("manageGradesDescription")}</DialogDescription>
        </DialogHeader>

        <input
          data-testid="add-grades-search"
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t("searchGradesPlaceholder")}
          className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
          autoFocus
        />

        <div
          data-testid="add-grades-list"
          className="max-h-72 overflow-y-auto rounded-md border"
        >
          {loading ? (
            <p className="py-6 text-center text-sm text-muted-foreground">
              {t("loadingGrades")}
            </p>
          ) : filtered.length === 0 ? (
            <p
              data-testid="add-grades-empty"
              className="py-6 text-center text-sm text-muted-foreground"
            >
              {pool.length === 0 ? t("noGradesInDictionary") : t("noMatches")}
            </p>
          ) : (
            <ul className="divide-y">
              {filtered.map((g) => {
                const isAttached = addedIds.has(g.id);
                const isChecked = selected.includes(g.id);
                const willAdd = !isAttached && isChecked;
                const willRemove = isAttached && !isChecked;
                const newCount = isChecked
                  ? diff.toAdd.indexOf(g.id) + 1
                  : 0;
                return (
                  <li
                    key={g.id}
                    data-testid={`add-grades-row-${g.id}`}
                    data-state={
                      willAdd
                        ? "add"
                        : willRemove
                          ? "remove"
                          : isChecked
                            ? "attached"
                            : "off"
                    }
                    className="flex items-center gap-3 px-3 py-2"
                  >
                    <Checkbox
                      id={`grade-${g.id}`}
                      checked={isChecked}
                      onCheckedChange={() => toggle(g.id)}
                    />
                    <label
                      htmlFor={`grade-${g.id}`}
                      className="flex-1 cursor-pointer text-sm"
                    >
                      {dictionaryItemLabel(tRef, g)}
                      {/* HRP-288 task 1: chip + suffix so the operator
                          sees the row was deactivated in the dictionary
                          but kept because it was previously attached. */}
                      {!g.is_active ? (
                        <span
                          data-testid={`add-grades-row-${g.id}-inactive`}
                          className="ml-2 inline-flex items-center rounded-full bg-muted px-2 py-0.5 align-middle text-[10px] font-medium text-muted-foreground"
                        >
                          {t("inactive")}
                        </span>
                      ) : null}
                      {isAttached && !willRemove ? (
                        <span className="ml-2 text-xs text-muted-foreground">
                          {t("alreadyAttached")}
                        </span>
                      ) : null}
                      {willRemove ? (
                        <span
                          data-testid={`add-grades-row-${g.id}-remove`}
                          className="ml-2 text-xs font-medium text-destructive"
                        >
                          {t("willDetach")}
                        </span>
                      ) : null}
                    </label>
                    {newCount > 0 && willAdd ? (
                      <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
                        {newCount}
                      </span>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={saving}>
            {tc("cancel")}
          </Button>
          <Button
            data-testid="add-grades-save"
            onClick={handleSave}
            disabled={totalChanges === 0 || saving}
          >
            {saving
              ? t("savingEllipsis")
              : totalChanges === 0
                ? t("save")
                : t("saveWithCount", { count: totalChanges })}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
