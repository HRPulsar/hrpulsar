"use client";

import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";

import { MatchPercentChip } from "@/components/assessment/match-percent-chip";
import { useCompetenceTree } from "@/hooks/use-competence-tree";
import type { CompetenceGroupTree } from "@/lib/types";

interface RenderedNode {
  group: CompetenceGroupTree;
  competences: { id: string; title: string; percent: number | null }[];
  children: RenderedNode[];
}

function buildTree(
  groups: CompetenceGroupTree[],
  averages: Map<string, number | null>,
): RenderedNode[] {
  const out: RenderedNode[] = [];
  for (const group of groups) {
    const competences = (group.competences ?? [])
      .filter((c) => averages.has(c.id))
      .map((c) => ({
        id: c.id,
        title: c.title,
        percent: averages.get(c.id) ?? null,
      }))
      .sort((a, b) => a.title.localeCompare(b.title));
    const children = buildTree(group.children ?? [], averages);
    if (competences.length === 0 && children.length === 0) continue;
    out.push({ group, competences, children });
  }
  return out;
}

function collectIds(nodes: RenderedNode[], into: Set<string>) {
  for (const node of nodes) {
    into.add(node.group.id);
    collectIds(node.children, into);
  }
}

function Branch({
  node,
  depth,
  expanded,
  toggle,
}: {
  node: RenderedNode;
  depth: number;
  expanded: Set<string>;
  toggle: (id: string) => void;
}) {
  const isOpen = expanded.has(node.group.id);
  return (
    <div>
      <button
        type="button"
        onClick={() => toggle(node.group.id)}
        className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-muted"
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
        data-testid={`group-analytics-tree-toggle-${node.group.id}`}
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
          {node.competences.map((competence) => (
            <div
              key={competence.id}
              className="flex items-center justify-between gap-3 rounded-md px-2 py-1.5 hover:bg-muted/60"
              style={{ paddingLeft: `${(depth + 1) * 16 + 8}px` }}
              data-testid={`group-analytics-tree-row-${competence.id}`}
            >
              <span className="min-w-0 flex-1 truncate text-sm">
                {competence.title}
              </span>
              <MatchPercentChip percent={competence.percent} />
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

/**
 * Competence tree carrying the group's average result per competence —
 * the same shape as the employee profile's Competences tab.
 */
export function CompetenceResultsTree({
  averages,
}: {
  averages: Map<string, number | null>;
}) {
  const t = useTranslations("assessments");
  const { tree } = useCompetenceTree();

  const rendered = useMemo(() => buildTree(tree, averages), [tree, averages]);

  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const expanded = useMemo(() => {
    const ids = new Set<string>();
    collectIds(rendered, ids);
    for (const id of collapsed) ids.delete(id);
    return ids;
  }, [rendered, collapsed]);

  const toggle = (id: string) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  if (rendered.length === 0) {
    return (
      <p
        className="text-sm text-muted-foreground"
        data-testid="group-analytics-tree-empty"
      >
        {t("analyticsNoData")}
      </p>
    );
  }

  return (
    <div className="space-y-1" data-testid="group-analytics-tree">
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
