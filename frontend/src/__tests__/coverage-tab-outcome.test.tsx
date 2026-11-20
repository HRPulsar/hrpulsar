// @vitest-environment jsdom
//
// The Coverage tab after the 12.11 demo review (HRP-903):
// HRP-1196 - a step's description from the Steps tab is on its coverage row.
// HRP-1200 - who does the work and who checks the agent's, next to the summary.
// HRP-1204 - a "?" by the step type opens what every type means.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import type { Coverage, CoverageStep } from "@/lib/api/work";

const getCoverage = vi.fn();

vi.mock("@/lib/api/work", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/work")>()),
  // The assign dialog lists the people it offers.
  workApi: {
    getCoverage,
    listPeople: vi.fn().mockResolvedValue([]),
    stepPeople: vi.fn().mockResolvedValue([]),
  },
}));
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ user: null }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const { CoverageTab } = await import("@/components/coverage/coverage-tab");
const { outcomeOf, stepExecutors, stepMatches } = await import("@/components/coverage/coverage-outcome");

const ANNA = { employee_id: "e-anna", name: "Anna Petrova", position: "Controller" };
const IVAN = { employee_id: "e-ivan", name: "Ivan Roe", position: null };
const OLGA = { employee_id: "e-olga", name: "Olga Berg", position: null };

function human(person: typeof ANNA | typeof IVAN, label: "assigned" | "assessed" = "assigned") {
  return { ...person, label, missing_codes: [] };
}

/** One process of every kind: two steps an agent closes, three it does under a
 * checker (one with nobody to check), and four people keep - one assigned, one
 * only matched, one matched with a colleague this reader may not see, and one
 * nobody covers. */
const PROCESS = [
  row("alone-1", { position: 1 }),
  row("alone-2", { position: 2, hours_per_year: 40 }),
  row("checked-1", { position: 3, mode: "draft_then_review", accountable: ANNA }),
  row("checked-2", { position: 4, mode: "review_required", accountable: ANNA }),
  row("checked-3", { position: 5, mode: "review_required", title: "Sign the act", needs_accountable: true }),
  row("people-1", { position: 6, mode: "blocked_judgment", verdict: "human", human: human(IVAN) }),
  row("people-2", {
    position: 7,
    mode: "blocked_physical",
    title: "Train on site",
    verdict: "human",
    human: human(OLGA, "assessed"),
  }),
  row("people-3", { position: 8, mode: "blocked_judgment", verdict: "gap" }),
  // HRP-810: the match is outside this reader's HR scope - redacted, still covered.
  row("people-4", { position: 9, mode: "blocked_judgment", title: "Agree the plan", verdict: "human" }),
  // Out of scope: in no bucket, as in the summary.
  row("boundary", { position: 10, in_scope: false, mode: "blocked_physical", verdict: "out_of_scope" }),
];

function row(id: string, overrides: Partial<CoverageStep> = {}): CoverageStep {
  return {
    step_id: id,
    position: 1,
    title: `Step ${id}`,
    state: "accepted",
    codes: ["P1"],
    required_codes: ["P1"],
    in_scope: true,
    mode: "automatable",
    quality: "strong",
    verdict: "agent",
    agent: null,
    human: null,
    human_backup: false,
    // HRP-1197: an assigned person is the step's executor.
    executors: overrides.human?.label === "assigned" ? [overrides.human] : [],
    accountable: null,
    needs_accountable: false,
    gap_label: null,
    hours_per_year: null,
    hire_need: null,
    skill_status: "none",
    tentative: false,
    review_human_share: null,
    ...overrides,
  };
}

function coverageOf(...steps: CoverageStep[]): Coverage {
  return {
    container_id: "c-1",
    status: "active",
    mapping_pending: false,
    candidate_step_ids: [],
    shares: null,
    hours: {
      total: 0,
      moves: 0,
      to_review: 0,
      stays: 0,
      unestimated: steps.length,
      to_review_after: 0,
      freed: 0,
      automated: 0,
    },
    quality: { no: 0, draft: 0, strong: steps.length, better_than_human: 0 },
    hourly_rate: null,
    hourly_rate_currency: null,
    money: null,
    review_human_share_default: 50,
    steps,
  };
}

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  getCoverage.mockReset();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function render(coverage: Coverage, canEdit = false) {
  getCoverage.mockResolvedValue(coverage);
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <CoverageTab
          containerId="c-1"
          steps={[]}
          primitives={[]}
          canEdit={canEdit}
          canOpenHireNeed={false}
          canRegisterAgent={false}
          onStepsChanged={() => {}}
        />
      </NextIntlClientProvider>,
    );
  });
}

const byId = (id: string) => document.querySelector<HTMLElement>(`[data-testid="${id}"]`);

it("shows the step's description on its row, and nothing where there is none (HRP-1196)", async () => {
  await render(
    coverageOf(
      row("s-1", { description: "Set up the organisation and its accounts" }),
      row("s-2", { description: null }),
      row("s-3"),
    ),
  );

  expect(byId("coverage-description-s-1")!.textContent).toBe("Set up the organisation and its accounts");
  expect(byId("coverage-description-s-2")).toBeNull();
  expect(byId("coverage-description-s-3")).toBeNull();
});

it("splits the process the way the summary's buckets do (HRP-1200)", () => {
  const o = outcomeOf(PROCESS);
  expect(o.agentAlone.map((r) => r.step_id)).toEqual(["alone-1", "alone-2"]);
  expect(o.agentChecked.map((r) => r.step_id)).toEqual(["checked-1", "checked-2", "checked-3"]);
  expect(o.checkers).toEqual([{ person: ANNA, steps: 2 }]);
  expect(o.unchecked.map((r) => r.step_id)).toEqual(["checked-3"]);
  expect(o.people.map((r) => r.step_id)).toEqual(["people-1", "people-2", "people-3", "people-4"]);
  // Assigned, matched and nobody are three outcomes, never one another.
  expect(o.doers.map((d) => [d.person.name, d.steps])).toEqual([["Ivan Roe", 1]]);
  expect(o.matched.map((d) => [d.person.name, d.steps])).toEqual([["Olga Berg", 1]]);
  expect(o.unassigned.map((r) => r.step_id)).toEqual(["people-2", "people-4"]);
  expect(o.nobody.map((r) => r.step_id)).toEqual(["people-3"]);
  // The one reader of a step's executor (assigned only), for HRP-1197 to widen,
  // and the match beside it.
  expect(stepExecutors(PROCESS[5]).map((p) => p.employee_id)).toEqual(["e-ivan"]);
  expect(stepExecutors(PROCESS[6])).toEqual([]);
  expect(stepMatches(PROCESS[6]).map((p) => p.employee_id)).toEqual(["e-olga"]);
  expect(stepMatches(PROCESS[5])).toEqual([]);
  expect(stepExecutors(PROCESS[7])).toEqual([]);
  // HRP-1197: several people on one step - each one does it, each counted.
  const shared = row("shared", {
    mode: "blocked_judgment",
    verdict: "human",
    human: human(ANNA),
    executors: [human(ANNA), human(IVAN)],
  });
  expect(stepExecutors(shared).map((p) => p.employee_id)).toEqual(["e-anna", "e-ivan"]);
  expect(stepMatches(shared)).toEqual([]);
  const together = outcomeOf([PROCESS[5], shared]);
  expect(together.doers.map(({ person, steps }) => [person.employee_id, steps])).toEqual([
    ["e-ivan", 2],
    ["e-anna", 1],
  ]);
  expect(together.unassigned).toEqual([]);
});

it("reads who does and who checks, and offers Who checks? where nobody does (HRP-1200)", async () => {
  await render(coverageOf(...PROCESS), true);

  expect(byId("coverage-outcome-agent-alone")!.dataset.count).toBe("2");
  expect(byId("coverage-outcome-agent-checked")!.dataset.count).toBe("3");
  expect(byId("coverage-outcome-people")!.dataset.count).toBe("4");
  expect(byId("coverage-outcome-checkers")!.textContent).toBe("Checked by:Anna Petrova· 2 steps");
  expect(byId("coverage-outcome-unchecked")!.textContent).toContain("Reviewer not assigned on 1 step:");
  expect(byId("coverage-outcome-assign-checker-checked-3")!.textContent).toBe("5. Sign the act");
  expect(byId("coverage-outcome-doers")!.textContent).toBe("Done by:Ivan Roe· 1 step");
  expect(byId("coverage-outcome-matched")!.textContent).toBe("Matched, not assigned:Olga Berg· 1 step");
  const unassigned = byId("coverage-outcome-unassigned")!;
  expect(unassigned.dataset.count).toBe("2");
  expect(unassigned.textContent).toContain("Executor not assigned on 2 steps:");
  expect(byId("coverage-outcome-assign-executor-people-2")!.textContent).toBe("7. Train on site");
  expect(byId("coverage-outcome-assign-executor-people-4")!.textContent).toBe("9. Agree the plan");
  expect(byId("coverage-outcome-nobody")!.textContent).toBe("Nobody does 1 step yet.");

  // The link is the row's own Assign: the executor's dialog, not the checker's.
  await act(async () => byId("coverage-outcome-assign-executor-people-2")!.click());
  expect(byId("coverage-modal-assign")!.dataset.field).toBe("executor_employee_ids");
});

it("gives a reader the step to look at instead of an action (HRP-1200)", async () => {
  await render(coverageOf(...PROCESS));

  expect(byId("coverage-outcome-assign-checker-checked-3")).toBeNull();
  expect(byId("coverage-outcome-unchecked-checked-3")!.textContent).toBe("5. Sign the act");
  expect(byId("coverage-outcome-assign-executor-people-2")).toBeNull();
  expect(byId("coverage-outcome-unassigned-people-2")!.textContent).toBe("7. Train on site");
});

it("shows no outcome for a breakdown with nothing in scope (HRP-1200)", async () => {
  await render(coverageOf(PROCESS[9]));

  expect(byId("coverage-outcome")).toBeNull();
});

it("opens what every step type means from the ? by a step's mode (HRP-1204)", async () => {
  await render(coverageOf(row("s-1"), row("s-2", { mode: "review_required" })), true);

  const trigger = byId("coverage-mode-help-s-2")!;
  expect(trigger.tagName).toBe("BUTTON");
  expect(trigger.getAttribute("aria-label")).toBe("What the step types mean");
  expect(byId("coverage-mode-help-s-1")).not.toBeNull();
  expect(byId("coverage-mode-help-s-2-popover")).toBeNull();

  await act(async () => trigger.click());

  const popover = byId("coverage-mode-help-s-2-popover")!;
  expect(popover.textContent).toContain("What the step types mean");
  for (const [mode, label, meaning] of [
    ["automatable", "Automatable", "An agent closes the step by itself; no reviewer is needed."],
    ["draft_then_review", "Draft, then review", "a person reviews and finishes it. That is why a reviewer is needed."],
    ["review_required", "Review required", "a person answers for the result — confirms or signs it"],
    ["blocked_judgment", "Needs a person's judgement", "so an agent does not decide it"],
    ["blocked_physical", "Needs a person on site", "someone on site"],
  ]) {
    const entry = byId(`coverage-mode-help-s-2-${mode}`)!;
    expect(entry.textContent).toContain(label);
    expect(entry.textContent).toContain(meaning);
  }
  // HRP-1182 (QA 20.11): Preliminary is not a mode - it has its own "?".
  expect(popover.textContent).not.toContain(enMessages.coverage.tentativeVerdict);
});
