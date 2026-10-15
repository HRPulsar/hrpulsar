// HRP-824: the board's write controls follow the tenant's matrix - `manage`
// on the talent market - and each card's own `can_manage`, not the admin /
// manager role. The sidebar entry and the vacancy's "post to the market"
// button read the same source, so a role the tenant raised or lowered gets
// the buttons the API will honour, without a role change.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const read = (rel: string) => readFileSync(resolve(__dirname, rel), "utf8");
const listPage = read("../app/(dashboard)/talent-market/page.tsx");
const cardPage = read("../app/(dashboard)/talent-market/[id]/page.tsx");
const sidebar = read("../components/sidebar.tsx");
const bridge = read("../components/recruitment/internal-candidates-block.tsx");

describe("the talent market follows the section level (HRP-824)", () => {
  it("gates Create and the card menus on the level, not on a role flag", () => {
    expect(listPage).toContain('const canManage = canManageSection("talent-market");');
    expect(listPage).not.toMatch(/const \{ canManage \} = usePermissions\(\)/);
  });

  it("gates every write control on the card page on the level and the card's own flag", () => {
    expect(cardPage).toContain(
      'const canManage = canManageSection("talent-market") && card?.can_manage !== false;',
    );
    expect(cardPage).not.toContain("canManageByRole");
  });

  it("leaves the sidebar entry to the matrix alone", () => {
    expect(sidebar).not.toContain("requireEmployeeOrManage");
  });

  it("posts a vacancy only into a market open to the caller", () => {
    expect(bridge).toContain('canViewSection("talent-market")');
  });
});

// HRP-639 (QA 12.10): the Create card form offered every division of the
// tenant to a manager the API then refused. The picker reads the same
// scope the API checks (`/divisions/scope`, `assert_division_in_scope`)
// and keeps a card's current division listed even outside it.
describe("the card's Division picker offers the caller's scope (HRP-639)", () => {
  it("reads /divisions/scope and filters the options by it", () => {
    expect(listPage).toContain('api.get<{ id: string }[]>("/divisions/scope")');
    // A failed scope load is a load error, not an admin's picker silently
    // shrunk to None.
    expect(listPage).not.toContain('"/divisions/scope").catch(');
    expect(listPage).toContain("setScopeIds(new Set(scopeData.map((d) => d.id)));");
    expect(listPage).toMatch(
      /flatDivisions\s*\.filter\(\(d\) => scopeIds\.has\(d\.id\) \|\| d\.id === form\.division_id\)\s*\.map\(\(d\) => \(\s*<SelectItem/,
    );
    // The unfiltered list stays behind the trigger's label, so a current
    // division outside the scope still reads by name.
    expect(listPage).toContain("const d = flatDivisions.find((d) => d.id === form.division_id);");
  });
});
