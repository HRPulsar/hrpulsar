// @vitest-environment jsdom
//
// HRP-959: a person the company named on a step stays on the row after going
// on leave or leaving the company - the same name, with their status chip in
// the shared EmployeeSummaryLine - instead of the step passing to whoever the
// match finds or "Who checks?" coming back.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import type { Coverage, CoverageStep } from "@/lib/api/work";

const getCoverage = vi.fn();

vi.mock("@/lib/api/work", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/work")>()),
  workApi: { getCoverage },
}));
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ user: null }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const { CoverageTab } = await import("@/components/coverage/coverage-tab");

const STEP: CoverageStep = {
  step_id: "s-1",
  position: 1,
  title: "Check the invoice",
  state: "accepted",
  codes: ["P1"],
  required_codes: ["P1"],
  in_scope: true,
  mode: "review_required",
  quality: "draft",
  verdict: "human",
  agent: null,
  human: {
    employee_id: "e-1",
    name: "Jane Doe",
    position: "Controller",
    status: "on_leave",
    label: "assigned",
    missing_codes: [],
  },
  human_backup: false,
  accountable: { employee_id: "e-2", name: "John Roe", position: null, status: "terminated" },
  needs_accountable: false,
  gap_label: null,
  hours_per_year: null,
  hire_need: null,
  skill_status: "none",
  tentative: false,
  review_human_share: null,
};

function coverageOf(...steps: CoverageStep[]): Coverage {
  return {
    container_id: "c-1",
    status: "active",
    mapping_pending: false,
    candidate_step_ids: [],
    shares: null,
    hours: { total: 0, moves: 0, to_review: 0, stays: 0, unestimated: steps.length, to_review_after: 0, freed: 0, automated: 0 },
    quality: { no: 0, draft: steps.length, strong: 0, better_than_human: 0 },
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
  vi.restoreAllMocks();
});

async function render(coverage: Coverage) {
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
}

const byId = (id: string) => document.querySelector<HTMLElement>(`[data-testid="${id}"]`);

it("keeps the assigned executor and accountable on the row with their status chips", async () => {
  await render(coverageOf(STEP));

  expect(byId("coverage-link-executor-s-1")!.textContent).toBe("Jane Doe");
  expect(byId("coverage-executor-summary-s-1-position")!.textContent).toBe("Controller");
  expect(byId("coverage-executor-summary-s-1-status")!.textContent).toBe("on leave");
  // Their skills did not leave with them: no "No matching skills" badge.
  expect(byId("coverage-executor-unmatched-s-1")).toBeNull();

  expect(byId("coverage-link-accountable-s-1")!.textContent).toBe("John Roe");
  expect(byId("coverage-accountable-summary-s-1-status")!.textContent).toBe("terminated");
  expect(byId("coverage-needs-accountable-s-1")).toBeNull();
});

it("shows no chip for an active person", async () => {
  await render(
    coverageOf({
      ...STEP,
      human: { ...STEP.human!, status: "active" },
      accountable: { ...STEP.accountable!, status: undefined },
    }),
  );

  expect(byId("coverage-executor-summary-s-1-status")).toBeNull();
  expect(byId("coverage-accountable-summary-s-1")).toBeNull();
});
