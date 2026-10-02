// @vitest-environment jsdom
//
// HRP-810 REDO: the list of processes and projects names each owner the way
// every other screen shows a person - name, position, status chip when they
// are not active - or says there is no owner. HRP-859 REDO: once a filter is
// set, a Clear button resets them all, like /assessments.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import type { WorkContainer } from "@/lib/api/work";

const listContainers = vi.fn();

vi.mock("@/lib/api/work", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/work")>()),
  workApi: { listContainers },
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
