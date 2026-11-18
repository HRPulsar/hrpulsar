"use client";

// HRP-809: name the people who do a step, or the one who checks and signs
// it. Matching skills are not required - the Coverage row shows which ones
// are missing. HRP-1197: the people who do it are several, picked from a
// list ranked by how much of the step each one holds, and saved together;
// the checker stays one person, saved on the click.

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { PeopleSelectList } from "@/components/people-select-list";
import { type StepPatch, type WorkStep, workApi } from "@/lib/api/work";

export type AssigneeField = "executor_employee_ids" | "accountable_employee_id";

type Person = {
  employee_id: string;
  name: string;
  email: string | null;
  position_title: string | null;
  match_percent?: number | null;
};

export function AssignPersonDialog({
  containerId,
  stepId,
  field,
  currentIds,
  suggestedIds = [],
  onClose,
  onSaved,
}: {
  containerId: string;
  stepId: string;
  field: AssigneeField;
  /** Who the step names now, as stored. */
  currentIds: string[];
  /** HRP-1198: checked from the start - the people the match found, for To
   * do's "confirm". Executors only. */
  suggestedIds?: string[];
  onClose: () => void;
  onSaved: (step: WorkStep) => void;
}) {
  const t = useTranslations("coverage");
  const tc = useTranslations("common");
  const many = field === "executor_employee_ids";
  const [people, setPeople] = useState<Person[] | null>(null);
  const [search, setSearch] = useState("");
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(many ? [...currentIds, ...suggestedIds] : currentIds),
  );

  useEffect(() => {
    let cancelled = false;
    // HRP-810: the process's own list - an owner who is not HR still sees
    // the whole company, and only people at work can take a step. The
    // executors' list is the same people, ranked for this step (HRP-1197).
    const load: Promise<Person[]> = many
      ? workApi.stepPeople(stepId)
      : workApi.listPeople(containerId).then((res) => res.filter((p) => p.assignable));
    load
      .then((res) => !cancelled && setPeople(res))
      // An error, not the "no employees yet" empty state.
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
    };
  }, [containerId, stepId, many]);

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (people ?? [])
      .filter(
        (p) =>
          !q ||
          [p.name, p.email, p.position_title].some((v) => v?.toLowerCase().includes(q)),
      )
      .map((p) => ({
        id: p.employee_id,
        name: p.name || p.email || p.employee_id,
        subtitle: p.position_title ?? p.email,
        aside:
          p.match_percent === undefined || p.match_percent === null
            ? null
            : t("matchPercent", { percent: p.match_percent }),
        disabled: saving,
      }));
  }, [people, search, saving, t]);

  async function save(patch: StepPatch) {
    setSaving(true);
    try {
      const step = await workApi.updateStep(stepId, patch);
      toast.success(t("assignSaved"));
      onSaved(step);
      onClose();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("saveFailed"));
      setSaving(false);
    }
  }

  function toggle(id: string) {
    if (!many) {
      if (currentIds.includes(id)) onClose();
      else void save({ accountable_employee_id: id });
      return;
    }
    setSelected((prev) => {
      const next = new Set(prev);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-lg" data-testid="coverage-modal-assign" data-field={field}>
        <DialogHeader>
          <DialogTitle>{many ? t("assignExecutorTitle") : t("assignAccountableTitle")}</DialogTitle>
          <DialogDescription>{t(many ? "assignExecutorsText" : "assignText")}</DialogDescription>
        </DialogHeader>
        <Input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t("assignSearchPlaceholder")}
          data-testid="coverage-modal-assign-search"
        />
        <PeopleSelectList
          rows={rows}
          isSelected={(id) => selected.has(id)}
          onToggle={toggle}
          loading={people === null && !failed}
          loadingLabel={tc("loading")}
          emptyLabel={
            failed
              ? tc("loadFailed")
              : people?.length === 0
                ? t("assignNoEmployees")
                : t("assignNoMatch")
          }
          className="max-h-72"
          testId="coverage-modal-assign-list"
          rowTestId={(id) => `coverage-modal-assign-option-${id}`}
        />
        <DialogFooter>
          {currentIds.length > 0 && (
            <Button
              variant="outline"
              className="sm:mr-auto"
              disabled={saving}
              onClick={() =>
                void save(many ? { executor_employee_ids: [] } : { accountable_employee_id: null })
              }
              data-testid="coverage-modal-assign-btn-clear"
            >
              {t("assignClear")}
            </Button>
          )}
          <Button variant="outline" onClick={onClose}>
            {t("cancel")}
          </Button>
          {many && (
            <Button
              disabled={saving}
              onClick={() => void save({ executor_employee_ids: [...selected] })}
              data-testid="coverage-modal-assign-btn-save"
            >
              {t("assignSave", { count: selected.size })}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
