"use client";

import { useCallback, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { cn, newClientId } from "@/lib/utils";
import { useInlineEdit, inlineEditKeys } from "@/hooks/use-inline-edit";
import { ChevronRight, Plus, Trash2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type { CompetenceItem, CompetenceQuestion } from "@/lib/types";

// HRP-134 REDO follow-up: a plain ``defaultValue`` would never refresh
// once the parent re-emits a new ``profileData`` (delete-then-shift, a
// polling refresh, etc.) — React reuses the DOM so the original mount
// value would stay on screen even though the underlying state held
// something else. We pin a ``key`` that flips whenever the prop value
// changes, forcing React to remount the input with the new initial
// value. While the user is typing, ``value`` does not change (the
// parent only sees the blurred commit), so the key stays stable and
// keystrokes are not interrupted.
function ControlledInput({
  value,
  className,
  placeholder,
  onCommit,
}: {
  value: string;
  className?: string;
  placeholder?: string;
  onCommit: (next: string) => void;
}) {
  return (
    <Input
      key={value}
      defaultValue={value}
      className={className}
      placeholder={placeholder}
      onBlur={(e) => {
        if (e.target.value !== value) onCommit(e.target.value);
      }}
    />
  );
}

function ControlledTextarea({
  value,
  className,
  onCommit,
}: {
  value: string;
  className?: string;
  onCommit: (next: string) => void;
}) {
  return (
    <Textarea
      key={value}
      defaultValue={value}
      className={className}
      onBlur={(e) => {
        if (e.target.value !== value) onCommit(e.target.value);
      }}
    />
  );
}

// HRP-318 REDO: shared shell for the ghost "+ …" affordances (add
// competence / indicator / question and the collapsed add-name state)
// so the styling and icon stay in one place.
function AddRowButton({
  label,
  testId,
  onClick,
}: {
  label: string;
  testId: string;
  onClick: () => void;
}) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      className="text-muted-foreground"
      onClick={onClick}
      data-testid={testId}
    >
      <Plus className="mr-1 size-4" />
      {label}
    </Button>
  );
}

// HRP-318 REDO: groups and subgroups are derived from the flat
// ``competences`` list, so an empty section cannot live in the payload.
// The add-name control collects the section name up front; the section
// then parks in local component state until its first competence
// materialises it into the draft.
function AddNameControl({
  label,
  cancelLabel,
  placeholder,
  testId,
  onAdd,
}: {
  label: string;
  // Already-translated aria-label for the collapse control — the two
  // call sites word it differently ("Cancel add group" / "…subgroup").
  cancelLabel: string;
  placeholder: string;
  testId: string;
  // Returns false when the name is rejected (duplicate section) — the
  // form then stays open so the user can correct it instead of retyping.
  onAdd: (name: string) => boolean;
}) {
  const t = useTranslations("recruitment");
  const field = useInlineEdit<string>(() => "");

  if (!field.editing) {
    return (
      <AddRowButton label={label} testId={testId} onClick={() => field.start()} />
    );
  }

  const submit = () => {
    const name = field.draft.trim();
    if (!name) return;
    if (onAdd(name)) field.close();
  };

  return (
    <div className="flex items-center gap-2">
      <Input
        autoFocus
        value={field.draft}
        placeholder={placeholder}
        className="h-8 max-w-xs text-sm"
        onChange={(e) => field.setDraft(e.target.value)}
        onKeyDown={inlineEditKeys({
          onCommit: submit,
          onCancel: field.cancel,
        })}
        data-testid={`${testId}-input`}
      />
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={!field.draft.trim()}
        onClick={submit}
        data-testid={`${testId}-submit`}
      >
        {t("competenceTreeAdd")}
      </Button>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="size-7 text-muted-foreground"
        onClick={field.cancel}
        aria-label={cancelLabel}
      >
        <X className="size-4" />
      </Button>
    </div>
  );
}

// HRP-134 / HRP-235 REDO: this tree now has three modes:
//   - readOnly  — display only (default; profile detail tab)
//   - editable  — inline edit + delete on every node (group → competence
//                 → indicator → question). Used by the matrix modal so
//                 the recruiter can prune AI output before saving.
//   - selectable — checkbox per competence to keep / drop, on top of
//                 editable. Used after fresh generation: the AI draft
//                 lives next to the locked previously-applied items.
interface CompetenceTreeViewProps {
  profileData: Record<string, unknown> | null;
  readOnly?: boolean;
  editable?: boolean;
  selectable?: boolean;
  // Ids of competences that are already part of the saved profile —
  // rendered with a lock chip and excluded from delete/exclude
  // controls so the recruiter cannot drop committed work.
  lockedCompetenceIds?: string[];
  selectedCompetenceIds?: string[];
  onSelectionChange?: (selected: string[]) => void;
  onChange?: (data: Record<string, unknown>) => void;
  // HRP-318 REDO: notifies the edit-lifecycle owner whether empty
  // just-added groups/subgroups exist, so its Cancel confirm can cover
  // structure the dirty check (which only sees the payload) cannot.
  onPendingChange?: (hasPending: boolean) => void;
}

// HRP-476: the wording lives in the `recruitment` i18n namespace; the
// map only owns the field → key relation.
const COMPETENCE_FIELDS: { key: keyof CompetenceItem; labelKey: string }[] = [
  { key: "why_important", labelKey: "competenceTreeFieldWhyImportant" },
  { key: "how_manifests", labelKey: "competenceTreeFieldHowManifests" },
];

// HRP-348: also consumed by the manager-assessment sheet so criticality
// chips render identically on the vacancy page and the candidate card.
//
// HRP-476: the wording lives in the `recruitment` namespace — the map
// only owns the code -> key relation, every consumer resolves it with its
// own `t` (vacancy profile tree + manager-assessment evaluation sheet).
export const criticalityConfig = {
  critical: {
    className:
      "bg-[color-mix(in_oklch,var(--rec-red-flag)_15%,transparent)] text-[var(--rec-red-flag)]",
    labelKey: "competenceTreeCriticalityCritical",
  },
  important: {
    className:
      "bg-[color-mix(in_oklch,var(--rec-data-partial)_15%,transparent)] text-[var(--rec-data-partial)]",
    labelKey: "competenceTreeCriticalityImportant",
  },
  desirable: {
    className:
      "bg-[color-mix(in_oklch,var(--rec-data-full)_15%,transparent)] text-[var(--rec-data-full)]",
    labelKey: "competenceTreeCriticalityDesirable",
  },
} as const;

const CRITICALITY_LEVELS = Object.keys(criticalityConfig) as Array<
  keyof typeof criticalityConfig
>;

interface GroupedData {
  groups: {
    name: string;
    subgroups: {
      name: string;
      competences: CompetenceItem[];
    }[];
  }[];
}

function competenceKey(comp: CompetenceItem): string {
  return comp.id || comp.name;
}

// Canonical fallback buckets for items missing group/subgroup — every
// grouping/filtering path must resolve names through these two helpers
// so a delete never disagrees with what buildTree rendered.
function groupOf(comp: CompetenceItem): string {
  return comp.group || "Other";
}

function subgroupOf(comp: CompetenceItem): string {
  return comp.subgroup || "General";
}

// TEST_IDS.md convention: testids are lowercase and dash-separated, so
// free-form group/subgroup names must be slugged before interpolation.
function testIdSlug(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

// HRP-318 REDO: shared save-path guard — every surface that persists
// profile_data (inline Save, review-dialog Apply) must refuse nameless
// competences: assessment sheets and evaluator views key their labels
// off the name.
export function findUnnamedCompetence(
  profileData: Record<string, unknown> | null,
): CompetenceItem | null {
  if (!profileData) return null;
  const competences = Array.isArray(profileData.competences)
    ? (profileData.competences as CompetenceItem[])
    : [];
  return competences.find((c) => !(c?.name || "").trim()) ?? null;
}

// HRP-318 REDO: drop indicator/question rows the recruiter added but
// never filled — downstream readers (evaluator sheet, PDF export, LLM
// prompts) render them verbatim as blank bullets otherwise.
export function sanitizeProfileData(
  profileData: Record<string, unknown>,
): Record<string, unknown> {
  const competences = Array.isArray(profileData.competences)
    ? (profileData.competences as CompetenceItem[])
    : null;
  if (!competences) return profileData;
  return {
    ...profileData,
    competences: competences.map((comp) => {
      const next = { ...comp };
      if (Array.isArray(next.indicators)) {
        next.indicators = next.indicators.filter((text) => text.trim());
      }
      if (Array.isArray(next.questions)) {
        next.questions = next.questions.filter((q) => (q.text || "").trim());
      }
      return next;
    }),
  };
}

// HRP-318 REDO: a freshly added group/subgroup that has no competences
// yet. It lives in component state only — the flat payload cannot hold
// an empty section — and is dropped once a competence materialises it
// (the dedupe below skips sections the items already produce).
export interface PendingSection {
  group: string;
  // Absent for a bare new group: it renders with only the
  // "Add subgroup" affordance inside.
  subgroup?: string;
}

export function buildTree(
  items: CompetenceItem[],
  pending: PendingSection[] = [],
): GroupedData {
  const groupMap = new Map<string, Map<string, CompetenceItem[]>>();

  for (const item of items) {
    const group = groupOf(item);
    const subgroup = subgroupOf(item);

    if (!groupMap.has(group)) groupMap.set(group, new Map());
    const subs = groupMap.get(group)!;
    if (!subs.has(subgroup)) subs.set(subgroup, []);
    subs.get(subgroup)!.push(item);
  }

  for (const section of pending) {
    if (!groupMap.has(section.group)) groupMap.set(section.group, new Map());
    if (section.subgroup) {
      const subs = groupMap.get(section.group)!;
      if (!subs.has(section.subgroup)) subs.set(section.subgroup, []);
    }
  }

  return {
    groups: Array.from(groupMap.entries()).map(([name, subMap]) => ({
      name,
      subgroups: Array.from(subMap.entries()).map(([subName, competences]) => ({
        name: subName,
        competences,
      })),
    })),
  };
}

function CollapsibleSection({
  title,
  count,
  level,
  defaultOpen = false,
  onDelete,
  children,
}: {
  title: string;
  count?: number;
  level: "group" | "subgroup";
  defaultOpen?: boolean;
  onDelete?: () => void;
  children: React.ReactNode;
}) {
  const t = useTranslations("recruitment");
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className={cn("rounded-lg border", level === "group" ? "" : "border-muted")}>
      <div className="flex items-center gap-1">
        <button
          type="button"
          className={cn(
            "flex flex-1 items-center gap-2 px-3 py-2 text-left transition-colors hover:bg-muted/50",
            level === "group" ? "text-sm font-semibold" : "text-sm font-medium",
          )}
          onClick={() => setOpen(!open)}
        >
          <ChevronRight
            className={cn("size-4 shrink-0 transition-transform", open && "rotate-90")}
          />
          <span className="flex-1">{title}</span>
          {count !== undefined && (
            <span className="text-xs text-muted-foreground">
              {t("competenceTreeCompetenceCount", { count })}
            </span>
          )}
        </button>
        {onDelete && (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="mr-2 size-7 text-muted-foreground hover:text-destructive"
            onClick={onDelete}
            aria-label={t("competenceTreeDeleteSection", { title })}
          >
            <Trash2 className="size-4" />
          </Button>
        )}
      </div>
      {open && (
        <div
          className={cn(
            "border-t px-3 py-2",
            level === "group" ? "space-y-2" : "space-y-3",
          )}
        >
          {children}
        </div>
      )}
    </div>
  );
}

function CompetenceFieldView({
  value,
  label,
  readOnly,
  onChange,
}: {
  value: string;
  label: string;
  readOnly: boolean;
  onChange?: (next: string) => void;
}) {
  if (readOnly) {
    return (
      <div className="space-y-0.5">
        <p className="text-xs font-medium text-muted-foreground">{label}</p>
        <p className="text-sm">{value || "—"}</p>
      </div>
    );
  }
  return (
    <div className="space-y-0.5">
      <label className="text-xs font-medium text-muted-foreground">{label}</label>
      <ControlledTextarea
        value={value}
        className="min-h-10 text-sm"
        onCommit={(next) => onChange?.(next)}
      />
    </div>
  );
}

function IndicatorRow({
  text,
  readOnly,
  onChange,
  onDelete,
}: {
  text: string;
  readOnly: boolean;
  onChange?: (next: string) => void;
  onDelete?: () => void;
}) {
  const t = useTranslations("recruitment");
  if (readOnly) {
    return (
      <li className="flex items-start gap-1.5 text-sm">
        <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-accent/70" />
        <span>{text}</span>
      </li>
    );
  }
  return (
    <li className="flex items-start gap-1.5">
      <span className="mt-3 size-1.5 shrink-0 rounded-full bg-accent/70" />
      <ControlledInput
        value={text}
        className="h-8 text-sm"
        onCommit={(next) => onChange?.(next)}
      />
      {onDelete && (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="size-7 text-muted-foreground hover:text-destructive"
          onClick={onDelete}
          aria-label={t("competenceTreeDeleteIndicator")}
        >
          <Trash2 className="size-4" />
        </Button>
      )}
    </li>
  );
}

function QuestionBlock({
  question,
  readOnly,
  onChange,
  onDelete,
}: {
  question: CompetenceQuestion;
  readOnly: boolean;
  onChange?: (next: CompetenceQuestion) => void;
  onDelete?: () => void;
}) {
  const t = useTranslations("recruitment");
  return (
    <div className="space-y-1 rounded border p-2">
      <div className="flex items-start gap-2">
        {readOnly ? (
          <p className="flex-1 text-sm font-medium">{question.text}</p>
        ) : (
          <ControlledInput
            value={question.text}
            className="h-8 flex-1 text-sm font-medium"
            onCommit={(next) => onChange?.({ ...question, text: next })}
          />
        )}
        {!readOnly && onDelete && (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-7 text-muted-foreground hover:text-destructive"
            onClick={onDelete}
            aria-label={t("competenceTreeDeleteQuestion")}
          >
            <Trash2 className="size-4" />
          </Button>
        )}
      </div>
      <div className="grid gap-1 sm:grid-cols-3">
        {(["good_answer", "acceptable_answer", "poor_answer"] as const).map(
          (key) => {
            const label =
              key === "good_answer"
                ? t("competenceTreeAnswerGood")
                : key === "acceptable_answer"
                  ? t("competenceTreeAnswerAcceptable")
                  : t("competenceTreeAnswerPoor");
            const value = question[key] || "";
            return (
              <div key={key} className="space-y-0.5">
                <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
                  {label}
                </p>
                {readOnly ? (
                  <p className="text-xs">{value || "—"}</p>
                ) : (
                  <ControlledTextarea
                    value={value}
                    className="min-h-8 text-xs"
                    onCommit={(next) =>
                      onChange?.({ ...question, [key]: next })
                    }
                  />
                )}
              </div>
            );
          },
        )}
      </div>
    </div>
  );
}

export function CompetenceTreeView({
  profileData,
  readOnly = true,
  editable = false,
  selectable = false,
  lockedCompetenceIds = [],
  selectedCompetenceIds,
  onSelectionChange,
  onChange,
  onPendingChange,
}: CompetenceTreeViewProps) {
  const t = useTranslations("recruitment");
  const items = useMemo<CompetenceItem[]>(() => {
    if (!profileData) return [];
    const competences = profileData.competences;
    if (Array.isArray(competences)) return competences as CompetenceItem[];
    return [];
  }, [profileData]);

  // HRP-318 REDO: sections added during this edit that have no
  // competences yet. Cleared when the tree leaves edit mode so a
  // cancelled edit does not leak placeholder sections into the next
  // one. Reset happens during render (prev-value comparison) — the
  // React-sanctioned alternative to a setState-in-effect cascade.
  const [pendingSections, setPendingSections] = useState<PendingSection[]>([]);
  const [prevEditable, setPrevEditable] = useState(editable);
  if (editable !== prevEditable) {
    setPrevEditable(editable);
    if (!editable) setPendingSections([]);
  }

  // Every pending mutation flows through here so the lifecycle owner
  // hears about it. The next-array is computed in the event handler (not
  // a functional updater) — handlers never batch two pending mutations
  // in one tick, and the callback must see the same value we commit.
  const commitPending = useCallback(
    (next: PendingSection[]) => {
      setPendingSections(next);
      onPendingChange?.(next.length > 0);
    },
    [onPendingChange],
  );

  const tree = useMemo(
    () => buildTree(items, pendingSections),
    [items, pendingSections],
  );
  const lockedSet = useMemo(
    () => new Set(lockedCompetenceIds),
    [lockedCompetenceIds],
  );

  const effectiveReadOnly = readOnly && !editable;
  // Structural edits (add group / subgroup / competence / indicator /
  // question, criticality select) stay off the selectable review dialog:
  // content born there on an unchecked row would be silently dropped by
  // the keep-or-drop apply filter.
  const canAddStructure = editable && !selectable;

  const emit = useCallback(
    (next: CompetenceItem[]) => {
      onChange?.({ ...(profileData || {}), competences: next });
    },
    [profileData, onChange],
  );

  const updateCompetence = useCallback(
    (key: string, patch: Partial<CompetenceItem>) => {
      const next = items.map((c) =>
        competenceKey(c) === key ? { ...c, ...patch } : c,
      );
      emit(next);
    },
    [items, emit],
  );

  const deleteCompetence = useCallback(
    (key: string) => {
      const victim = items.find((c) => competenceKey(c) === key);
      const remaining = items.filter((c) => competenceKey(c) !== key);
      // Deleting the last competence of a section must not collapse the
      // section mid-edit — park it as pending so the recruiter can add
      // a replacement in place instead of re-creating group + subgroup.
      if (victim && canAddStructure) {
        const group = groupOf(victim);
        const subgroup = subgroupOf(victim);
        const sectionSurvives = remaining.some(
          (c) => groupOf(c) === group && subgroupOf(c) === subgroup,
        );
        const alreadyPending = pendingSections.some(
          (s) => s.group === group && s.subgroup === subgroup,
        );
        if (!sectionSurvives && !alreadyPending) {
          commitPending([...pendingSections, { group, subgroup }]);
        }
      }
      emit(remaining);
    },
    [items, emit, canAddStructure, pendingSections, commitPending],
  );

  const deleteGroup = useCallback(
    (group: string) => {
      const nextPending = pendingSections.filter((s) => s.group !== group);
      if (nextPending.length !== pendingSections.length) {
        commitPending(nextPending);
      }
      const remaining = items.filter((c) => groupOf(c) !== group);
      if (remaining.length !== items.length) emit(remaining);
    },
    [items, emit, pendingSections, commitPending],
  );

  const deleteSubgroup = useCallback(
    (group: string, subgroup: string) => {
      const nextPending = pendingSections.filter(
        (s) => s.group !== group || s.subgroup !== subgroup,
      );
      if (nextPending.length !== pendingSections.length) {
        commitPending(nextPending);
      }
      const remaining = items.filter(
        (c) => groupOf(c) !== group || subgroupOf(c) !== subgroup,
      );
      if (remaining.length !== items.length) emit(remaining);
    },
    [items, emit, pendingSections, commitPending],
  );

  const addGroup = useCallback(
    (name: string) => {
      // buildTree dedupes by name, so a same-named section would render
      // nothing — surface why instead of silently swallowing the click.
      const exists =
        items.some((c) => groupOf(c) === name) ||
        pendingSections.some((s) => s.group === name);
      if (exists) {
        toast.info(t("competenceTreeGroupExists", { name }));
        return false;
      }
      commitPending([...pendingSections, { group: name }]);
      return true;
    },
    [items, pendingSections, commitPending, t],
  );

  const addSubgroup = useCallback(
    (group: string, name: string) => {
      const exists =
        items.some((c) => groupOf(c) === group && subgroupOf(c) === name) ||
        pendingSections.some((s) => s.group === group && s.subgroup === name);
      if (exists) {
        toast.info(t("competenceTreeSubgroupExists", { name, group }));
        return false;
      }
      commitPending([...pendingSections, { group, subgroup: name }]);
      return true;
    },
    [items, pendingSections, commitPending, t],
  );

  const addCompetence = useCallback(
    (group: string, subgroup: string) => {
      const fresh: CompetenceItem = {
        id: newClientId(),
        group,
        subgroup,
        name: "",
        criticality: "desirable",
        why_important: "",
        how_manifests: "",
        indicator_question: "",
        good_answer: "",
        acceptable_answer: "",
        poor_answer: "",
        indicators: [],
        questions: [],
      };
      emit([...items, fresh]);
    },
    [items, emit],
  );

  const toggleSelection = useCallback(
    (key: string, on: boolean) => {
      if (!onSelectionChange) return;
      const base = selectedCompetenceIds ?? items.map((c) => competenceKey(c));
      const set = new Set(base);
      if (on) set.add(key);
      else set.delete(key);
      onSelectionChange(Array.from(set));
    },
    [onSelectionChange, selectedCompetenceIds, items],
  );

  // In structural-edit mode an emptied-out tree must keep rendering so
  // the recruiter can still add a group back (or Cancel) — the dead-end
  // placeholder is for the read-only / review surfaces only.
  if (!profileData || (items.length === 0 && !canAddStructure)) {
    return (
      <div
        data-testid="recruitment-profile-tree"
        className="flex items-center justify-center rounded-lg border border-dashed p-8 text-sm text-muted-foreground"
      >
        {t("competenceTreeEmpty")}
      </div>
    );
  }

  return (
    <div data-testid="recruitment-profile-tree" className="space-y-2">
      {tree.groups.map((group) => (
        <CollapsibleSection
          key={group.name}
          title={group.name}
          count={group.subgroups.reduce(
            (sum, sg) => sum + sg.competences.length,
            0,
          )}
          level="group"
          defaultOpen
          onDelete={
            editable ? () => deleteGroup(group.name) : undefined
          }
        >
          {group.subgroups.map((subgroup) => (
            <CollapsibleSection
              key={subgroup.name}
              title={subgroup.name}
              count={subgroup.competences.length}
              level="subgroup"
              // A just-added empty subgroup opens straight away so its
              // "Add competence" affordance is visible without a click.
              defaultOpen={subgroup.competences.length === 0}
              onDelete={
                editable
                  ? () => deleteSubgroup(group.name, subgroup.name)
                  : undefined
              }
            >
              {subgroup.competences.map((comp) => {
                // Single source for the unknown-criticality fallback:
                // the chip, the select value and the select options must
                // all agree on what an out-of-enum value displays as.
                const critKey = criticalityConfig[comp.criticality]
                  ? comp.criticality
                  : "desirable";
                const crit = criticalityConfig[critKey];
                const key = competenceKey(comp);
                const locked = lockedSet.has(key);
                const selected = selectable
                  ? (selectedCompetenceIds
                      ? selectedCompetenceIds.includes(key)
                      : true) || locked
                  : true;

                // Normalise indicator / question arrays so every mode
                // (readonly + editable) renders the legacy single-question
                // fields when ``indicators[]`` / ``questions[]`` are
                // absent. The previous fallback dropped the row entirely
                // when ``indicator_question`` was empty but the answer
                // fields carried text — a regression on profiles persisted
                // before the matrix prompt rolled out (HRP-134 REDO
                // follow-up #11).
                const indicators =
                  comp.indicators && comp.indicators.length > 0
                    ? comp.indicators
                    : ([comp.indicator_question].filter(Boolean) as string[]);
                const hasLegacyAnswers = Boolean(
                  comp.indicator_question ||
                    comp.good_answer ||
                    comp.acceptable_answer ||
                    comp.poor_answer,
                );
                const questions =
                  comp.questions && comp.questions.length > 0
                    ? comp.questions
                    : hasLegacyAnswers
                      ? [
                          {
                            text: comp.indicator_question || "",
                            good_answer: comp.good_answer,
                            acceptable_answer: comp.acceptable_answer,
                            poor_answer: comp.poor_answer,
                          },
                        ]
                      : [];

                return (
                  <div
                    key={key}
                    className={cn(
                      "space-y-2 rounded-md border p-3",
                      selectable && !selected && "opacity-60",
                    )}
                    data-testid={`competence-card-${key}`}
                  >
                    <div className="flex items-start gap-2">
                      {selectable && (
                        <Checkbox
                          checked={selected}
                          disabled={locked}
                          onCheckedChange={(v) =>
                            toggleSelection(key, Boolean(v))
                          }
                          aria-label={
                            locked
                              ? t("competenceTreeLockedAria")
                              : t("competenceTreeIncludeAria")
                          }
                          data-testid={`competence-select-${key}`}
                        />
                      )}
                      <div className="flex flex-1 items-center gap-2">
                        {editable && !locked ? (
                          <ControlledInput
                            value={comp.name}
                            className="h-8 max-w-md text-sm font-medium"
                            placeholder={t("competenceTreeNamePlaceholder")}
                            onCommit={(next) =>
                              updateCompetence(key, { name: next })
                            }
                          />
                        ) : (
                          <span className="text-sm font-medium">{comp.name}</span>
                        )}
                        {canAddStructure && !locked ? (
                          <Select
                            value={critKey}
                            onValueChange={(v) =>
                              updateCompetence(key, {
                                criticality:
                                  v as CompetenceItem["criticality"],
                              })
                            }
                          >
                            <SelectTrigger
                              size="sm"
                              className={cn(
                                "h-7 w-auto gap-1 rounded-full border-none px-2.5 text-xs font-medium shadow-none",
                                crit.className,
                              )}
                              aria-label={t("competenceTreeCriticalityAria")}
                              data-testid={`competence-criticality-select-${key}`}
                            >
                              {/* Render the label, not the raw enum value
                                  the primitive falls back to. */}
                              <SelectValue>{() => t(crit.labelKey)}</SelectValue>
                            </SelectTrigger>
                            <SelectContent>
                              {CRITICALITY_LEVELS.map((level) => (
                                <SelectItem key={level} value={level}>
                                  {t(criticalityConfig[level].labelKey)}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        ) : (
                          <span
                            className={cn(
                              "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
                              crit.className,
                            )}
                          >
                            {t(crit.labelKey)}
                          </span>
                        )}
                        {locked && (
                          <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
                            {t("competenceTreeSavedChip")}
                          </span>
                        )}
                      </div>
                      {editable && !locked && (
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          className="size-7 text-muted-foreground hover:text-destructive"
                          onClick={() => deleteCompetence(key)}
                          aria-label={t("competenceTreeDeleteCompetence")}
                          data-testid={`competence-delete-${key}`}
                        >
                          <Trash2 className="size-4" />
                        </Button>
                      )}
                    </div>

                    <div className="grid gap-2 sm:grid-cols-2">
                      {COMPETENCE_FIELDS.map((field) => (
                        <CompetenceFieldView
                          key={field.key}
                          value={(comp[field.key] as string) || ""}
                          label={t(field.labelKey)}
                          readOnly={effectiveReadOnly || locked}
                          onChange={(v) =>
                            updateCompetence(key, { [field.key]: v })
                          }
                        />
                      ))}
                    </div>

                    {(indicators.length > 0 ||
                      (canAddStructure && !locked)) && (
                      <div className="space-y-1">
                        <p className="text-xs font-medium text-muted-foreground">
                          {t("competenceTreeIndicators")}
                        </p>
                        <ul className="space-y-1">
                          {indicators.map((ind, idx) => (
                            <IndicatorRow
                              key={`${key}-ind-${idx}`}
                              text={ind}
                              readOnly={effectiveReadOnly || locked}
                              onChange={(next) => {
                                const updated = [...indicators];
                                updated[idx] = next;
                                updateCompetence(key, { indicators: updated });
                              }}
                              onDelete={
                                editable && !locked
                                  ? () => {
                                      const updated = indicators.filter(
                                        (_, i) => i !== idx,
                                      );
                                      updateCompetence(key, {
                                        indicators: updated,
                                      });
                                    }
                                  : undefined
                              }
                            />
                          ))}
                        </ul>
                        {canAddStructure && !locked && (
                          <AddRowButton
                            label={t("competenceTreeAddIndicator")}
                            testId={`competence-add-indicator-${key}`}
                            onClick={() =>
                              updateCompetence(key, {
                                indicators: [...indicators, ""],
                              })
                            }
                          />
                        )}
                      </div>
                    )}

                    {(questions.length > 0 ||
                      (canAddStructure && !locked)) && (
                      <div className="space-y-1">
                        <p className="text-xs font-medium text-muted-foreground">
                          {t("competenceTreeInterviewQuestions")}
                        </p>
                        <div className="space-y-2">
                          {questions.map((q, idx) => (
                            <QuestionBlock
                              key={`${key}-q-${idx}`}
                              question={q}
                              readOnly={effectiveReadOnly || locked}
                              onChange={(next) => {
                                const updated = [...questions];
                                updated[idx] = next;
                                const patch: Partial<CompetenceItem> = {
                                  questions: updated,
                                };
                                if (idx === 0) {
                                  // Keep legacy mirrors in sync so older
                                  // readers (Canvas, exports) still work.
                                  patch.indicator_question = next.text;
                                  patch.good_answer = next.good_answer || "";
                                  patch.acceptable_answer =
                                    next.acceptable_answer || "";
                                  patch.poor_answer = next.poor_answer || "";
                                }
                                updateCompetence(key, patch);
                              }}
                              onDelete={
                                editable && !locked
                                  ? () => {
                                      const updated = questions.filter(
                                        (_, i) => i !== idx,
                                      );
                                      const patch: Partial<CompetenceItem> = {
                                        questions: updated,
                                      };
                                      if (idx === 0) {
                                        const head = updated[0];
                                        patch.indicator_question = head?.text || "";
                                        patch.good_answer =
                                          head?.good_answer || "";
                                        patch.acceptable_answer =
                                          head?.acceptable_answer || "";
                                        patch.poor_answer = head?.poor_answer || "";
                                      }
                                      updateCompetence(key, patch);
                                    }
                                  : undefined
                              }
                            />
                          ))}
                        </div>
                        {canAddStructure && !locked && (
                          <AddRowButton
                            label={t("competenceTreeAddQuestion")}
                            testId={`competence-add-question-${key}`}
                            onClick={() =>
                              updateCompetence(key, {
                                questions: [
                                  ...questions,
                                  {
                                    text: "",
                                    good_answer: "",
                                    acceptable_answer: "",
                                    poor_answer: "",
                                  },
                                ],
                              })
                            }
                          />
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
              {canAddStructure && (
                <AddRowButton
                  label={t("competenceTreeAddCompetence")}
                  testId={`competence-add-btn-${testIdSlug(group.name)}-${testIdSlug(subgroup.name)}`}
                  onClick={() => addCompetence(group.name, subgroup.name)}
                />
              )}
            </CollapsibleSection>
          ))}
          {canAddStructure && (
            <AddNameControl
              label={t("competenceTreeAddSubgroup")}
              cancelLabel={t("competenceTreeCancelAddSubgroup")}
              placeholder={t("competenceTreeSubgroupNamePlaceholder")}
              testId={`competence-add-subgroup-btn-${testIdSlug(group.name)}`}
              onAdd={(name) => addSubgroup(group.name, name)}
            />
          )}
        </CollapsibleSection>
      ))}
      {canAddStructure && (
        <AddNameControl
          label={t("competenceTreeAddGroup")}
          cancelLabel={t("competenceTreeCancelAddGroup")}
          placeholder={t("competenceTreeGroupNamePlaceholder")}
          testId="competence-add-group-btn"
          onAdd={addGroup}
        />
      )}
    </div>
  );
}
