// @vitest-environment jsdom
//
// HRP-1197: a step done by people names several executors - picked from a
// list ranked by how much of the step each one holds, saved together, and
// shown on the row as the first one and "+N".

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import type { Coverage, CoverageHuman, CoverageStep } from "@/lib/api/work";

const getCoverage = vi.fn();
const stepPeople = vi.fn();
const listPeople = vi.fn();
const updateStep = vi.fn();

vi.mock("@/lib/api/work", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/work")>()),
  workApi: { getCoverage, stepPeople, listPeople, updateStep },
}));
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ user: null }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const { AssignPersonDialog } = await import("@/components/coverage/assign-person-dialog");
const { CoverageTab } = await import("@/components/coverage/coverage-tab");

const RANKED = [
  { employee_id: "e-1", name: "Anna Petrova", email: null, position_title: "Controller", match_percent: 100 },
  { employee_id: "e-2", name: "Ivan Roe", email: null, position_title: null, match_percent: 50 },
  // Outside the reader's HR scope: offered, the percent not shown.
  { employee_id: "e-3", name: "Olga Berg", email: null, position_title: null, match_percent: null },
];

let container: HTMLDivElement;
let root: Root;
const onSaved = vi.fn();
const onClose = vi.fn();

beforeEach(() => {
  for (const fn of [getCoverage, stepPeople, listPeople, updateStep, onSaved, onClose]) fn.mockReset();
  stepPeople.mockResolvedValue(RANKED);
  updateStep.mockResolvedValue({ id: "s-1" });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

const byId = (id: string) => document.querySelector<HTMLElement>(`[data-testid="${id}"]`);

async function click(id: string) {
  await act(async () => byId(id)!.click());
}

async function renderDialog(props: { currentIds: string[]; suggestedIds?: string[] }) {
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <AssignPersonDialog
          containerId="c-1"
          stepId="s-1"
          field="executor_employee_ids"
          onClose={onClose}
          onSaved={onSaved}
          {...props}
        />
      </NextIntlClientProvider>,
    );
  });
}

const checked = (id: string) => byId(`coverage-modal-assign-option-${id}`)!.hasAttribute("data-checked");

it("ranks the people with their match and saves several together", async () => {
  await renderDialog({ currentIds: ["e-2"] });

  expect(stepPeople).toHaveBeenCalledWith("s-1");
  const names = [...byId("coverage-modal-assign-list")!.querySelectorAll("li")].map(
    (li) => li.querySelector("p")!.textContent,
  );
  expect(names).toEqual(["Anna Petrova", "Ivan Roe", "Olga Berg"]);
  expect(byId("coverage-modal-assign-option-e-1-aside")!.textContent).toBe("100% match");
  expect(byId("coverage-modal-assign-option-e-3-aside")).toBeNull();
  expect(checked("e-2")).toBe(true);

  // Ticking does not save; Save does, with the whole set.
  await click("coverage-modal-assign-option-e-1");
  expect(updateStep).not.toHaveBeenCalled();
  expect(byId("coverage-modal-assign-btn-save")!.textContent).toBe("Save (2)");
  await click("coverage-modal-assign-btn-save");
  expect(updateStep).toHaveBeenCalledWith("s-1", { executor_employee_ids: ["e-2", "e-1"] });
  expect(onSaved).toHaveBeenCalled();
});

it("starts from the people the match found, to confirm them (HRP-1198)", async () => {
  await renderDialog({ currentIds: [], suggestedIds: ["e-1"] });

  expect(checked("e-1")).toBe(true);
  expect(byId("coverage-modal-assign-btn-clear")).toBeNull();
  await click("coverage-modal-assign-btn-save");
  expect(updateStep).toHaveBeenCalledWith("s-1", { executor_employee_ids: ["e-1"] });
});

it("takes everyone off at once", async () => {
  await renderDialog({ currentIds: ["e-1", "e-2"] });

  await click("coverage-modal-assign-btn-clear");
  expect(updateStep).toHaveBeenCalledWith("s-1", { executor_employee_ids: [] });
});

it("keeps the checker one person, saved on the click", async () => {
  listPeople.mockResolvedValue([
    { employee_id: "e-1", user_id: "u-1", name: "Anna Petrova", email: null, position_title: null, assignable: true },
  ]);
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <AssignPersonDialog
          containerId="c-1"
          stepId="s-1"
          field="accountable_employee_id"
          currentIds={[]}
          onClose={onClose}
          onSaved={onSaved}
        />
      </NextIntlClientProvider>,
    );
  });

  expect(stepPeople).not.toHaveBeenCalled();
  expect(byId("coverage-modal-assign-btn-save")).toBeNull();
  await click("coverage-modal-assign-option-e-1");
  expect(updateStep).toHaveBeenCalledWith("s-1", { accountable_employee_id: "e-1" });
});

function executor(id: string, name: string, missing: string[]): CoverageHuman {
  return { employee_id: id, name, position: null, label: "assigned", missing_codes: missing };
}

it("shows the first executor and +N, and what none of them holds", async () => {
  const people = [
    executor("e-1", "Anna Petrova", ["P6", "P8"]),
    executor("e-2", "Ivan Roe", ["P8"]),
    executor("e-3", "Olga Berg", ["P6", "P8"]),
  ];
  const step: CoverageStep = {
    step_id: "s-1",
    position: 1,
    title: "Settle the priorities",
    state: "accepted",
    codes: ["P6", "P8"],
    required_codes: ["P6", "P8"],
    in_scope: true,
    mode: "blocked_judgment",
    quality: "no",
    verdict: "human",
    agent: null,
    human: people[0],
    human_backup: false,
    executors: people,
    accountable: null,
    needs_accountable: false,
    gap_label: null,
    hours_per_year: null,
    hire_need: null,
    skill_status: "none",
    tentative: false,
    review_human_share: null,
  };
  const coverage: Coverage = {
    container_id: "c-1",
    status: "active",
    mapping_pending: false,
    candidate_step_ids: [],
    shares: null,
    hours: { total: 0, moves: 0, to_review: 0, stays: 0, unestimated: 1, to_review_after: 0, freed: 0, automated: 0 },
    quality: { no: 1, draft: 0, strong: 0, better_than_human: 0 },
    hourly_rate: null,
    hourly_rate_currency: null,
    money: null,
    review_human_share_default: 50,
    steps: [step],
  };
  getCoverage.mockResolvedValue(coverage);
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <CoverageTab
          containerId="c-1"
          steps={[]}
          primitives={[]}
          canEdit={false}
          canOpenHireNeed={false}
          canRegisterAgent={false}
          onStepsChanged={() => {}}
        />
      </NextIntlClientProvider>,
    );
  });

  expect(byId("coverage-executor-s-1")!.textContent).toContain("Executor: Anna Petrova");
  const more = byId("coverage-executor-more-s-1")!;
  expect(more.textContent).toBe("+2");
  expect(more.getAttribute("aria-label")).toBe("2 more people");
  // P6 is Ivan's, so only P8 is missing for the team.
  expect(byId("coverage-executor-unmatched-s-1")!.getAttribute("title")).toBe("Missing: P8");
  await click("coverage-executor-more-s-1");
  const listed = byId("coverage-executor-more-s-1-popover")!.textContent;
  expect(listed).toContain("Ivan Roe");
  expect(listed).toContain("Olga Berg");
  // Both blocks read the same people: the outcome counts all three.
  expect(byId("coverage-outcome-doers")!.textContent).toContain("Ivan Roe");
});
