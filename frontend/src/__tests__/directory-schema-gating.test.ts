// HRP-623: `roles` is deliberately absent from `EmployeeDirectoryRead`, so
// the Role and Status columns of the employee list must only render for
// callers the backend answers in the full schema. Two ways that silently
// rots:
//
//   1. `canViewHrData` drifts away from the backend's `is_employee_only`
//      (a wider set here renders columns the API never sends);
//   2. someone adds `roles` / `hire_date` / `status` back to the directory
//      schema and the "trimmed" contract quietly stops being trimmed.
//
// Both sides are parsed from source rather than mocked: the point is that
// the copies agree, not that this file's own copy is self-consistent.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";

import { describe, expect, it } from "vitest";

function read(relative: string): string {
  return readFileSync(resolve(__dirname, relative), "utf8");
}

function pythonFrozenset(source: string, name: string): string[] {
  const start = source.indexOf(`${name} = frozenset(`);
  expect(start, `${name} not found`).toBeGreaterThan(-1);
  const body = source.slice(start, source.indexOf(")", start));
  return [...body.matchAll(/"(\w+)"/g)].map((m) => m[1]).sort();
}

describe("employee directory schema", () => {
  it("canViewHrData mirrors the backend's is_employee_only", () => {
    const accessScope = read("../../../backend/app/core/access_scope.py");
    const backendRoles = [
      ...pythonFrozenset(accessScope, "ADMIN_ROLE_CODES"),
      ...pythonFrozenset(accessScope, "MANAGER_ROLE_CODES"),
    ].sort();

    const hook = read("../hooks/use-permissions.ts");
    const line = hook
      .split("\n")
      .find((l) => l.trim().startsWith("canViewHrData:"));
    expect(line, "canViewHrData not found in use-permissions.ts").toBeDefined();
    // `isPlatformAdmin` → `platform_admin`, `isHr` → `hr`, and so on.
    const frontendRoles = [...line!.matchAll(/is([A-Z]\w*)/g)]
      .map((m) => m[1].replace(/([a-z0-9])([A-Z])/g, "$1_$2").toLowerCase())
      .sort();

    expect(frontendRoles).toEqual(backendRoles);
  });

  it("the directory schema carries no HR-process fields", () => {
    const schemas = read("../../../backend/app/modules/employee/schemas.py");
    const start = schemas.indexOf("class EmployeeDirectoryRead(BaseModel):");
    expect(start, "EmployeeDirectoryRead not found").toBeGreaterThan(-1);
    const body = schemas.slice(
      start,
      schemas.indexOf("class EmployeeDirectoryList", start),
    );
    for (const field of [
      "roles",
      "hire_date",
      "status",
      "alert",
      "user_first_login_at",
      "specialization_id",
    ]) {
      expect(body, `${field} leaked into the directory schema`).not.toContain(
        `\n    ${field}:`,
      );
    }
  });

  // HRP-633: /positions/{id}/employees and /specializations/{id}/employees
  // answer the trimmed directory row to a rank-and-file caller, so every
  // screen fed by one of them has to decide its column set. Omitting
  // `hrColumns` silently keeps the seven-column layout and renders four
  // permanently empty cells for exactly those callers.
  it("screens fed by a directory-capable employees route gate their columns", () => {
    const src = resolve(__dirname, "..");
    const FEEDS =
      /\/positions\/\$\{[^}]+\}\/employees|specializationsApi\.employees\(/;
    const offenders: string[] = [];
    let checked = 0;

    const walk = (dir: string) => {
      for (const entry of readdirSync(dir)) {
        const full = join(dir, entry);
        if (statSync(full).isDirectory()) {
          if (entry !== "__tests__") walk(full);
          continue;
        }
        if (!entry.endsWith(".tsx")) continue;
        const text = readFileSync(full, "utf8");
        if (!FEEDS.test(text)) continue;
        checked += 1;
        const usages = [...text.matchAll(/<EmployeeList\b[\s\S]*?\/>/g)];
        if (!usages.length) {
          // Fetches the route but renders the rows some other way — the
          // column decision then lives somewhere this check cannot see.
          offenders.push(`${full.slice(src.length + 1)} (no <EmployeeList>)`);
        }
        for (const usage of usages) {
          // The value matters, not just the prop: `hrColumns={true}` would
          // satisfy a presence check and render the HR columns anyway.
          if (!/hrColumns=\{canViewHrData\}/.test(usage[0])) {
            offenders.push(full.slice(src.length + 1));
          }
        }
      }
    };
    walk(src);

    // Guard the guard: a renamed API helper would otherwise match nothing
    // and pass silently.
    expect(checked, "no screen matched the route patterns").toBeGreaterThan(0);
    expect(
      offenders,
      "pass hrColumns={canViewHrData} — see usePermissions",
    ).toEqual([]);
  });
});
