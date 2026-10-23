import { api } from "@/lib/api";

export interface DivisionOption {
  id: string;
  name?: string;
}

function flatten(list: unknown[]): DivisionOption[] {
  const out: DivisionOption[] = [];
  for (const node of list) {
    if (!node || typeof node !== "object") continue;
    const n = node as { id?: string; name?: string; children?: unknown[] };
    if (n.id) out.push({ id: n.id, name: n.name });
    if (Array.isArray(n.children)) out.push(...flatten(n.children));
  }
  return out;
}

/** The Division picker of a vacancy (create, edit page, inline edit).
 *
 * `divisions` is the whole tree, so a stored division always has its name.
 * HRP-830 REDO: a caller who does not see all of hiring and heads divisions
 * places a vacancy in their subtree only - `allowed`, mirroring
 * `assert_vacancy_placement` in backend recruitment/scope.py. `null` when
 * any division goes (whoever sees all of hiring; a hiring manager with no
 * division, who keeps the vacancy theirs by being its hiring manager). */
export async function loadVacancyDivisions(seesAllHiring: boolean): Promise<{
  divisions: DivisionOption[];
  allowed: Set<string> | null;
}> {
  const [tree, scoped] = await Promise.all([
    api.get<unknown[]>("/divisions"),
    seesAllHiring
      ? Promise.resolve(null)
      : api.get<{ id: string }[]>("/divisions/scope").catch(() => null),
  ]);
  const ids = (scoped ?? []).map((d) => d.id);
  return {
    divisions: flatten(Array.isArray(tree) ? tree : []),
    allowed: ids.length > 0 ? new Set(ids) : null,
  };
}

/** The options to offer: the allowed ones, plus the stored one. */
export function placeableDivisions(
  divisions: DivisionOption[],
  allowed: Set<string> | null,
  current: string | null,
): DivisionOption[] {
  return allowed
    ? divisions.filter((d) => allowed.has(d.id) || d.id === current)
    : divisions;
}
