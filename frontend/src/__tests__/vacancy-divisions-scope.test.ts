// HRP-830 REDO (QA 14.10): a manager who runs hiring on their divisions
// places a vacancy in their own subtree - the Division picker offers it,
// plus the vacancy's stored division so its name still shows.

import { describe, expect, it, vi } from "vitest";

const get = vi.fn((url: string) => {
  if (url === "/divisions")
    return Promise.resolve([
      { id: "root", name: "Root", children: [{ id: "mine", name: "Mine", children: [{ id: "sub", name: "Sub" }] }] },
      { id: "theirs", name: "Theirs" },
    ]);
  if (url === "/divisions/scope") return Promise.resolve(scope);
  return Promise.reject(new Error(url));
});
let scope: { id: string }[] = [];

vi.mock("@/lib/api", () => ({ api: { get: (url: string) => get(url) } }));

const { loadVacancyDivisions, placeableDivisions } = await import(
  "@/components/recruitment/vacancy-divisions"
);

const ids = (list: { id: string }[]) => list.map((d) => d.id);

describe("the vacancy Division picker (HRP-830 REDO)", () => {
  it("offers a manager their subtree and the stored division", async () => {
    scope = [{ id: "mine" }, { id: "sub" }];
    const { divisions, allowed } = await loadVacancyDivisions(false);
    expect(ids(divisions)).toEqual(["root", "mine", "sub", "theirs"]);
    expect(ids(placeableDivisions(divisions, allowed, null))).toEqual(["mine", "sub"]);
    expect(ids(placeableDivisions(divisions, allowed, "theirs"))).toEqual(["mine", "sub", "theirs"]);
  });

  it("offers every division to whoever sees all of hiring, without asking the scope", async () => {
    get.mockClear();
    const { divisions, allowed } = await loadVacancyDivisions(true);
    expect(allowed).toBeNull();
    expect(ids(placeableDivisions(divisions, allowed, null))).toHaveLength(4);
    expect(get.mock.calls.map(([u]) => u)).toEqual(["/divisions"]);
  });

  it("offers every division to a hiring manager who heads none", async () => {
    scope = [];
    const { divisions, allowed } = await loadVacancyDivisions(false);
    expect(allowed).toBeNull();
    expect(ids(placeableDivisions(divisions, allowed, null))).toHaveLength(4);
  });
});
