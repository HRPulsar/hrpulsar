// @vitest-environment jsdom
//
// HRP-634: the Roles page. Two things must hold and neither is visible in
// the component source alone:
//
//   1. a non-admin never renders it (the sidebar entry is hidden, but a
//      typed URL must be denied too — `RequireRole admin`);
//   2. it prints the holder counts and the plain-language capability text,
//      and never the seeded `permissions` codenames: those rows exist in
//      the DB but no gate reads them, so showing them would claim a
//      recruiter can do nothing.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import type { Role } from "@/lib/types";

let isAdmin = true;

const ROLES: Role[] = [
  {
    id: "r-emp",
    name: "Employee",
    code: "employee",
    description: null,
    is_system: true,
    tenant_id: null,
    permissions: ["employees.read", "company.read"],
    user_count: 23,
  },
  {
    id: "r-rec",
    name: "Recruiter",
    code: "recruiter",
    description: null,
    is_system: true,
    tenant_id: null,
    permissions: [],
    user_count: 3,
  },
  {
    id: "r-custom",
    name: "Auditor",
    code: "auditor",
    description: null,
    is_system: false,
    tenant_id: "t-1",
    permissions: [],
    user_count: 0,
  },
  {
    id: "r-described",
    name: "Observer",
    code: "observer",
    description: "Read-only observer",
    is_system: false,
    tenant_id: "t-1",
    permissions: [],
    user_count: 0,
  },
];

vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {},
  api: { get: vi.fn(() => Promise.resolve(ROLES)) },
}));

vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ isAdmin, canManage: isAdmin }),
}));

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ user: { id: "u-1" }, loading: false }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

const RolesPage = (await import("@/app/(dashboard)/settings/roles/page"))
  .default;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  isAdmin = true;
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
        <RolesPage />
      </NextIntlClientProvider>,
    );
  });
}

describe("roles page", () => {
  it("renders one row per role with its holder count", async () => {
    await render();

    expect(container.querySelector("[data-testid='roles-table']")).not.toBeNull();
    for (const role of ROLES) {
      expect(
        container.querySelector(`[data-testid='roles-row-${role.code}']`),
        `row missing for ${role.code}`,
      ).not.toBeNull();
      expect(
        container.querySelector(`[data-testid='roles-count-${role.code}']`)
          ?.textContent,
      ).toBe(String(role.user_count));
    }
  });

  it("drills the count down to the employees holding that role", async () => {
    await render();

    const href = (code: string) =>
      container
        .querySelector(`[data-testid='roles-count-${code}']`)
        ?.getAttribute("href");

    expect(href("recruiter")).toBe("/employees?role=recruiter");
    expect(href("auditor")).toBe("/employees?role=auditor");
    // `?role=employee` means "holds ONLY the baseline" — a different
    // question from "holds the baseline", which is everyone. The baseline
    // row therefore drills down to the unfiltered list.
    expect(href("employee")).toBe("/employees");
  });

  it("describes what a role can do instead of listing dead permissions", async () => {
    await render();

    const text = container.textContent ?? "";
    expect(text).toContain(enMessages.settings.rolesCapRecruiter);
    // Custom roles carry no gates at all — say so rather than leave a blank,
    // unless the tenant wrote its own description.
    expect(text).toContain(enMessages.settings.rolesCapCustom);
    expect(text).toContain("Read-only observer");
    for (const codename of ROLES[0].permissions) {
      expect(text, `${codename} must not be printed`).not.toContain(codename);
    }
  });

  it("renders nothing for a non-admin", async () => {
    isAdmin = false;
    await render();

    expect(container.querySelector("[data-testid='roles-page']")).toBeNull();
  });
});
