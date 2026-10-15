// @vitest-environment jsdom
//
// HRP-827, QA 13.10: `view` on dictionaries opens the page read-only - the
// list renders, the add button and the row menu do not. `manage` edits.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";

let sections: Record<string, string> = {};
const replace = vi.fn();

vi.mock("next/navigation", () => ({
  usePathname: () => "/dictionaries",
  useRouter: () => ({ replace, push: vi.fn() }),
}));

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({
    user: { id: "u-1", first_name: "T", last_name: "U", roles: ["manager"], sections },
    loading: false,
  }),
}));

vi.mock("@/lib/api", () => ({
  api: {
    get: vi.fn(async () => [
      {
        id: "item-1",
        tenant_id: "t-1",
        type: "grade",
        title: "Staff",
        description: null,
        sort_index: 1,
        is_active: true,
      },
    ]),
  },
}));

const { default: DictionariesPage } = await import("@/app/(dashboard)/dictionaries/page");

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  replace.mockClear();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function renderWith(level: string) {
  sections = { dictionaries: level };
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <DictionariesPage />
      </NextIntlClientProvider>,
    );
  });
}

const byTestId = (id: string) => container.querySelector(`[data-testid="${id}"]`);

describe("dictionaries page by section level (HRP-827)", () => {
  it("opens read-only at view", async () => {
    await renderWith("view");
    expect(replace).not.toHaveBeenCalled();
    expect(byTestId("dictionaries-item-item-1")).not.toBeNull();
    expect(byTestId("dictionaries-btn-add")).toBeNull();
    expect(byTestId("dictionaries-item-item-1")!.querySelector("button")).toBeNull();
  });

  it("edits at manage", async () => {
    await renderWith("manage");
    expect(byTestId("dictionaries-btn-add")).not.toBeNull();
    expect(byTestId("dictionaries-item-item-1")!.querySelector("button")).not.toBeNull();
  });
});
