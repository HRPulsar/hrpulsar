"use client";

// HRP-809: name the person who does a step, or the one who checks and
// signs it. One active employee or nobody; matching skills are not
// required - the Coverage row shows which ones are missing.

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
import { type ProcessPerson, type StepPatch, type WorkStep, workApi } from "@/lib/api/work";

export type AssigneeField = "executor_employee_id" | "accountable_employee_id";

export function AssignPersonDialog({
  containerId,
  stepId,
  field,
  currentId,
  onClose,
  onSaved,
}: {
  containerId: string;
  stepId: string;
  field: AssigneeField;
  currentId: string | null;
  onClose: () => void;
  onSaved: (step: WorkStep) => void;
}) {
  const t = useTranslations("coverage");
  const tc = useTranslations("common");
  const [people, setPeople] = useState<ProcessPerson[] | null>(null);
  const [search, setSearch] = useState("");
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    // HRP-810: the process's own list - an owner who is not HR still sees
    // the whole company, and only people at work can take a step.
    workApi
      .listPeople(containerId)
      .then((res) => !cancelled && setPeople(res.filter((p) => p.assignable)))
      // An error, not the "no employees yet" empty state.
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
    };
  }, [containerId]);

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
      }));
  }, [people, search]);

  async function save(employeeId: string | null) {
    if (employeeId === currentId) {
      onClose();
      return;
    }
    setSaving(true);
    try {
      const step = await workApi.updateStep(stepId, { [field]: employeeId } as StepPatch);
      toast.success(t("assignSaved"));
      onSaved(step);
      onClose();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("saveFailed"));
      setSaving(false);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-lg" data-testid="coverage-modal-assign" data-field={field}>
        <DialogHeader>
          <DialogTitle>
            {field === "executor_employee_id" ? t("assignExecutorTitle") : t("assignAccountableTitle")}
          </DialogTitle>
          <DialogDescription>{t("assignText")}</DialogDescription>
        </DialogHeader>
        <Input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t("assignSearchPlaceholder")}
          data-testid="coverage-modal-assign-search"
        />
        <PeopleSelectList
          rows={rows.map((row) => ({ ...row, disabled: saving }))}
          isSelected={(id) => id === currentId}
          onToggle={(id) => void save(id)}
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
          {currentId && (
            <Button
              variant="outline"
              className="sm:mr-auto"
              disabled={saving}
              onClick={() => void save(null)}
              data-testid="coverage-modal-assign-btn-clear"
            >
              {t("assignClear")}
            </Button>
          )}
          <Button variant="outline" onClick={onClose}>
            {t("cancel")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
