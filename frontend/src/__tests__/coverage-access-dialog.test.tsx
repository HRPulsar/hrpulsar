// @vitest-environment jsdom
//
// 2.0.0 review §3 — the access dialog of a process: the owner picker and
// the rule picker shared one search box and one unfiltered list, and a
// person with no name on record produced a chip with nothing in it.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import type { ContainerAccess, ProcessPerson } from "@/lib/api/work";

const getAccess = vi.fn();
const listPeople = vi.fn();

vi.mock("@/lib/api/work", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/work")>()),
  workApi: { getAccess, listPeople, setAccess: vi.fn(), updateContainer: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const { AccessDialog } = await import("@/components/coverage/access-dialog");

const ACCESS: ContainerAccess = {
  visibility: "restricted",
  owner: { user_id: "u-1", name: "Alice Adams", active: true },
  // A person the directory has no name for: the chip must still say who.
  rules: [{ role_code: null, position_id: null, employee_id: "e-2", label: "" }],
  history: [],
};

const PEOPLE: ProcessPerson[] = [
  {
    employee_id: "e-1",
    user_id: "u-1",
    name: "Alice Adams",
    email: "alice@example.com",
    position_title: "Head of Finance",
    assignable: true,
  },
  {
    employee_id: "e-2",
    user_id: "u-2",
    name: "",
    email: "bob@example.com",
    position_title: null,
    // Gone from the company: cannot be handed a process.
    assignable: false,
  },
];

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  getAccess.mockReset().mockResolvedValue(ACCESS);
  listPeople.mockReset().mockResolvedValue(PEOPLE);
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function render() {
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <AccessDialog
          containerId="c-1"
          canChangeOwner
          onClose={() => {}}
          onOwnerChanged={() => {}}
        />
      </NextIntlClientProvider>,
    );
  });
}

function byTestId(testId: string): HTMLElement {
  const el = document.querySelector(`[data-testid="${testId}"]`) as HTMLElement;
  expect(el, testId).toBeTruthy();
  return el;
}

async function click(testId: string) {
  const el = byTestId(testId);
  await act(async () => {
    el.click();
  });
}

async function type(el: HTMLInputElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

it("offers only people at work as the next owner", async () => {
  await render();
  await click("coverage-access-btn-owner");

  // Bob has left the company: he is in the directory, not in this list.
  const list = byTestId("coverage-access-owner-list").textContent ?? "";
  expect(list).toContain("Alice Adams");
  expect(list).not.toContain("bob@example.com");
});

it("names a rule with no name by the person behind it", async () => {
  await render();

  expect(byTestId("coverage-access-rule-employee-e-2").textContent).toContain("e-2");
});

it("filters the owner list by its own search box", async () => {
  await render();
  await click("coverage-access-btn-owner");
  await type(byTestId("coverage-access-owner-search") as HTMLInputElement, "nobody");

  expect(byTestId("coverage-access-owner-list").textContent).not.toContain("Alice Adams");

  await type(byTestId("coverage-access-owner-search") as HTMLInputElement, "alice");

  expect(byTestId("coverage-access-owner-list").textContent).toContain("Alice Adams");
  // The rule picker's own box is a second state (`ruleSearch`); its list
  // sits behind a base-ui select that jsdom cannot open, so the separation
  // is not asserted here.
});
