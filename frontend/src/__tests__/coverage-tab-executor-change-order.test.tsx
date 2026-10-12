// @vitest-environment jsdom
//
// HRP-809 REDO (QA 09.10): on a step handed to a person that an agent could
// take, the executor's Change button sits right after the executor's data -
// before the "an agent type could take this" hint - not at the end of the row.

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
  mode: "automatable",
  quality: "strong",
  verdict: "human",
  agent: {
    pack_id: "p-1",
    pack_code: "research",
    agent_id: null,
    agent_name: null,
  },
  human: {
    employee_id: "e-1",
    name: "Jane Doe",
    position: "Controller",
    label: "assigned",
    missing_codes: [],
  },
  human_backup: false,
  accountable: null,
  needs_accountable: false,
  gap_label: null,
  hours_per_year: null,
  hire_need: null,
  skill_status: "none",
  tentative: false,
  review_human_share: null,
};

const COVERAGE: Coverage = {
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
    unestimated: 0,
    to_review_after: 0,
    freed: 0,
    automated: 0,
  },
  quality: { no: 0, draft: 0, strong: 1, better_than_human: 0 },
  hourly_rate: null,
  hourly_rate_currency: null,
  money: null,
  review_human_share_default: 50,
  steps: [STEP],
};

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

async function render(coverage: Coverage) {
  getCoverage.mockResolvedValue(coverage);
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <CoverageTab
          containerId="c-1"
          steps={[]}
          primitives={[]}
          canEdit
          canOpenHireNeed={false}
          canRegisterAgent={false}
          onStepsChanged={() => {}}
        />
      </NextIntlClientProvider>,
    );
  });
}

const byId = (id: string) => document.querySelector<HTMLElement>(`[data-testid="${id}"]`);
const precedes = (a: Element, b: Element) =>
  Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);

it("puts Change right after the executor, before the agent hint", async () => {
  await render(COVERAGE);

  const executor = byId("coverage-executor-s-1")!;
  const button = byId("coverage-btn-assign-executor-s-1")!;
  const agentHint = byId("coverage-agent-s-1")!;

  expect(button.textContent).toBe(enMessages.coverage.changeExecutor);
  expect(precedes(executor, button)).toBe(true);
  expect(precedes(button, agentHint)).toBe(true);
});

it("keeps Assign at the end of the row when nobody is assigned", async () => {
  await render({
    ...COVERAGE,
    steps: [{ ...STEP, verdict: "agent", human: null }],
  });

  const button = byId("coverage-btn-assign-executor-s-1")!;
  const agentRow = byId("coverage-agent-s-1")!;

  expect(button.textContent).toBe(enMessages.coverage.assignExecutor);
  expect(precedes(agentRow, button)).toBe(true);
});
