// @vitest-environment jsdom
//
// HRP-623 REDO (QA 12.10): the card GET answers a designed 404 for a stale id
// (deleted card) and for a colleague hidden from the viewer (outside
// active / on-leave, outside the read scope — e.g. an inactive Administrator
// opened under a manager). The page renders its not-found state for that;
// toasting "Failed to load employee" on top misreports design as breakage,
// which is exactly how the QA case surfaced. The toast stays for a server or
// network error, where loading truly failed. Same contract the coverage page
// pinned in HRP-853.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";

const apiGet = vi.fn();
const toastError = vi.fn();

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "gone" }),
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api: { get: apiGet },
}));
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ user: null }) }));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({
    canAssignRoles: false,
    canViewSection: () => false,
    canManageSection: () => false,
    isAdminLevel: false,
  }),
}));
vi.mock("@/hooks/use-competence-tree", () => ({
  useCompetenceTree: () => ({ tree: [], loading: false }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: toastError } }));

const { ApiError } = await import("@/lib/api");
const { default: EmployeeDetailPage } = await import(
  "@/app/(dashboard)/employees/[id]/page"
);

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  apiGet.mockReset();
  toastError.mockReset();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function render(cardError: Error) {
  apiGet.mockImplementation((path: string) =>
    path === "/employees/gone"
      ? Promise.reject(cardError)
      : Promise.reject(new ApiError(403, "forbidden")),
  );
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <EmployeeDetailPage />
      </NextIntlClientProvider>,
    );
  });
}

it("renders not-found for a designed 404 without a load-failure toast", async () => {
  await render(new ApiError(404, "not found", undefined, "employee_not_found"));

  expect(document.body.textContent).toContain(enMessages.employees.notFound);
  expect(toastError).not.toHaveBeenCalled();
});

it("keeps the load-failure toast for a server error", async () => {
  await render(new ApiError(500, "boom"));

  expect(toastError).toHaveBeenCalledWith(enMessages.employees.toastLoadFailed);
});
