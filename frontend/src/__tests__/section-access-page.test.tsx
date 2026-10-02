// @vitest-environment jsdom
//
// HRP-820 review round 1: pin the matrix behavior the review flagged —
// every level offered on every cell (the clamp is gone since HRP-832), the
// admin_locked cell staying locked, the never_hidden checkbox staying
// disabled, a hidden row dimming its whole row (not just its selects), and
// Save pushing the whole matrix then refreshing /auth/me so the admin's
// own sidebar/section gate catch up without a hard reload.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import type { SectionAccess } from "@/lib/api/section-access";

const MATRIX: SectionAccess = {
  roles: ["admin", "hr", "employee"],
  sections: [
    {
      code: "employees",
      hidden: false,
      admin_locked: false,
      never_hidden: true,
      defaults: { admin: "manage", hr: "view", employee: "view" },
      levels: { admin: "manage", hr: "view", employee: "view" },
    },
    {
      code: "company",
      hidden: false,
      admin_locked: true,
      never_hidden: true,
      defaults: { admin: "manage", hr: "manage", employee: "none" },
      levels: { admin: "manage", hr: "manage", employee: "none" },
    },
    {
      code: "exams",
      hidden: false,
      admin_locked: false,
      never_hidden: false,
      defaults: { admin: "manage", hr: "view", employee: "view" },
      levels: { admin: "manage", hr: "view", employee: "view" },
    },
    {
      // HRP-998: saved before the floor was shown - hr sits below Employee.
      code: "analytics",
      hidden: false,
      admin_locked: false,
      never_hidden: false,
      defaults: { admin: "manage", hr: "manage", employee: "none" },
      levels: { admin: "manage", hr: "none", employee: "view" },
    },
  ],
};

const RANK = ["none", "view", "manage"];

const getMatrix = vi.fn(() => Promise.resolve(structuredClone(MATRIX)));
const updateMatrix = vi.fn((body: unknown) =>
  Promise.resolve(structuredClone((body as { sections: unknown }) && MATRIX)),
);

vi.mock("@/lib/api/section-access", () => ({
  sectionAccessApi: {
    get: (...args: unknown[]) => getMatrix(...(args as [])),
    update: (...args: unknown[]) => updateMatrix(...(args as [unknown])),
  },
}));

const refreshSpy = vi.fn(() => Promise.resolve());

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({
    user: { id: "u-1", roles: ["admin"], sections: {} },
    loading: false,
    refresh: refreshSpy,
  }),
}));

// A fresh object on every call would change `router`'s identity each
// render, and RequireRole's effect depends on it — see
// dashboard-closed-sections.test.tsx for the same note.
const { routerMock } = vi.hoisted(() => ({ routerMock: { replace: vi.fn() } }));

vi.mock("next/navigation", () => ({
  useRouter: () => routerMock,
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

const SectionAccessPage = (
  await import("@/app/(dashboard)/company/profile/section-access/page")
).default;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  getMatrix.mockClear();
  updateMatrix.mockClear();
  refreshSpy.mockClear();
  routerMock.replace.mockClear();
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
        <SectionAccessPage />
      </NextIntlClientProvider>,
    );
  });
}

function byTestId(testId: string): HTMLElement {
  const el = container.querySelector(`[data-testid="${testId}"]`) as HTMLElement;
  expect(el, testId).toBeTruthy();
  return el;
}

async function click(testId: string) {
  const el = byTestId(testId);
  await act(async () => {
    el.click();
  });
}

function optionDisabled(selectTestId: string, value: string): boolean {
  const select = byTestId(selectTestId) as HTMLSelectElement;
  const option = select.querySelector(`option[value="${value}"]`) as HTMLOptionElement;
  expect(option, `${selectTestId} option ${value}`).toBeTruthy();
  return option.disabled;
}

describe("SectionAccessPage (HRP-820)", () => {
  it("offers every level from the Employee column up, none below it", async () => {
    await render();

    // HRP-832 dropped the clamp filter: exams-hr "manage" used to be off.
    // HRP-998: the Employee column is every role's floor - everyone holds
    // it - so a level under it is off; Employee itself offers all three.
    for (const section of MATRIX.sections) {
      const floor = RANK.indexOf(section.levels.employee);
      for (const role of MATRIX.roles) {
        for (const level of RANK) {
          const below = role !== "employee" && RANK.indexOf(level) < floor;
          expect(
            optionDisabled(`section-access-select-${section.code}-${role}`, level),
            `${section.code}-${role} ${level}`,
          ).toBe(below);
        }
      }
    }
    expect(byTestId("section-access-employee-floor").textContent).toContain("Employee role");
  });

  it("explains a level saved below the Employee column", async () => {
    await render();

    const hint = byTestId("section-access-below-employee-analytics-hr");
    expect(hint.getAttribute("aria-label")).toContain("at View anyway");
    expect(container.querySelectorAll('[data-testid^="section-access-below-employee-"]')).toHaveLength(
      1,
    );
  });

  it("follows the Employee column as it changes", async () => {
    await render();

    expect(optionDisabled("section-access-select-exams-hr", "none")).toBe(true);
    const employee = byTestId("section-access-select-exams-employee") as HTMLSelectElement;
    await act(async () => {
      employee.value = "none";
      employee.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(optionDisabled("section-access-select-exams-hr", "none")).toBe(false);
  });

  it("keeps an admin_locked cell disabled", async () => {
    await render();

    const select = byTestId("section-access-select-company-admin") as HTMLSelectElement;
    expect(select.disabled).toBe(true);
  });

  it("keeps a never_hidden row's checkbox disabled", async () => {
    await render();

    const checkbox = byTestId("section-access-hidden-employees");
    expect(checkbox.getAttribute("aria-disabled")).toBe("true");
  });

  it("dims the whole row and disables its selects when hidden is toggled on", async () => {
    await render();

    const row = byTestId("section-access-row-exams");
    const labelCell = row.querySelector("th[scope='row']") as HTMLElement;
    expect(labelCell.className).not.toContain("opacity-50");
    expect((byTestId("section-access-select-exams-admin") as HTMLSelectElement).disabled).toBe(
      false,
    );

    await click("section-access-hidden-exams");

    expect(labelCell.className).toContain("opacity-50");
    expect((byTestId("section-access-select-exams-admin") as HTMLSelectElement).disabled).toBe(
      true,
    );
    expect((byTestId("section-access-select-exams-hr") as HTMLSelectElement).disabled).toBe(true);
    // The checkbox cell itself must stay at full opacity — it is the one
    // control that stays active and brings the row back.
    const hiddenCellWrapper = byTestId("section-access-hidden-exams").closest("td");
    expect(hiddenCellWrapper?.className ?? "").not.toContain("opacity-50");
  });

  it("saves the whole matrix and refreshes /auth/me afterwards", async () => {
    await render();

    await click("section-access-btn-save");

    expect(updateMatrix).toHaveBeenCalledTimes(1);
    expect(updateMatrix).toHaveBeenCalledWith({
      sections: MATRIX.sections.map((s) => ({
        code: s.code,
        hidden: s.hidden,
        levels: s.levels,
      })),
    });
    expect(refreshSpy).toHaveBeenCalledTimes(1);
  });
});
