"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { ChevronDown, ChevronRight } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { EmployeeCompetenceBreakdown } from "@/components/employees/employee-competence-breakdown";
import { BADGE_COLOR } from "@/lib/badge-tones";
import type {
  CompetenceGroupTree,
  EmployeeCompetenceRow,
} from "@/lib/types";

interface EmployeeCompetenceTreeProps {
  /** Full competence tree (origin + tenant) from useCompetenceTree(). */
  tree: CompetenceGroupTree[];
  /** Current-position rows keyed by competence_id -> row payload. */
  rows: EmployeeCompetenceRow[];
}

interface RenderedNode {
  group: CompetenceGroupTree;
  competences: { id: string; title: string; row: EmployeeCompetenceRow }[];
  children: RenderedNode[];
}

function collectGroupIdsWithRows(
  groups: CompetenceGroupTree[],
  rowsByComp: Map<string, EmployeeCompetenceRow>,
  out: Set<string>,
): boolean {
  let kept = false;
  for (const g of groups) {
    const hasDirect = (g.competences ?? []).some((c) => rowsByComp.has(c.id));
    const childKept = collectGroupIdsWithRows(g.children ?? [], rowsByComp, out);
    if (hasDirect || childKept) {
      out.add(g.id);
      kept = true;
    }
  }
  return kept;
}

function buildRenderedTree(
  groups: CompetenceGroupTree[],
  rowsByComp: Map<string, EmployeeCompetenceRow>,
  keep: Set<string>,
): RenderedNode[] {
  const result: RenderedNode[] = [];
  for (const g of groups) {
    if (!keep.has(g.id)) continue;
    const competences = (g.competences ?? [])
      .map((c) => {
        const row = rowsByComp.get(c.id);
        return row ? { id: c.id, title: c.title, row } : null;
      })
      .filter((x): x is { id: string; title: string; row: EmployeeCompetenceRow } => x !== null)
      .sort((a, b) => a.title.localeCompare(b.title));
    const children = buildRenderedTree(g.children ?? [], rowsByComp, keep);
    if (competences.length === 0 && children.length === 0) continue;
    result.push({ group: g, competences, children });
  }
  return result;
}

function PercentBadge({ percent }: { percent: number | null }) {
  if (percent === null) {
    return (
      <span className="text-sm text-muted-foreground" data-testid="competence-percent-empty">
        —
      </span>
    );
  }
  const tone =
    percent >= 75
      ? BADGE_COLOR.green
      : percent >= 50
        ? BADGE_COLOR.yellow
        : BADGE_COLOR.red;
  return (
    <span
      className={`rounded-md px-2 py-0.5 text-xs font-medium ${tone}`}
      data-testid="competence-percent"
    >
      {percent}%
    </span>
  );
}

interface BranchProps {
  node: RenderedNode;
  depth: number;
  expanded: Set<string>;
  toggle: (id: string) => void;
}

function Branch({ node, depth, expanded, toggle }: BranchProps) {
  const isOpen = expanded.has(node.group.id);
  return (
    <div>
      <button
        type="button"
        onClick={() => toggle(node.group.id)}
        className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-muted"
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
        data-testid={`employee-competence-group-toggle-${node.group.id}`}
      >
        {isOpen ? (
          <ChevronDown className="size-4" />
        ) : (
          <ChevronRight className="size-4" />
        )}
        <span className="text-sm font-medium">{node.group.title}</span>
      </button>
      {isOpen && (
        <div>
          {node.competences.map(({ id, title, row }) => (
            <div
              key={id}
              className="flex items-center justify-between gap-3 rounded-md px-2 py-1.5 hover:bg-muted/60"
              style={{ paddingLeft: `${(depth + 1) * 16 + 8}px` }}
              data-testid={`employee-competences-current-row-${id}`}
            >
              <div className="flex flex-1 items-center gap-2 text-sm">
                <span className="truncate">{title}</span>
                <Badge variant="secondary" className="shrink-0 text-xs">
                  {row.skill_level_title}
                </Badge>
              </div>
              <div className="flex items-center gap-2">
                <PercentBadge percent={row.percent} />
                <EmployeeCompetenceBreakdown
                  competenceId={id}
                  competenceTitle={title}
                  breakdown={row.level_breakdown}
                  testIdPrefix="employee-competences-current-row"
                />
              </div>
            </div>
          ))}
          {node.children.map((child) => (
            <Branch
              key={child.group.id}
              node={child}
              depth={depth + 1}
              expanded={expanded}
              toggle={toggle}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export function EmployeeCompetenceTree({
  tree,
  rows,
}: EmployeeCompetenceTreeProps) {
  const t = useTranslations("employees");
  const rowsByComp = useMemo(() => {
    const map = new Map<string, EmployeeCompetenceRow>();
    for (const row of rows) map.set(row.competence_id, row);
    return map;
  }, [rows]);

  const rendered = useMemo(() => {
    const keep = new Set<string>();
    collectGroupIdsWithRows(tree, rowsByComp, keep);
    return buildRenderedTree(tree, rowsByComp, keep);
  }, [tree, rowsByComp]);

  // Default-open the entire tree -- the spec calls out the
  // expand/collapse affordance but doesn't say it has to start collapsed,
  // and a profile glance is more useful when everything is visible.
  const [expanded, setExpanded] = useState<Set<string>>(() => {
    const ids = new Set<string>();
    const walk = (nodes: RenderedNode[]) => {
      for (const n of nodes) {
        ids.add(n.group.id);
        walk(n.children);
      }
    };
    walk(rendered);
    return ids;
  });

  const toggle = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  if (rendered.length === 0) {
    return (
      <p
        className="py-4 text-center text-sm text-muted-foreground"
        data-testid="employee-competences-current-empty"
      >
        {t("currentPositionCompetencesEmpty")}
      </p>
    );
  }

  return (
    <div className="space-y-1" data-testid="employee-competences-current-tree">
      {rendered.map((node) => (
        <Branch
          key={node.group.id}
          node={node}
          depth={0}
          expanded={expanded}
          toggle={toggle}
        />
      ))}
    </div>
  );
}
