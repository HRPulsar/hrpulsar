// @vitest-environment jsdom
//
// The import preview of a long file carries only its first rows: the page
// counts rows and problems from the totals the backend sends for the whole
// file, and says the table shows only the first rows.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";

const PREVIEW = {
  columns: ["email", "first_name", "last_name", "position", "hire_date"],
  rows: [
    { line: 2, cells: ["a@test.com", "A", "B", "Dev", "2024-01-15"], problem: null },
    { line: 3, cells: ["b@test.com", "B", "C", "Dev", "2024-01-15"], problem: null },
  ],
  total_rows: 250,
  problem_rows: 7,
};

const uploadMock = vi.fn(() => Promise.resolve(PREVIEW));

vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {},
  api: {
    get: vi.fn(() => Promise.resolve({ items: [], total: 0 })),
    upload: uploadMock,
  },
}));

vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({
    canImport: true,
    canViewSection: () => true,
    canManageSection: () => true,
  }),
}));

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ user: { id: "u-1", sections: { import: "manage" } }, loading: false }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

const ImportPage = (await import("@/app/(dashboard)/settings/import/page")).default;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("import preview of a long file", () => {
  it("counts the whole file and says only the first rows are shown", async () => {
    await act(async () => {
      root.render(
        <NextIntlClientProvider locale="en" messages={enMessages}>
          <ImportPage />
        </NextIntlClientProvider>,
      );
    });
    const input = container.querySelector<HTMLInputElement>("input[type='file']");
    expect(input).not.toBeNull();
    const file = new File(["x"], "people.csv", { type: "text/csv" });
    Object.defineProperty(input, "files", { value: [file] });
    await act(async () => {
      input!.dispatchEvent(new Event("change", { bubbles: true }));
    });

    const text = container.textContent ?? "";
    expect(text).toContain("250 rows found");
    expect(text).toContain("7 errors detected");
    expect(
      container.querySelector("[data-testid='import-preview-truncated']")?.textContent,
    ).toBe("Showing the first 2 of 250 rows.");
    expect(container.querySelectorAll("tbody tr")).toHaveLength(2);
  });
});
