import type { CompetenceGroupTree } from "@/lib/types";

/** The groups and competences a search on `/competences` keeps on screen. */
export interface CompetenceTreeMatch {
  groups: Set<string>;
  competences: Set<string>;
}

/**
 * HRP-1082: a group whose title matches keeps everything under it; a
 * competence that matches keeps itself and the groups above it. `null` when
 * there is nothing to search for - the whole tree shows.
 *
 * Ids, not a pruned copy of the tree: the page hands the group objects to
 * its actions (AI fill/extend, bulk add, delete), and those must see the
 * group as it is, not as the search trimmed it.
 */
export function matchCompetenceTree(
  tree: CompetenceGroupTree[],
  query: string,
): CompetenceTreeMatch | null {
  const q = query.trim().toLocaleLowerCase();
  if (!q) return null;
  const match: CompetenceTreeMatch = { groups: new Set(), competences: new Set() };
  const hit = (title: string) => title.toLocaleLowerCase().includes(q);
  const keepAll = (g: CompetenceGroupTree) => {
    match.groups.add(g.id);
    for (const c of g.competences) match.competences.add(c.id);
    g.children.forEach(keepAll);
  };
  const walk = (g: CompetenceGroupTree): boolean => {
    if (hit(g.title)) {
      keepAll(g);
      return true;
    }
    let found = false;
    for (const c of g.competences) {
      if (hit(c.title)) {
        match.competences.add(c.id);
        found = true;
      }
    }
    for (const child of g.children) found = walk(child) || found;
    if (found) match.groups.add(g.id);
    return found;
  };
  tree.forEach(walk);
  return match;
}
