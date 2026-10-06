// @vitest-environment jsdom
//
// HRP-907: the Active assessments block counts only what is still moving —
// not Done, not Cancelled — reads `total`s (a 100-row page capped the old
// numbers at 100), shows the launched share, and its button opens the list
// on the same statuses. The number is the row count of that grouped list: a
// mass assessment is one row, however many statuses its assessments are in.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";

// Rows of /assessments-grouped, each as the statuses of its assessments.
const ROWS: string[][] = [
  ...Array.from({ length: 3 }, () => ["draft"]),
  ...Array.from({ length: 7 }, () => ["sent"]),
  ["draft", "sent", "in_progress", "done"], // a mass assessment
  ["in_progress"],
  ["on_review"],
  ["done"],
];

const getMock = vi.fn((path: string) => {
  if (path === "/onboarding/status") {
    return Promise.resolve({ needs_onboarding: false });
  }
  if (path === "/company") return Promise.resolve({ id: "t-1", name: "Acme" });
  if (path.startsWith("/assessments-grouped?")) {
    const wanted = new URLSearchParams(path.split("?")[1]).getAll("status");
    const total = ROWS.filter((row) => row.some((s) => wanted.includes(s))).length;
    return Promise.resolve({ items: [], total });
  }
  return Promise.reject(new Error("not mocked"));
});

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api: { get: getMock, post: vi.fn() },
}));

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({
    user: { id: "u-1", is_platform_admin: false, sections: { assessments: "view" } },
  }),
}));

const { routerMock } = vi.hoisted(() => ({
  routerMock: { replace: vi.fn(), push: vi.fn() },
}));

vi.mock("next/navigation", () => ({ useRouter: () => routerMock }));

const page = await import("@/app/(dashboard)/dashboard/page");

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  getMock.mockClear();
  routerMock.push.mockClear();
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
        <page.default />
      </NextIntlClientProvider>,
    );
  });
}

describe("Active assessments block (HRP-907)", () => {
  it("asks the grouped list for totals, never a capped page", async () => {
    await render();
    const asked = getMock.mock.calls
      .map((c) => String(c[0]))
      .filter((p) => p.startsWith("/assessments"));
    expect(asked.sort()).toEqual([
      "/assessments-grouped?limit=1&status=draft&status=sent&status=in_progress&status=on_review",
      "/assessments-grouped?limit=1&status=in_progress&status=on_review",
      "/assessments-grouped?limit=1&status=on_review",
      "/assessments-grouped?limit=1&status=sent&status=in_progress&status=on_review",
    ]);
  });

  it("counts active assessments and the launched share", async () => {
    await render();
    const text = container.textContent ?? "";
    expect(text).toContain("Active assessments");
    // 13 active rows - the list the button opens; the mass assessment is
    // one of them, under its furthest stage (in progress).
    expect(text).toContain("13 assessments");
    // Launched = sent 7 + in progress 2 + on review 1.
    expect(text).toContain("10 of 13 launched");
    expect(text).toContain("77%");
    for (const label of ["Sent", "In progress", "In review", "Preparing"]) {
      expect(text).toContain(label);
    }
    expect(text).not.toContain("Manage cycles");
    expect(text).not.toContain("Not started");
  });

  it("opens the assessments list filtered to the same statuses", async () => {
    await render();
    const cta = container.querySelector<HTMLButtonElement>(
      '[data-testid="dashboard-cycle-cta"]',
    );
    act(() => cta?.click());
    expect(routerMock.push).toHaveBeenCalledWith(page.ACTIVE_ASSESSMENTS_HREF);
    const statuses = new URLSearchParams(
      page.ACTIVE_ASSESSMENTS_HREF.split("?")[1],
    ).getAll("status");
    expect(statuses).toEqual(["draft", "sent", "in_progress", "on_review"]);
  });

  it("is a launched share of what is active, nothing else", () => {
    expect(
      page.cycleStats({ draft: 1, sent: 0, in_progress: 0, on_review: 0 }),
    ).toEqual({ launched: 0, total: 1, percent: 0 });
    expect(
      page.cycleStats({ draft: 0, sent: 0, in_progress: 0, on_review: 0 }),
    ).toEqual({ launched: 0, total: 0, percent: 0 });
  });

  it("puts each row under its furthest stage, summing to the list", () => {
    expect(page.cycleCountsFromSuffixTotals([13, 10, 3, 1])).toEqual({
      draft: 3,
      sent: 7,
      in_progress: 2,
      on_review: 1,
    });
  });
});
