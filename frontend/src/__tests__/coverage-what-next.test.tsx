// @vitest-environment jsdom
//
// HRP-1205: the closing popup of a breakdown. "What's next" opens it on any
// process; in a demo sandbox it also opens by itself, once per process, when a
// breakdown finishes in front of the visitor - after the demo's own card, never
// over it, and never on opening a process broken down before.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import type { Coverage, CoverageStep, DecompositionSession, WorkContainer, WorkStep } from "@/lib/api/work";

const getContainer = vi.fn();
const listSteps = vi.fn();
const listPrimitives = vi.fn();
const latestDecomposition = vi.fn();
const applyDecomposition = vi.fn();
const getCoverage = vi.fn();
let authUser: { tenant_is_demo?: boolean } | null = null;

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "p-1" }),
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("@/lib/api/work", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/work")>()),
  workApi: { getContainer, listSteps, listPrimitives, latestDecomposition, applyDecomposition, getCoverage },
}));
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ user: authUser }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const { default: ContainerPage } = await import("@/app/(dashboard)/coverage/[id]/page");
const { WhatNextDialog } = await import("@/components/coverage/what-next-dialog");

const CONTAINER: WorkContainer = {
  id: "p-1",
  tenant_id: "t-1",
  type: "process",
  title: "Client onboarding",
  description: "We onboard a client.",
  goal: null,
  status: "draft",
  visibility: "restricted",
  owner_id: null,
  created_by_id: null,
  source: "manual",
  catalog_version: "v1.1",
  gap_default_label: "hire",
  my_access: "manage",
  coverage_summary: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function session(status: DecompositionSession["status"]): DecompositionSession {
  return {
    id: "run-1",
    container_id: "p-1",
    status,
    phase: null,
    error_code: null,
    error_message: null,
    payload: status === "ready" ? { steps: [] } : null,
    created_at: "2026-01-01T00:00:00Z",
    finished_at: null,
  };
}

function row(id: string, overrides: Partial<CoverageStep> = {}): CoverageStep {
  return {
    step_id: id,
    position: 1,
    title: `Step ${id}`,
    state: "system_suggested",
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
    tentative: true,
    review_human_share: null,
    ...overrides,
  };
}

const STEPS = [
  row("a", { position: 1 }),
  row("b", { position: 2, mode: "review_required", title: "Sign the act" }),
  row("c", { position: 3, mode: "review_required", accountable: { employee_id: "e-1", name: "Anna Petrova", position: null } }),
  row("d", { position: 4, mode: "blocked_judgment", verdict: "gap" }),
  // People keep three: one assigned, one only matched, one nobody covers (d).
  row("e", {
    position: 5,
    mode: "blocked_judgment",
    verdict: "human",
    human: { employee_id: "e-2", name: "Ivan Roe", position: null, label: "assigned", missing_codes: [] },
  }),
  row("f", {
    position: 6,
    mode: "blocked_physical",
    title: "Train on site",
    verdict: "human",
    human: { employee_id: "e-3", name: "Olga Berg", position: null, label: "assessed", missing_codes: [] },
  }),
];

function coverageOf(steps: CoverageStep[]): Coverage {
  return {
    container_id: "p-1",
    status: "draft",
    mapping_pending: false,
    candidate_step_ids: [],
    shares: null,
    hours: { total: 0, moves: 0, to_review: 0, stays: 0, unestimated: steps.length, to_review_after: 0, freed: 0, automated: 0 },
    quality: { no: 0, draft: 0, strong: steps.length, better_than_human: 0 },
    hourly_rate: null,
    hourly_rate_currency: null,
    money: null,
    review_human_share_default: 50,
    steps,
  };
}

const workStep = (id: string) => ({ id, title: `Step ${id}` }) as WorkStep;

let container: HTMLDivElement;
let root: Root;
let applied: boolean;

beforeEach(() => {
  authUser = null;
  applied = false;
  localStorage.clear();
  getContainer.mockReset().mockResolvedValue(CONTAINER);
  listPrimitives.mockReset().mockResolvedValue([]);
  listSteps.mockReset().mockImplementation(async () => (applied ? STEPS.map((s) => workStep(s.step_id)) : []));
  applyDecomposition.mockReset().mockImplementation(async () => {
    applied = true;
  });
  getCoverage.mockReset().mockImplementation(async () => coverageOf(applied ? STEPS : []));
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  document.querySelectorAll('[data-testid="demo-feedback-popup"]').forEach((el) => el.remove());
  vi.useRealTimers();
});

const byId = (id: string) => document.querySelector<HTMLElement>(`[data-testid="${id}"]`);

async function render() {
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <ContainerPage />
      </NextIntlClientProvider>,
    );
  });
}

async function wait(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

/** A first breakdown runs while the page is open, then applies itself. */
async function breakDownLive() {
  vi.useFakeTimers();
  latestDecomposition.mockReset().mockResolvedValueOnce(session("running")).mockResolvedValueOnce(session("ready"));
  latestDecomposition.mockResolvedValue(session("applied"));
  await render();
  expect(byId("coverage-banner-generating")).not.toBeNull();
  // One poll: the run is ready, applies itself, and the tab reloads.
  await wait(5_000);
  expect(applyDecomposition).toHaveBeenCalledTimes(1);
}

describe("in a demo sandbox", () => {
  beforeEach(() => {
    authUser = { tenant_is_demo: true };
  });

  it("opens by itself once the breakdown finishes in front of the visitor", async () => {
    await breakDownLive();
    // Not before the demo card's own moment has had its chance.
    expect(byId("coverage-what-next")).toBeNull();

    await wait(2_000);
    expect(byId("coverage-what-next")).not.toBeNull();
    expect(localStorage.getItem("coverage_what_next:p-1")).toBe("1");
  });

  it("waits for the demo card on screen and opens when it closes", async () => {
    const card = document.createElement("form");
    card.dataset.testid = "demo-feedback-popup";
    document.body.appendChild(card);

    await breakDownLive();
    await wait(10_000);
    expect(byId("coverage-what-next")).toBeNull();

    await act(async () => card.remove());
    expect(byId("coverage-what-next")).not.toBeNull();
  });

  it("does not open again on a process it already opened on", async () => {
    localStorage.setItem("coverage_what_next:p-1", "1");
    await breakDownLive();
    await wait(10_000);

    expect(byId("coverage-what-next")).toBeNull();
  });

  it("stays shut on a process broken down before, behind its button", async () => {
    vi.useFakeTimers();
    applied = true;
    latestDecomposition.mockReset().mockResolvedValue(session("applied"));
    await render();
    await wait(10_000);
    expect(byId("coverage-what-next")).toBeNull();

    await act(async () => byId("coverage-btn-what-next")!.click());
    expect(byId("coverage-what-next")).not.toBeNull();
  });
});

describe("outside a demo", () => {
  it("never opens by itself; What's next opens it", async () => {
    await breakDownLive();
    await wait(10_000);
    expect(byId("coverage-what-next")).toBeNull();

    await act(async () => byId("coverage-btn-what-next")!.click());
    expect(byId("coverage-what-next")).not.toBeNull();
  });

  it("offers no What's next before there is a step in scope", async () => {
    latestDecomposition.mockReset().mockResolvedValue(null);
    await render();

    expect(byId("coverage-btn-what-next")).toBeNull();
  });
});

describe("the popup", () => {
  async function open(steps: CoverageStep[]) {
    await act(async () => {
      root.render(
        <NextIntlClientProvider locale="en" messages={enMessages}>
          <WhatNextDialog steps={steps} onClose={() => {}} />
        </NextIntlClientProvider>,
      );
    });
  }

  it("says who does what with the summary's figures, and how to go on", async () => {
    await open(STEPS);

    expect(byId("coverage-outcome-agent-alone")!.dataset.count).toBe("1");
    expect(byId("coverage-outcome-agent-checked")!.dataset.count).toBe("2");
    expect(byId("coverage-outcome-people")!.dataset.count).toBe("3");
    // Assigned, matched and nobody stay three outcomes here too.
    expect(byId("coverage-outcome-doers")!.textContent).toBe("Done by:Ivan Roe· 1 step");
    expect(byId("coverage-outcome-matched")!.textContent).toBe("Matched, not assigned:Olga Berg· 1 step");
    expect(byId("coverage-outcome-nobody")!.textContent).toBe("Nobody does 1 step yet.");
    // Over the page: a step without a reviewer or executor is named, not a link behind the popup.
    expect(byId("coverage-outcome-unchecked-b")!.tagName).toBe("SPAN");
    expect(byId("coverage-outcome-unassigned-f")!.tagName).toBe("SPAN");
    expect(byId("coverage-what-next-executor")!.textContent).toBe(
      "Assign who does the steps that stay with people: “Assign” on the step.",
    );
    expect(byId("coverage-what-next-checker")!.textContent).toBe(
      "Name who checks the agent's work: “Who checks?” on the step.",
    );
    expect(byId("coverage-what-next-download")!.textContent).toBe(
      "Download the instruction for the agent: on the To do tab, or with the button next to the step.",
    );
    expect(byId("coverage-what-next-bot")!.textContent).toContain("the agent is not built into the product");
    // HRP-1182 (QA 20.11): the intro leads into the block, which has no heading of its own here.
    const popup = byId("coverage-what-next")!;
    expect(popup.textContent).toContain("The steps are split between people and agents:");
    expect(popup.textContent).not.toContain(enMessages.coverage.outcomeTitle);
    expect(popup.textContent).toContain(enMessages.coverage.whatNextHowTitle);
  });

  it("drops the reviewer and executor steps once nothing lacks one", async () => {
    await open(STEPS.filter((s) => s.step_id !== "b" && s.step_id !== "f"));

    expect(byId("coverage-what-next-checker")).toBeNull();
    expect(byId("coverage-what-next-executor")).toBeNull();
    expect(byId("coverage-outcome-matched")).toBeNull();
    expect(byId("coverage-what-next-download")).not.toBeNull();
  });
});
