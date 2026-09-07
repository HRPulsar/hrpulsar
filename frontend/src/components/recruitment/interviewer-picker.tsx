"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { PeopleSelectList } from "@/components/people-select-list";
import type { InterviewerOption } from "@/lib/types";

interface PickerProps {
  people: InterviewerOption[];
  value: string[];
  onChange: (ids: string[]) => void;
  testId?: string;
}

/** Select-all over the rows a search left visible: once every visible row
 *  is selected, drop exactly those and keep the selections the filter is
 *  hiding; otherwise add the visible ones without duplicating. */
export function toggleAllIds(selected: string[], visible: string[]): string[] {
  const allSelected =
    visible.length > 0 && visible.every((id) => selected.includes(id));
  return allSelected
    ? selected.filter((id) => !visible.includes(id))
    : Array.from(new Set([...selected, ...visible]));
}

/** HRP-386: Interviewer(s) picker built on the same control as
 *  Exams → Assign employees — search box, bordered list with checkboxes,
 *  select-all header and a selected counter. */
export function InterviewerPicker({
  people,
  value,
  onChange,
  testId,
}: PickerProps) {
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const [search, setSearch] = useState("");

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return people;
    return people.filter((p) =>
      [p.full_name, p.email]
        .filter(Boolean)
        .some((v) => (v ?? "").toLowerCase().includes(q)),
    );
  }, [people, search]);

  const allFilteredSelected =
    filtered.length > 0 && filtered.every((p) => value.includes(p.id));

  function toggle(id: string) {
    onChange(
      value.includes(id) ? value.filter((v) => v !== id) : [...value, id],
    );
  }

  function toggleAll() {
    onChange(toggleAllIds(value, filtered.map((p) => p.id)));
  }

  return (
    <div className="space-y-2">
      <Input
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder={t("interviewerSearchPlaceholder")}
        data-testid={testId ? `${testId}-search` : undefined}
      />
      <PeopleSelectList
        rows={filtered.map((p) => ({
          id: p.id,
          name: p.full_name,
          subtitle: p.email,
        }))}
        isSelected={(id) => value.includes(id)}
        onToggle={toggle}
        loadingLabel={tc("loading")}
        emptyLabel={
          people.length === 0
            ? t("candidateInterviewsNoInterviewers")
            : t("interviewersNoMatch")
        }
        selectAll={{
          label: t("interviewersSelectAll", { count: filtered.length }),
          checked: allFilteredSelected,
          disabled: filtered.length === 0,
          onToggle: toggleAll,
          testId: testId ? `${testId}-select-all` : undefined,
        }}
        className="max-h-64"
        testId={testId}
        rowTestId={(id) => (testId ? `${testId}-option-${id}` : undefined)}
      />
      <p className="text-xs text-muted-foreground">
        {t("interviewersSelectedCount", { count: value.length })}
      </p>
    </div>
  );
}

interface DialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  people: InterviewerOption[];
  value: string[];
  saving?: boolean;
  onSave: (ids: string[]) => void;
}

/** HRP-387: the same picker as a standalone modal, opened from the pencil
 *  next to Interviewer(s) on the interview page. */
export function InterviewerPickerDialog({
  open,
  onOpenChange,
  people,
  value,
  saving,
  onSave,
}: DialogProps) {
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const [draft, setDraft] = useState<string[]>(value);

  // Re-seed each time the modal opens so a cancelled edit never leaks.
  const [seenOpen, setSeenOpen] = useState(open);
  if (open !== seenOpen) {
    setSeenOpen(open);
    if (open) setDraft(value);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="sm:max-w-2xl"
        data-testid="recruitment-interview-interviewers-dialog"
      >
        <DialogHeader>
          <DialogTitle>{t("interviewersPickerTitle")}</DialogTitle>
        </DialogHeader>
        <InterviewerPicker
          people={people}
          value={draft}
          onChange={setDraft}
          testId="recruitment-interview-interviewers-picker"
        />
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={saving}
          >
            {tc("cancel")}
          </Button>
          <Button
            onClick={() => onSave(draft)}
            disabled={saving}
            data-testid="recruitment-interview-interviewers-save"
          >
            {saving && <Loader2 className="size-4 animate-spin" />}
            {t("save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
