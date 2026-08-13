// HRP-550: the platform-admin bounce lived inside (dashboard)/layout.tsx,
// so the (fullscreen) shell added by HRP-510 — same AuthProvider, no app
// chrome — let a platform admin render a tenant-scoped canvas instead of
// being sent to their own console. The guard is now one shared component
// and both authenticated shells wrap their tree in it.
//
// Structural test: mounting either layout drags in the whole auth + router
// data layer, so the contract is pinned by source-grep like its siblings.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const read = (path: string) =>
  readFileSync(resolve(__dirname, path), "utf8").replace(/\s+/g, " ");

const GUARD = read("../components/platform-admin-redirect.tsx");
const DASHBOARD = read("../app/(dashboard)/layout.tsx");
const FULLSCREEN = read("../app/(fullscreen)/layout.tsx");

describe("Platform-admin redirect (HRP-550)", () => {
  it("lives in one shared component", () => {
    expect(GUARD).toContain("export function PlatformAdminRedirect");
    expect(GUARD).toContain('router.replace("/platform")');
    expect(GUARD).toContain("user?.is_platform_admin");
  });

  for (const [name, source] of [
    ["dashboard", DASHBOARD],
    ["fullscreen", FULLSCREEN],
  ] as const) {
    it(`the ${name} shell imports and applies it`, () => {
      expect(source).toContain(
        'import { PlatformAdminRedirect } from "@/components/platform-admin-redirect"',
      );
      expect(source).toContain("<PlatformAdminRedirect>");
      expect(source).toContain("</PlatformAdminRedirect>");
    });

    it(`the ${name} shell keeps the guard inside the AuthProvider`, () => {
      const provider = source.indexOf("<AuthProvider>");
      const guard = source.indexOf("<PlatformAdminRedirect>");
      expect(provider).toBeGreaterThan(-1);
      expect(guard).toBeGreaterThan(provider);
    });
  }

  it("no longer defines a second copy inside the dashboard layout", () => {
    expect(DASHBOARD).not.toContain("function PlatformAdminRedirect(");
  });
});
