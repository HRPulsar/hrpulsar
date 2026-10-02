// @vitest-environment jsdom
// HRP-820: a direct link into a section the matrix closed bounces to the
// dashboard with the permission toast; an open one renders.
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";

let sections: Record<string, string> = {};
let pathname = "/exams";
const replace = vi.fn();
const toastError = vi.fn();

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ user: { id: "u-1", roles: ["employee"], sections }, loading: false }),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  usePathname: () => pathname,
}));
vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: toastError }),
}));

const { RequireSection, SectionGate } = await import("@/components/require-section");

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  replace.mockClear();
  toastError.mockClear();
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function render(path: string, userSections: Record<string, string>) {
  pathname = path;
  sections = userSections;
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <SectionGate>
          <div data-testid="page">page</div>
        </SectionGate>
      </NextIntlClientProvider>,
    );
  });
}

describe("SectionGate (HRP-820)", () => {
  it("renders an open section", async () => {
    await render("/exams/1", { exams: "view" });
    expect(container.querySelector('[data-testid="page"]')).not.toBeNull();
    expect(replace).not.toHaveBeenCalled();
  });

  it("bounces a closed section", async () => {
    await render("/exams/1", { employees: "view" });
    expect(container.querySelector('[data-testid="page"]')).toBeNull();
    expect(toastError).toHaveBeenCalledWith(enMessages.common.noPermissionPage, expect.anything());
    expect(replace).toHaveBeenCalledWith("/dashboard");
  });

  it("asks for manage where the page needs it (HRP-823)", async () => {
    sections = { exams: "view" };
    // The mass exam's page wraps itself in RequireSection level="manage":
    // `view` on the section is the taker's half and opens nothing there.
    await act(async () => {
      root.render(
        <NextIntlClientProvider locale="en" messages={enMessages}>
          <RequireSection code="exams" level="manage">
            <div data-testid="page">page</div>
          </RequireSection>
        </NextIntlClientProvider>,
      );
    });
    expect(container.querySelector('[data-testid="page"]')).toBeNull();
    expect(replace).toHaveBeenCalledWith("/dashboard");
  });

  it("passes one's own exams through a closed exams section (HRP-823)", async () => {
    // The assignment e-mail links to /exams, and `/api/exams*` stays out
    // of the matrix for the same reason - the gate must not undo that.
    await render("/exams", { employees: "view" });
    expect(container.querySelector('[data-testid="page"]')).not.toBeNull();
    expect(replace).not.toHaveBeenCalled();
  });

  it("passes a path outside the matrix through", async () => {
    await render("/settings/profile", {});
    expect(container.querySelector('[data-testid="page"]')).not.toBeNull();
    expect(replace).not.toHaveBeenCalled();
  });
});
