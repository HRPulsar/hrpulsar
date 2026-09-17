// @vitest-environment jsdom
//
// 2.0.0 review §3 — the To do tab.
//
// Bulk generation used to report only the last refusal, so nine failures
// out of ten looked like one; and a selection mixing Hire and Agency was
// silently sent to Recruitment as Hire.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import type { Gap } from "@/lib/api/work";

const listGaps = vi.fn();
const generateSkill = vi.fn();
const toastError = vi.fn();
const toastSuccess = vi.fn();

vi.mock("@/lib/api/work", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/work")>()),
  workApi: { listGaps, generateSkill },
}));
vi.mock("@/hooks/use-cost-confirmation", () => ({
  useCostConfirmation: () => ({ cost: null }),
}));
vi.mock("@/lib/ee-hooks", () => ({ EECreditCostBadge: () => null }));
vi.mock("sonner", () => ({ toast: { success: toastSuccess, error: toastError } }));

const { GapsTab } = await import("@/components/coverage/gaps-tab");

const GAP: Gap = {
  step_id: "s-1",
  position: 1,
  title: "Check the invoice",
  kind: "not_automated_yet",
  mode: "automatable",
  gap_label: null,
  required_codes: [],
  agent: null,
  skill_status: "none",
  hire_need: null,
};

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  listGaps.mockReset();
  generateSkill.mockReset();
  toastError.mockReset();
  toastSuccess.mockReset();
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
        <GapsTab
          containerId="c-1"
          primitives={[]}
          canEdit
          canOpenHireNeed
          canRegisterAgent
          onStepsChanged={() => {}}
        />
      </NextIntlClientProvider>,
    );
  });
}

async function click(testId: string) {
  const el = document.querySelector(`[data-testid="${testId}"]`) as HTMLElement;
  expect(el, testId).toBeTruthy();
  await act(async () => {
    el.click();
  });
}

it("counts every refusal of a bulk run in one message", async () => {
  listGaps.mockResolvedValue([
    GAP,
    { ...GAP, step_id: "s-2", position: 2 },
    { ...GAP, step_id: "s-3", position: 3 },
  ]);
  generateSkill
    .mockRejectedValueOnce(new Error("first refusal"))
    .mockResolvedValueOnce({})
    .mockRejectedValueOnce(new Error("last refusal"));

  await render();
  await click("coverage-btn-generate-all-skills");
  await click("confirm-dialog-btn-confirm");

  expect(generateSkill).toHaveBeenCalledTimes(3);
  expect(toastError).toHaveBeenCalledTimes(1);
  expect(toastError.mock.calls[0][0]).toContain("2 of 3");
  expect(toastError.mock.calls[0][0]).toContain("last refusal");
});

it("refuses to guess the label of a mixed selection", async () => {
  listGaps.mockResolvedValue([
    { ...GAP, kind: "no_owner", gap_label: "hire" },
    { ...GAP, step_id: "s-2", position: 2, kind: "no_owner", gap_label: "agency" },
  ]);

  await render();
  const hireNeed = () =>
    document.querySelector('[data-testid="coverage-gap-btn-hire-need"]') as HTMLButtonElement;

  await click("coverage-gap-row-s-1-checkbox");
  expect(hireNeed().disabled).toBe(false);

  await click("coverage-gap-row-s-2-checkbox");
  expect(hireNeed().disabled).toBe(true);
  expect(document.body.textContent).toContain(enMessages.coverage.mixedGapLabelsHint);
});
