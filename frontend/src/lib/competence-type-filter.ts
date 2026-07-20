// HRP-287: hide inactive Competence Types from the create / edit
// Competence selects, but keep the currently selected one in the list
// when it has been deactivated after the competence was saved —
// otherwise edit mode would silently lose the value the user previously
// chose. The deactivated type still renders on consumers (assessments,
// PDPs, etc.) because they read the type label off the stored id and
// not from a picker.

import type { DictionaryItem } from "@/lib/types";

export function visibleCompetenceTypes(
  all: DictionaryItem[],
  selectedId: string | null | undefined,
): DictionaryItem[] {
  const active = all.filter((ct) => ct.is_active);
  if (!selectedId) return active;
  if (active.some((ct) => ct.id === selectedId)) return active;
  const selected = all.find((ct) => ct.id === selectedId);
  return selected ? [...active, selected] : active;
}
