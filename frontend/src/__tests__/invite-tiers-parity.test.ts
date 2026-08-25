// HRP-618: the invitations page hides role options the backend would reject,
// so its INVITE_ALLOWED must be a copy of `_INVITE_ALLOWED` in
// backend/app/modules/auth/service.py. Drift is invisible until a user picks
// a role and gets a 403 `role_above_inviter` — this guard parses both sides
// and compares them.
//
// The `platform_admin` tier is skipped on purpose: the backend gets it from
// the enterprise rbac_hooks seam (backend/ee/rbac.py), which does not exist
// in the public repo this test is synced to.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

const ENTERPRISE_ONLY_TIERS = ["platform_admin"];

function parsePythonTiers(source: string): Record<string, string[]> {
  const start = source.indexOf("_INVITE_ALLOWED: dict[str, frozenset[str]] = {");
  expect(start, "_INVITE_ALLOWED not found in auth/service.py").toBeGreaterThan(-1);
  const end = source.indexOf("\n}", start);
  const body = source.slice(source.indexOf("{", start) + 1, end);
  const tiers: Record<string, string[]> = {};
  for (const [, key, values] of body.matchAll(
    /"(\w+)":\s*frozenset\(\s*\{([^}]*)\}/g,
  )) {
    tiers[key] = [...values.matchAll(/"(\w+)"/g)].map((m) => m[1]).sort();
  }
  return tiers;
}

function parseTsTiers(source: string): Record<string, string[]> {
  const start = source.indexOf("const INVITE_ALLOWED");
  expect(start, "INVITE_ALLOWED not found in the invitations page").toBeGreaterThan(-1);
  const body = source.slice(start, source.indexOf("\n};", start));
  const tiers: Record<string, string[]> = {};
  for (const [, key, values] of body.matchAll(/(\w+):\s*new Set\(\[([^\]]*)\]/g)) {
    tiers[key] = [...values.matchAll(/"(\w+)"/g)].map((m) => m[1]).sort();
  }
  return tiers;
}

describe("invitation tiers", () => {
  it("frontend INVITE_ALLOWED matches backend _INVITE_ALLOWED", () => {
    const python = parsePythonTiers(
      readFileSync(
        resolve(__dirname, "../../../backend/app/modules/auth/service.py"),
        "utf8",
      ),
    );
    const ts = parseTsTiers(
      readFileSync(
        resolve(__dirname, "../app/(dashboard)/settings/invitations/page.tsx"),
        "utf8",
      ),
    );
    for (const tier of ENTERPRISE_ONLY_TIERS) delete ts[tier];

    expect(Object.keys(python).sort()).toEqual(["admin", "hr", "manager"]);
    expect(ts).toEqual(python);
  });
});
