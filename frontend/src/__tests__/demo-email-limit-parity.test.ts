// A demo tells its visitor how many people it will email, so each page's
// limit must be the number the backend actually enforces: HRP-806 for the
// set-password emails of an import, HRP-813 for invitations. A Next.js page
// module cannot export a constant, so both sides are read as source.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

function limitIn(path: string, pattern: RegExp): number {
  const match = readFileSync(resolve(__dirname, path), "utf8").match(pattern);
  expect(match, `${pattern} not found in ${path}`).not.toBeNull();
  return Number(match![1]);
}

describe("demo email limits", () => {
  it("import page matches the import task", () => {
    const backend = limitIn(
      "../../../backend/app/modules/data_import/tasks.py",
      /^DEMO_IMPORT_EMAIL_LIMIT = (\d+)$/m,
    );
    const frontend = limitIn(
      "../app/(dashboard)/settings/import/page.tsx",
      /^const DEMO_IMPORT_EMAIL_LIMIT = (\d+);$/m,
    );
    expect(frontend).toBe(backend);
  });

  it("invitations page matches the invitation service", () => {
    const backend = limitIn(
      "../../../backend/app/modules/auth/service.py",
      /^DEMO_INVITATION_LIMIT = (\d+)$/m,
    );
    const frontend = limitIn(
      "../app/(dashboard)/settings/invitations/page.tsx",
      /^const DEMO_INVITATION_LIMIT = (\d+);$/m,
    );
    expect(frontend).toBe(backend);
  });
});
