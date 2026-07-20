// HRP-158: pure helper for the "Manage grades" dialog. The modal pre-checks
// already-attached grades; the user can tick more (additions) or untick the
// pre-checked ones (removals). This function turns the current selection
// (an insertion-ordered list, used as sort_index hint for additions) and
// the original attachment set into the two diff lists the save handler
// pipes through addGrades/deleteGrade.

export interface GradeDiff {
  /** Grade IDs to attach, in the order the user ticked them. */
  toAdd: string[];
  /** Grade IDs to detach, in the order the dictionary returned them. */
  toRemove: string[];
}

export function computeGradeDiff(
  selected: readonly string[],
  alreadyAttached: ReadonlySet<string>,
): GradeDiff {
  const selectedSet = new Set(selected);
  const toAdd = selected.filter((id) => !alreadyAttached.has(id));
  const toRemove: string[] = [];
  for (const id of alreadyAttached) {
    if (!selectedSet.has(id)) toRemove.push(id);
  }
  return { toAdd, toRemove };
}
