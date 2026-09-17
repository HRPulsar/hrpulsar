// @vitest-environment jsdom
//
// M22b: the recruitment subtree is gated by `RequireRole recruit` in
// `(dashboard)/recruitment/layout.tsx`. The whole point is the negative
// case — an employee following a bookmark must get the permission toast and
// a bounce, not the shell plus a cascade of 403s from every child request.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";

let canRecruit = true;
const replace = vi.fn();
const toastError = vi.fn();

vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({
    canRecruit,
    isAdmin: false,
    canManage: false,
    canViewManagementData: false,
    canViewCoverage: false,
    canCreateCoverage: false,
  }),
}));

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ user: { id: "u-1" }, loading: false }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: toastError }),
}));

const { RequireRole } = await import("@/components/require-role");

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  canRecruit = true;
  replace.mockClear();
  toastError.mockClear();
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
        <RequireRole recruit>
          <div data-testid="recruitment-child" />
        </RequireRole>
      </NextIntlClientProvider>,
    );
  });
}

describe("RequireRole recruit", () => {
  it("renders the recruitment shell for a recruiting role", async () => {
    await render();
    expect(
      container.querySelector("[data-testid='recruitment-child']"),
    ).not.toBeNull();
    expect(replace).not.toHaveBeenCalled();
  });

  it("denies everyone else with the permission toast and a bounce", async () => {
    canRecruit = false;
    await render();
    expect(
      container.querySelector("[data-testid='recruitment-child']"),
    ).toBeNull();
    expect(toastError).toHaveBeenCalledWith(
      enMessages.common.noPermissionPage,
      expect.anything(),
    );
    expect(replace).toHaveBeenCalledWith("/dashboard");
  });
});
