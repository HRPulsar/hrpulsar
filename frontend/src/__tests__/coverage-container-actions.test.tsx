// @vitest-environment jsdom
//
// HRP-1228: Edit, Access, Archive and Delete of a process or a project sit
// behind one kebab, the same on its page and on its row of the list. What
// each item does is the button's old job; who sees which is in the list
// page's test.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import type { WorkContainer } from "@/lib/api/work";

const updateContainer = vi.fn();
const deleteContainer = vi.fn();

vi.mock("@/lib/api/work", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/work")>()),
  workApi: { updateContainer, deleteContainer },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
// The access dialog reads the server by itself; here it only has to open.
vi.mock("@/components/coverage/access-dialog", () => ({
  AccessDialog: () => <div data-testid="access-dialog-stub" />,
}));

const { ContainerActions } = await import("@/components/coverage/container-actions");

const CONTAINER = {
  id: "p-1",
  type: "process",
  title: "Client onboarding",
  description: "We onboard a client.",
  goal: null,
  status: "active",
  my_access: "manage",
} as WorkContainer;

const onChanged = vi.fn();
const onDeleted = vi.fn();

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  updateContainer.mockReset();
  deleteContainer.mockReset().mockResolvedValue(undefined);
  onChanged.mockReset();
  onDeleted.mockReset();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

const byId = (id: string) => document.querySelector<HTMLElement>(`[data-testid="${id}"]`);

async function render(disabled = false) {
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <ContainerActions
          container={CONTAINER}
          testIdPrefix="coverage-btn"
          disabled={disabled}
          onChanged={onChanged}
          onDeleted={onDeleted}
        />
      </NextIntlClientProvider>,
    );
  });
}

/** Open the kebab and press one of its items. */
async function pick(item: string) {
  await act(async () => byId("coverage-btn-actions")!.click());
  await act(async () => byId(`coverage-btn-${item}`)!.click());
}

it("saves an edit and hands the saved container on", async () => {
  const saved = { ...CONTAINER, title: "Client onboarding" };
  updateContainer.mockResolvedValue(saved);
  await render();

  await pick("edit");
  expect(byId("coverage-modal-edit")).not.toBeNull();
  await act(async () => byId("coverage-btn-edit-save")!.click());

  expect(updateContainer).toHaveBeenCalledExactlyOnceWith("p-1", {
    title: "Client onboarding",
    description: "We onboard a client.",
    goal: null,
  });
  expect(onChanged).toHaveBeenCalledExactlyOnceWith(saved);
  expect(byId("coverage-modal-edit")).toBeNull();
});

it("archives at once and hands the archived container on", async () => {
  const archived = { ...CONTAINER, status: "archived" };
  updateContainer.mockResolvedValue(archived);
  await render();

  await pick("archive");

  expect(updateContainer).toHaveBeenCalledExactlyOnceWith("p-1", { status: "archived" });
  expect(onChanged).toHaveBeenCalledExactlyOnceWith(archived);
});

it("deletes only after the confirm", async () => {
  await render();

  await pick("delete");
  expect(deleteContainer).not.toHaveBeenCalled();
  await act(async () => byId("coverage-btn-delete-confirm")!.click());

  expect(deleteContainer).toHaveBeenCalledExactlyOnceWith("p-1");
  expect(onDeleted).toHaveBeenCalledOnce();
});

it("opens the access dialog", async () => {
  await render();
  await pick("access");
  expect(byId("access-dialog-stub")).not.toBeNull();
});

it("keeps Archive and Delete off while the page is busy with the process", async () => {
  await render(true);
  await act(async () => byId("coverage-btn-actions")!.click());

  expect(byId("coverage-btn-archive")!.hasAttribute("data-disabled")).toBe(true);
  expect(byId("coverage-btn-delete")!.hasAttribute("data-disabled")).toBe(true);
  expect(byId("coverage-btn-edit")!.hasAttribute("data-disabled")).toBe(false);
});
