// @vitest-environment jsdom
//
// HRP-1182: the Coverage tab says what the product does in plain words. The
// thesis stands on the tab itself, not only on the site; the company's own
// agent reads by its name instead of "<agent type> via <name>"; and the
// agent the company already uses is asked for before the checker of its work.

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
  title: "Build the account",
  state: "accepted",
  codes: ["P9"],
  required_codes: ["P9"],
  in_scope: true,
  mode: "review_required",
  quality: "draft",
  verdict: "agent",
  agent: { pack_id: "p-1", pack_code: "artifact_builder", agent_id: null, agent_name: null },
  human: null,
  executors: [],
  human_backup: false,
  accountable: null,
  needs_accountable: true,
  gap_label: null,
  hours_per_year: null,
  hire_need: null,
  skill_status: "none",
  tentative: false,
  review_human_share: 50,
};

const COVERAGE: Coverage = {
  container_id: "c-1",
  status: "active",
  mapping_pending: false,
  candidate_step_ids: ["s-1"],
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
  quality: { no: 0, draft: 1, strong: 0, better_than_human: 0 },
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

async function render(step: CoverageStep) {
  getCoverage.mockResolvedValue({ ...COVERAGE, steps: [step] });
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <CoverageTab
          containerId="c-1"
          steps={[]}
          primitives={[]}
          canEdit
          canOpenHireNeed={false}
          canRegisterAgent
          onStepsChanged={() => {}}
        />
      </NextIntlClientProvider>,
    );
  });
}

const byId = (id: string) => document.querySelector<HTMLElement>(`[data-testid="${id}"]`);

it("states the thesis on the tab", async () => {
  await render(STEP);

  expect(byId("coverage-thesis")!.textContent).toBe(enMessages.coverage.coverageThesis);
});

it("names the company's own agent without gluing it to the agent type", async () => {
  await render({ ...STEP, agent: { ...STEP.agent!, agent_id: "a-1", agent_name: "Cloud" } });

  const agent = byId("coverage-agent-s-1")!;
  expect(agent.textContent).toBe("Your agent “Cloud” already does this step");
  expect(byId("coverage-pack-chip-s-1")).toBeNull();
});

it("shows the agent type while the company names no agent of its own", async () => {
  await render(STEP);

  expect(byId("coverage-pack-chip-s-1")).not.toBeNull();
});

it("asks for the agent in use before the checker of its work", async () => {
  await render(STEP);

  const useAgent = byId("coverage-btn-use-agent-s-1")!;
  const whoChecks = byId("coverage-btn-assign-accountable-s-1")!;
  expect(useAgent.compareDocumentPosition(whoChecks) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});
