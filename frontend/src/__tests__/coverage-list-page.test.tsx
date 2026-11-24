// @vitest-environment jsdom
//
// HRP-810 REDO: the list of processes and projects names each owner the way
// every other screen shows a person - name, position, status chip when they
// are not active - or says there is no owner. HRP-859 REDO: once a filter is
// set, a Clear button resets them all, like /assessments. HRP-1194: the
// Already automated column explains its percent.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import type { WorkContainer } from "@/lib/api/work";

const listContainers = vi.fn();
const updateContainer = vi.fn();

vi.mock("@/lib/api/work", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/work")>()),
  workApi: { listContainers, updateContainer },
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ canCreateCoverage: false }),
}));

const { default: CoveragePage } = await import("@/app/(dashboard)/coverage/page");

const ROW: WorkContainer = {
  id: "c-1",
  tenant_id: "t-1",
  type: "process",
  title: "Month-end close",
  description: null,
  goal: null,
  status: "active",
  visibility: "company",
  owner_id: "u-1",
  owner: {
    user_id: "u-1",
    name: "Alice Adams",
    position_title: "Head of Finance",
    status: "on_leave",
    active: true,
  },
  created_by_id: null,
  source: "manual",
  catalog_version: "v1.1",
  gap_default_label: "hire",
  my_access: "manage",
  coverage_summary: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  listContainers.mockReset();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function render(items: WorkContainer[]) {
  listContainers.mockResolvedValue({ items, total: items.length });
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <CoveragePage />
      </NextIntlClientProvider>,
    );
  });
}

const byId = (id: string) => document.querySelector<HTMLElement>(`[data-testid="${id}"]`);

it("names the owner with position and status, or says there is none", async () => {
  await render([
    ROW,
    { ...ROW, id: "c-2", title: "Hiring", type: "initiative", owner_id: null, owner: null },
  ]);

  const owner = byId("coverage-row-c-1-owner")!;
  expect(owner.textContent).toContain("Alice Adams");
  expect(owner.textContent).toContain("Head of Finance");
  expect(owner.textContent).toContain(enMessages.employees.statusOnLeave);
  expect(byId("coverage-row-c-2-owner")!.textContent).toBe(enMessages.coverage.accessOwnerNone);
});

// HRP-1194: the column says what its percent counts.
it("explains the Already automated column behind a question mark by its header", async () => {
  await render([ROW]);

  expect(byId("coverage-col-automated-hint")!.getAttribute("aria-label")).toBe(
    enMessages.coverage.colAutomatedHint,
  );
});

// HRP-1207 (1): what the section does is said once, by the list.
it("says how it works in a window opened from the list", async () => {
  await render([ROW]);
  expect(byId("coverage-how-dialog")).toBeNull();

  await act(async () => byId("coverage-btn-how")!.click());
  expect(byId("coverage-how-dialog")!.textContent).toContain(
    enMessages.coverage.howItWorksText,
  );

  await act(async () => byId("coverage-how-btn-ok")!.click());
  expect(byId("coverage-how-dialog")).toBeNull();
});

// HRP-1228: a row's actions sit behind a kebab, each by what the caller
// may do with that process - and a reader has no kebab at all.
it("puts a row's actions behind a kebab, by the caller's access", async () => {
  await render([
    ROW,
    { ...ROW, id: "c-edit", my_access: "edit" },
    { ...ROW, id: "c-read", my_access: "read" },
    { ...ROW, id: "c-old", status: "archived" },
  ]);
  const items = async (row: string) => {
    await act(async () => byId(`coverage-row-${row}-btn-actions`)!.click());
    const shown = ["edit", "access", "archive", "delete"].filter((name) =>
      byId(`coverage-row-${row}-btn-${name}`),
    );
    await act(async () => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    });
    return shown;
  };

  // The kebab's column has a name for a screen reader.
  expect([...document.querySelectorAll("th")].at(-1)!.textContent).toBe("Actions");
  expect(byId("coverage-row-c-read-btn-actions")).toBeNull();
  expect(await items("c-1")).toEqual(["edit", "access", "archive", "delete"]);
  expect(await items("c-edit")).toEqual(["edit", "access"]);
  expect(await items("c-old")).toEqual(["access", "delete"]);
});

it("archives from the row and reads the list again", async () => {
  await render([ROW]);
  updateContainer.mockResolvedValue({ ...ROW, status: "archived" });

  await act(async () => byId("coverage-row-c-1-btn-actions")!.click());
  await act(async () => byId("coverage-row-c-1-btn-archive")!.click());

  expect(updateContainer).toHaveBeenCalledExactlyOnceWith("c-1", { status: "archived" });
  expect(listContainers).toHaveBeenCalledTimes(2);
});

async function type(el: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
  await act(async () => {
    setter.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

it("offers Clear only while a filter is set, and Clear resets them", async () => {
  await render([ROW, { ...ROW, id: "c-2", title: "Hiring", type: "initiative" }]);

  expect(byId("coverage-btn-clear-filters")).toBeNull();

  await type(byId("coverage-input-search") as HTMLInputElement, "month");
  expect(byId("coverage-row-c-2")).toBeNull();
  const clear = byId("coverage-btn-clear-filters")!;
  expect(clear.textContent).toContain(enMessages.common.clear);

  await act(async () => {
    clear.click();
  });
  expect(byId("coverage-btn-clear-filters")).toBeNull();
  expect((byId("coverage-input-search") as HTMLInputElement).value).toBe("");
  expect(byId("coverage-row-c-2")).not.toBeNull();
});
