// @vitest-environment jsdom
//
// 2.0.0 review §3 — the To do tab.
//
// Bulk generation used to report only the last refusal, so nine failures
// out of ten looked like one. HRP-801 (QA 23.10, e): a gap row carries no
// Hire / Agency label any more - the hire window chooses the route, for one
// row or for a selection - and a row already handed over links to its
// vacancy instead. HRP-1198: three groups - people with nobody assigned,
// an agent still missing something, nobody at all - each with its next step.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import { ApiError } from "@/lib/api";
import type { Gap } from "@/lib/api/work";

const listGaps = vi.fn();
const generateSkill = vi.fn();
const createHireNeed = vi.fn();
const stepPeople = vi.fn();
const toastError = vi.fn();
const toastSuccess = vi.fn();
const toastWarning = vi.fn();

vi.mock("@/lib/api/work", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/work")>()),
  workApi: { listGaps, generateSkill, createHireNeed, stepPeople },
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ canViewSection: () => true }),
}));
vi.mock("@/hooks/use-cost-confirmation", () => ({
  useCostConfirmation: () => ({ cost: null }),
}));
vi.mock("@/lib/ee-hooks", () => ({ EECreditCostBadge: () => null }));
vi.mock("sonner", () => ({
  toast: { success: toastSuccess, error: toastError, warning: toastWarning },
}));

const { GapsTab } = await import("@/components/coverage/gaps-tab");

const GAP: Gap = {
  step_id: "s-1",
  position: 1,
  title: "Check the invoice",
  kind: "not_automated_yet",
  mode: "automatable",
  gap_label: null,
  required_codes: [],
  codes: [],
  agent: null,
  skill_status: "none",
  hire_need: null,
};

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  listGaps.mockReset();
  generateSkill.mockReset();
  createHireNeed.mockReset();
  toastError.mockReset();
  toastSuccess.mockReset();
  toastWarning.mockReset();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function render(onLoaded?: (count: number) => void) {
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
          onLoaded={onLoaded}
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

// HRP-1172: the demo sandbox answers 429 `credits_demo_quota_exhausted`, not
// 402 - the loop kept sending guaranteed refusals for every row left.
it.each([
  ["402", new ApiError(402, "out of credits", undefined, "credits_limit_reached"), 1],
  [
    "the demo quota",
    new ApiError(429, "demo quota", undefined, "credits_demo_quota_exhausted"),
    1,
  ],
  ["another refusal", new ApiError(429, "slow down", undefined, "rate_limited"), 3],
])("stops a bulk run on %s only when credits are out", async (_name, refusal, calls) => {
  listGaps.mockResolvedValue([
    GAP,
    { ...GAP, step_id: "s-2", position: 2 },
    { ...GAP, step_id: "s-3", position: 3 },
  ]);
  generateSkill.mockRejectedValue(refusal);

  await render();
  await click("coverage-btn-generate-all-skills");
  await click("confirm-dialog-btn-confirm");

  expect(generateSkill).toHaveBeenCalledTimes(calls);
  expect(toastError.mock.calls[0][0]).toContain(`${calls} of ${calls}`);
});

const NO_OWNER: Gap = { ...GAP, kind: "no_owner", gap_label: "hire" };
const byTestId = (id: string) => document.querySelector(`[data-testid="${id}"]`);

it("links a handed-over row to its vacancy, named by how it is filled", async () => {
  listGaps.mockResolvedValue([
    {
      ...NO_OWNER,
      hire_need: { id: "n-1", vacancy_id: "v-1", label: "agency", talent_card_id: null },
    },
    {
      ...NO_OWNER,
      step_id: "s-2",
      position: 2,
      // QA 12.11: "look inside first" opened the card alone.
      hire_need: { id: "n-2", vacancy_id: null, label: "hire", talent_card_id: "tc-2" },
    },
    { ...NO_OWNER, step_id: "s-3", position: 3 },
  ]);

  await render();

  const agency = byTestId("coverage-gap-row-s-1-link-vacancy")!;
  expect(agency.textContent).toBe(enMessages.coverage.goToVacancyAgency);
  expect(agency.getAttribute("href")).toBe("/recruitment/requisitions/v-1");
  // "Look inside first" landed on the talent market: the link goes there.
  const inside = byTestId("coverage-gap-row-s-2-link-vacancy")!;
  expect(inside.textContent).toBe(enMessages.coverage.goToVacancy);
  expect(inside.getAttribute("href")).toBe("/talent-market/tc-2");
  // No label to pick on any row, and a handed-over row is not offered again.
  expect(document.querySelector('[data-testid$="-select-label"]')).toBeNull();
  expect(byTestId("coverage-gap-row-s-1-btn-hire")).toBeNull();
  expect(byTestId("coverage-gap-row-s-2-btn-hire")).toBeNull();
  expect(byTestId("coverage-gap-row-s-2-checkbox")!.hasAttribute("data-disabled")).toBe(true);
  const handedOver = byTestId("coverage-gap-row-s-1-checkbox")!;
  expect(handedOver.hasAttribute("data-disabled")).toBe(true);
  expect(handedOver.getAttribute("title")).toBe(enMessages.coverage.gapHandedOverHint);
  // A row not handed over yet: the hire window and Assign, as on Coverage.
  expect(byTestId("coverage-gap-row-s-3-btn-hire")!.textContent).toBe(
    enMessages.coverage.openHireNeedOne,
  );
  expect(byTestId("coverage-gap-row-s-3-btn-assign")).not.toBeNull();
  expect(document.body.textContent).toContain(enMessages.coverage.gapsHint);
});

it("opens one window for a row and for a selection", async () => {
  listGaps.mockResolvedValue([
    NO_OWNER,
    { ...NO_OWNER, step_id: "s-2", position: 2, title: "Sign the release", gap_label: "agency" },
  ]);
  createHireNeed.mockResolvedValue({ id: "n-1", talent_card_id: null });

  await render();
  await click("coverage-gap-row-s-1-btn-hire");
  expect(byTestId("coverage-modal-hire")!.textContent).toContain("Hire for: Check the invoice");
  await act(async () => {
    (document.querySelector('[data-testid="coverage-modal-hire"] button') as HTMLElement)
      .closest("[role=dialog]")
      ?.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  });

  // Mixed labels no longer block the selection: the window decides.
  await click("coverage-gap-row-s-1-checkbox");
  await click("coverage-gap-row-s-2-checkbox");
  await click("coverage-gap-btn-hire-need");
  expect(byTestId("coverage-modal-hire")!.textContent).toContain(
    enMessages.coverage.hireFromStepsTitle,
  );
  await click("coverage-hire-route-agency");
  await click("coverage-btn-hire-submit");
  expect(createHireNeed).toHaveBeenCalledWith("c-1", {
    step_ids: ["s-1", "s-2"],
    label: "agency",
    internal_search_allowed: false,
  });
  expect(toastSuccess).toHaveBeenCalledWith(enMessages.coverage.hireNeedCreated);
});

it("says when looking inside first could not reach the talent market", async () => {
  listGaps.mockResolvedValue([NO_OWNER]);
  createHireNeed.mockResolvedValue({ id: "n-1", talent_card_id: null });

  await render();
  await click("coverage-gap-row-s-1-btn-hire");
  await click("coverage-btn-hire-submit");

  expect(createHireNeed).toHaveBeenCalledWith("c-1", {
    step_ids: ["s-1"],
    label: "hire",
    internal_search_allowed: true,
  });
  expect(toastWarning).toHaveBeenCalledWith(enMessages.coverage.hireNeedNotOnTalentMarket);
  expect(toastSuccess).not.toHaveBeenCalled();
});

const PEOPLE: Gap = { ...GAP, kind: "unassigned", mode: "blocked_judgment" };
const OLGA = { employee_id: "e-olga", name: "Olga Berg", position: null, label: "assessed" as const, missing_codes: [] };

it("splits To do into people, agent and nobody, in that order (HRP-1198)", async () => {
  const onLoaded = vi.fn();
  listGaps.mockResolvedValue([
    { ...NO_OWNER, step_id: "s-3", position: 3 },
    { ...GAP, step_id: "s-2", position: 2 },
    { ...PEOPLE, human: OLGA },
    { ...PEOPLE, step_id: "s-4", position: 4, human: null },
  ]);
  await render(onLoaded);

  const sections = [...document.querySelectorAll("section")].map((el) => el.dataset.testid);
  expect(sections).toEqual(["coverage-todo-people", "coverage-todo-not-automated", "coverage-todo-no-owner"]);
  // HRP-1206: the page's counter follows what the tab lists.
  expect(onLoaded).toHaveBeenLastCalledWith(4);
  // Each group says what to do next.
  expect(byTestId("coverage-todo-people")!.textContent).toContain(enMessages.coverage.todoPeopleHint);
  expect(byTestId("coverage-todo-not-automated")!.textContent).toContain(enMessages.coverage.todoAgentNext);
  expect(byTestId("coverage-todo-no-owner")!.textContent).toContain(enMessages.coverage.gapsHint);

  // Matched, not assigned - the outcome block's split - and Confirm.
  expect(byTestId("coverage-people-row-s-1-matched")!.textContent).toBe("Matched, not assigned:Olga Berg");
  expect(byTestId("coverage-people-row-s-1-btn-confirm")!.textContent).toBe(enMessages.coverage.todoConfirmPeople);
  // Nobody this reader may see: not assigned, and Assign.
  expect(byTestId("coverage-people-row-s-4-unassigned")!.textContent).toBe(enMessages.coverage.todoNoExecutor);
  expect(byTestId("coverage-people-row-s-4-btn-assign")).not.toBeNull();
  // The "?" of the step type, on every group.
  expect(byTestId("coverage-people-row-s-1-mode-help")).not.toBeNull();
  expect(byTestId("coverage-todo-row-s-2-mode-help")).not.toBeNull();
  expect(byTestId("coverage-gap-row-s-3-mode-help")).not.toBeNull();
});

it("confirms the people the match found in the executors' dialog (HRP-1198)", async () => {
  listGaps.mockResolvedValue([{ ...PEOPLE, human: OLGA }]);
  stepPeople.mockResolvedValue([
    { employee_id: "e-olga", name: "Olga Berg", email: null, position_title: null, match_percent: 100 },
  ]);
  await render();

  await click("coverage-people-row-s-1-btn-confirm");
  expect(stepPeople).toHaveBeenCalledWith("s-1");
  expect(byTestId("coverage-modal-assign-option-e-olga")!.hasAttribute("data-checked")).toBe(true);
});
