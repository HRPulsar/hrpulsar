// HRP-632: a division head's personal competence draft. The catalogue page
// reads the tree with the drafts its viewer may see; every picker keeps the
// plain tree, where no personal draft ever appears. The page itself needs the
// API to render, so its gates are pinned by source-grep like its siblings.

import { readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMock = vi.hoisted(() => ({
  get: vi.fn<(url: string) => Promise<unknown>>(),
}));
vi.mock("@/lib/api", () => ({ api: apiMock }));

beforeEach(() => {
  vi.resetModules();
  apiMock.get.mockReset();
  apiMock.get.mockResolvedValue([]);
});

const PAGE = readFileSync(
  resolve(__dirname, "../app/(dashboard)/competences/page.tsx"),
  "utf8",
).replace(/\s+/g, " ");

describe("Personal competence drafts (HRP-632)", () => {
  it("leaves the catalogue page's tree alone until it is read", async () => {
    const mod = await import("@/hooks/use-competence-tree");
    await mod.invalidateCompetenceTree();
    expect(apiMock.get.mock.calls.map((c) => c[0])).toEqual(["/competence-tree"]);
  });

  it("reads the drafts on the catalogue page only", () => {
    expect(PAGE).toContain("useCompetenceTree({ drafts: true })");
    const root = resolve(__dirname, "..");
    const readers = readdirSync(root, { recursive: true, encoding: "utf8" })
      .filter((f) => /\.(tsx?|jsx?)$/.test(f) && !f.includes("__tests__"))
      .filter((f) => /drafts: true|drafts=true/.test(readFileSync(resolve(root, f), "utf8")));
    expect(readers.sort()).toEqual(
      ["app/(dashboard)/competences/page.tsx", "hooks/use-competence-tree.ts"].sort(),
    );
  });

  it("offers the indicators editor to the catalogue only, not to a draft's author", () => {
    expect(PAGE).toContain('{compDialogMode === "edit" && editingCompId && canManage && (');
  });

  it("lets a division head add into a group and edit and delete their own draft", () => {
    expect(PAGE).toContain("{(canEdit || canDraftCompetences) && !isOriginGroup && (");
    expect(PAGE).toContain(
      "const ownDraft = canDraftCompetences && comp.draft_owner_id === user?.id;",
    );
    expect(PAGE).toContain("{(canEdit || ownDraft) && (");
    expect(PAGE).toContain("{(canAdministerCompetences || ownDraft) && (");
  });

  it("keeps the group fixed when a division head edits their draft, and says why", () => {
    expect(PAGE).toContain('disabled={compDialogMode === "edit" && !canManage}');
    expect(PAGE).toContain('data-testid="competences-modal-competence-group-fixed"');
  });
});
