// @vitest-environment jsdom
//
// HRP-1206: the tab reads "To do (N)" as soon as the page opens - N is the
// steps the tab lists, taken from the coverage the page loads anyway - and
// follows every reload of the tab after an action there.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import type { Coverage, CoverageStep, Gap, WorkContainer } from "@/lib/api/work";

const getContainer = vi.fn();
const listSteps = vi.fn();
const listPrimitives = vi.fn();
const latestDecomposition = vi.fn();
const getCoverage = vi.fn();
const listGaps = vi.fn();

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "p-1" }),
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("@/lib/api/work", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/work")>()),
  workApi: { getContainer, listSteps, listPrimitives, latestDecomposition, getCoverage, listGaps },
}));
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ user: null }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const { default: ContainerPage } = await import("@/app/(dashboard)/coverage/[id]/page");

const CONTAINER = {
  id: "p-1",
  type: "process",
  title: "Client onboarding",
  description: "We onboard a client.",
  status: "active",
  my_access: "read",
} as WorkContainer;

function row(id: string, todo: CoverageStep["todo"]): CoverageStep {
  return {
    step_id: id,
    position: 1,
    title: `Step ${id}`,
    state: "accepted",
    codes: ["P1"],
    required_codes: ["P1"],
    in_scope: true,
    mode: "blocked_judgment",
    quality: "no",
    verdict: todo === "no_owner" ? "gap" : "human",
    agent: null,
    human: null,
    human_backup: false,
    executors: [],
    accountable: null,
    needs_accountable: false,
    gap_label: null,
    hours_per_year: null,
    hire_need: null,
    skill_status: "none",
    tentative: false,
    review_human_share: null,
    todo,
  };
}

function coverageOf(steps: CoverageStep[]): Coverage {
  return {
    container_id: "p-1",
    status: "active",
    mapping_pending: false,
    candidate_step_ids: [],
    shares: null,
    hours: { total: 0, moves: 0, to_review: 0, stays: 0, unestimated: 0, to_review_after: 0, freed: 0, automated: 0 },
    quality: { no: steps.length, draft: 0, strong: 0, better_than_human: 0 },
    hourly_rate: null,
    hourly_rate_currency: null,
    money: null,
    review_human_share_default: 50,
    steps,
  };
}

const gap = (id: string): Gap => ({
  step_id: id,
  position: 1,
  title: `Step ${id}`,
  kind: "no_owner",
  mode: "blocked_judgment",
  gap_label: "hire",
  required_codes: ["P6"],
  codes: ["P6"],
  agent: null,
  skill_status: "none",
  hire_need: null,
});

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  getContainer.mockReset().mockResolvedValue(CONTAINER);
  listSteps.mockReset().mockResolvedValue([]);
  listPrimitives.mockReset().mockResolvedValue([]);
  latestDecomposition.mockReset().mockResolvedValue(null);
  getCoverage.mockReset();
  listGaps.mockReset();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

const tab = () => document.querySelector<HTMLElement>('[data-testid="coverage-tab-gaps"]')!;

async function render() {
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <ContainerPage />
      </NextIntlClientProvider>,
    );
  });
}

it("counts the steps To do lists from the coverage, before the tab is opened", async () => {
  getCoverage.mockResolvedValue(
    coverageOf([row("a", "unassigned"), row("b", "no_owner"), row("c", null), row("d", "not_automated_yet")]),
  );
  await render();

  expect(tab().textContent).toBe("To do (3)");
  expect(tab().dataset.count).toBe("3");
  expect(listGaps).not.toHaveBeenCalled();
});

it("What's next fetches the coverage again: To do may have changed it while the Coverage tab was closed", async () => {
  getCoverage.mockResolvedValue(coverageOf([row("a", "unassigned")]));
  await render();
  expect(tab().textContent).toBe("To do (1)");

  getCoverage.mockResolvedValue(coverageOf([row("a", null)]));
  await act(async () => document.querySelector<HTMLElement>('[data-testid="coverage-btn-what-next"]')!.click());

  expect(getCoverage).toHaveBeenCalledTimes(2);
  expect(tab().textContent).toBe("To do (0)");
  expect(document.querySelector('[data-testid="coverage-what-next"]')).not.toBeNull();
});

it("follows the tab's own reload, and says (0) when nothing is left", async () => {
  getCoverage.mockResolvedValue(coverageOf([row("a", "no_owner"), row("b", "no_owner")]));
  listGaps.mockResolvedValue([gap("a")]);
  await render();
  expect(tab().textContent).toBe("To do (2)");

  await act(async () => tab().click());
  expect(tab().textContent).toBe("To do (1)");

  getCoverage.mockResolvedValue(coverageOf([row("a", null)]));
  await act(async () => document.querySelector<HTMLElement>('[data-testid="coverage-tab-coverage"]')!.click());
  expect(tab().textContent).toBe("To do (0)");
});
