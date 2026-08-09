"use client";

// HRP-485 task 3: pick one or more competences from the vacancy's
// Competences & indicators tree and turn each into a question.
//
// The mapping from competence to question is fixed by the ticket:
//   criticality      -> priority (critical/important/desirable)
//   first question   -> question text
//   other questions  -> follow-ups
//   indicators       -> expected indicators
//   why_important    -> why this question (rationale)
// and the competence id rides along so the question stays linked to the
// profile competence (HRP-503).

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { ChevronRight, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  competenceQuestionTexts,
  competenceToQuestion,
  isUsableCompetence,
} from "@/lib/competence-question";
import type { CompetenceItem } from "@/lib/types";
import type { NewQuestionPayload } from "./question-payload";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  competences: CompetenceItem[];
  onSubmit: (payloads: NewQuestionPayload[]) => void;
}

interface TreeNode {
  key: string;
  label: string;
  children: TreeNode[];
  competences: CompetenceItem[];
}

const UNGROUPED = "—";

/** Stable per-competence key — profile ids are optional on old rows.
 *
 * ``idx`` must be the row's position in the full profile list, never in a
 * filtered view: keys built off the search results shifted under the user
 * as they typed, so ticked rows appeared to clear and were dropped on Add.
 */
function competenceKey(c: CompetenceItem, idx: number): string {
  return c.id || `${c.group}|${c.subgroup}|${c.name}|${idx}`;
}

function buildTree(competences: CompetenceItem[]): TreeNode[] {
  const groups = new Map<string, Map<string, CompetenceItem[]>>();
  for (const c of competences) {
    const g = (c.group || "").trim() || UNGROUPED;
    const s = (c.subgroup || "").trim() || UNGROUPED;
    if (!groups.has(g)) groups.set(g, new Map());
    const sub = groups.get(g)!;
    if (!sub.has(s)) sub.set(s, []);
    sub.get(s)!.push(c);
  }
  return [...groups.entries()].map(([g, subs]) => ({
    key: g,
    label: g,
    competences: [],
    children: [...subs.entries()].map(([s, items]) => ({
      key: `${g}|${s}`,
      label: s,
      children: [],
      competences: items,
    })),
  }));
}

export function AddFromCompetencyDialog({
  open,
  onOpenChange,
  competences,
  onSubmit,
}: Props) {
  const t = useTranslations("recruitment");
  const tc = useTranslations("common");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [expandedDetail, setExpandedDetail] = useState<Set<string>>(new Set());

  // Only competences that actually carry a question can become one.
  const usable = useMemo(
    () => competences.filter(isUsableCompetence),
    [competences],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return usable;
    return usable.filter((c) =>
      [c.name, c.group, c.subgroup, c.why_important, ...(c.indicators || [])]
        .filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(q)),
    );
  }, [usable, query]);

  const tree = useMemo(() => buildTree(filtered), [filtered]);

  function reset() {
    setQuery("");
    setSelected(new Set());
    setCollapsed(new Set());
    setExpandedDetail(new Set());
  }

  function toggle(set: Set<string>, key: string): Set<string> {
    const next = new Set(set);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    return next;
  }

  const allKeys = useMemo(() => {
    const keys: string[] = [];
    for (const g of tree) {
      keys.push(g.key);
      for (const s of g.children) keys.push(s.key);
    }
    return keys;
  }, [tree]);

  // Both maps are keyed off the untouched `competences` list, so a key
  // means the same competence no matter what the search box holds.
  const keyOf = useMemo(() => {
    const m = new Map<CompetenceItem, string>();
    competences.forEach((c, i) => m.set(c, competenceKey(c, i)));
    return m;
  }, [competences]);

  const byKey = useMemo(() => {
    const m = new Map<string, CompetenceItem>();
    competences.forEach((c, i) => m.set(competenceKey(c, i), c));
    return m;
  }, [competences]);

  function handleAdd() {
    const picked = [...selected]
      .map((k) => byKey.get(k))
      .filter((c): c is CompetenceItem => Boolean(c));
    onSubmit(picked.map(competenceToQuestion));
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) reset();
        onOpenChange(o);
      }}
    >
      <DialogContent
        className="flex max-h-[85vh] max-w-3xl flex-col"
        data-testid="recruitment-interview-questions-competency-dialog"
      >
        <DialogHeader>
          <DialogTitle>{t("questionSetsCompetencyDialogTitle")}</DialogTitle>
        </DialogHeader>

        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-56 flex-1">
            <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              className="pl-8"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t("questionSetsCompetencySearch")}
              data-testid="recruitment-interview-questions-competency-search"
            />
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setCollapsed(new Set())}
            data-testid="recruitment-interview-questions-competency-expand-all"
          >
            {tc("expandAll")}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setCollapsed(new Set(allKeys))}
            data-testid="recruitment-interview-questions-competency-collapse-all"
          >
            {tc("collapseAll")}
          </Button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto rounded-md border p-2">
          {!usable.length ? (
            <p className="p-4 text-sm text-muted-foreground">
              {t("questionSetsCompetencyEmpty")}
            </p>
          ) : !filtered.length ? (
            <p className="p-4 text-sm text-muted-foreground">
              {t("questionSetsCompetencyNoMatch")}
            </p>
          ) : (
            tree.map((group) => (
              <div key={group.key} className="mb-1">
                <button
                  type="button"
                  className="flex w-full items-center gap-1 rounded px-1 py-1 text-left text-sm font-semibold hover:bg-muted/50"
                  onClick={() => setCollapsed((s) => toggle(s, group.key))}
                >
                  <ChevronRight
                    className={`h-4 w-4 transition ${collapsed.has(group.key) ? "" : "rotate-90"}`}
                  />
                  {group.label}
                </button>
                {!collapsed.has(group.key) &&
                  group.children.map((sub) => (
                    <div key={sub.key} className="ml-4">
                      <button
                        type="button"
                        className="flex w-full items-center gap-1 rounded px-1 py-1 text-left text-sm font-medium text-muted-foreground hover:bg-muted/50"
                        onClick={() => setCollapsed((s) => toggle(s, sub.key))}
                      >
                        <ChevronRight
                          className={`h-4 w-4 transition ${collapsed.has(sub.key) ? "" : "rotate-90"}`}
                        />
                        {sub.label}
                      </button>
                      {!collapsed.has(sub.key) && (
                        <ul className="ml-5 space-y-1">
                          {sub.competences.map((c) => {
                            const key =
                              keyOf.get(c) ??
                              competenceKey(c, competences.indexOf(c));
                            const texts = competenceQuestionTexts(c);
                            const showDetail = expandedDetail.has(key);
                            return (
                              <li key={key} className="rounded border p-2">
                                <div className="flex items-start gap-2">
                                  <Checkbox
                                    checked={selected.has(key)}
                                    onCheckedChange={() =>
                                      setSelected((s) => toggle(s, key))
                                    }
                                    aria-label={c.name}
                                    data-testid={`recruitment-interview-questions-competency-item-${key}`}
                                  />
                                  <div className="min-w-0 flex-1">
                                    <button
                                      type="button"
                                      className="block text-left text-sm font-medium"
                                      onClick={() =>
                                        setExpandedDetail((s) => toggle(s, key))
                                      }
                                    >
                                      {c.name}
                                    </button>
                                    <p className="text-xs text-muted-foreground">
                                      {c.criticality}
                                    </p>
                                    {showDetail && (
                                      <div className="mt-2 space-y-2 rounded bg-muted/40 p-2 text-xs">
                                        {c.why_important && (
                                          <div>
                                            <p className="font-medium">
                                              {t("questionSetsWhyImportant")}
                                            </p>
                                            <p className="text-muted-foreground">
                                              {c.why_important}
                                            </p>
                                          </div>
                                        )}
                                        {(c.indicators || []).length > 0 && (
                                          <div>
                                            <p className="font-medium">
                                              {t("questionSetsExpectedIndicators")}
                                            </p>
                                            <ul className="ml-4 list-disc">
                                              {(c.indicators || []).map((i, n) => (
                                                <li key={n}>{i}</li>
                                              ))}
                                            </ul>
                                          </div>
                                        )}
                                        <div>
                                          <p className="font-medium">
                                            {t("questionSetsCompetencyQuestions")}
                                          </p>
                                          <ul className="ml-4 list-disc">
                                            {texts.map((q, n) => (
                                              <li key={n}>{q}</li>
                                            ))}
                                          </ul>
                                        </div>
                                      </div>
                                    )}
                                  </div>
                                </div>
                              </li>
                            );
                          })}
                        </ul>
                      )}
                    </div>
                  ))}
              </div>
            ))
          )}
        </div>

        <DialogFooter className="items-center justify-between gap-2 sm:justify-between">
          <span className="text-xs text-muted-foreground">
            {t("questionSetsCompetencySelected", { count: selected.size })}
          </span>
          <span className="flex gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              {tc("cancel")}
            </Button>
            <Button
              onClick={handleAdd}
              disabled={selected.size === 0}
              data-testid="recruitment-interview-questions-competency-submit"
            >
              {t("questionSetsAddSubmit")}
            </Button>
          </span>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
