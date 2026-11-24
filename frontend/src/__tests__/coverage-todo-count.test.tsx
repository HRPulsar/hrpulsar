// @vitest-environment jsdom
//
// HRP-1206: the tab reads "To do (N)" as soon as the page opens - N is the
// steps the tab lists, taken from the coverage the page loads anyway - and
// follows every reload of the tab after an action there.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import type { Coverage, CoverageStep, Gap, WorkContainer } from "@/lib/api/work";

const getContainer = vi.fn();
const listSteps = vi.fn();
const listPrimitives = vi.fn();
const latestDecomposition = vi.fn();
const getCoverage = vi.fn();
const listGaps = vi.fn();
const updateContainer = vi.fn();
const deleteContainer = vi.fn();
const startDecomposition = vi.fn();
const push = vi.fn();

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "p-1" }),
  usePathname: () => "/coverage/p-1",
  // The open tab rides in `?tab=` (HRP-1234), written through the History API.
  useSearchParams: () => new URLSearchParams(window.location.search),
  useRouter: () => ({ push }),
}));
vi.mock("@/lib/api/work", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/work")>()),
  workApi: {
    getContainer,
    listSteps,
    listPrimitives,
    latestDecomposition,
    getCoverage,
    listGaps,
    updateContainer,
    deleteContainer,
    startDecomposition,
  },
}));
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ user: null }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
// The access dialog reads the server by itself; here it only changes the owner.
vi.mock("@/components/coverage/access-dialog", () => ({
  AccessDialog: ({ onOwnerChanged }: { onOwnerChanged: () => void }) => (
    <button type="button" data-testid="access-dialog-stub" onClick={onOwnerChanged} />
  ),
}));

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
  window.history.replaceState(null, "", "/coverage/p-1");
  getContainer.mockReset().mockResolvedValue(CONTAINER);
  listSteps.mockReset().mockResolvedValue([]);
  listPrimitives.mockReset().mockResolvedValue([]);
  latestDecomposition.mockReset().mockResolvedValue(null);
  getCoverage.mockReset();
  listGaps.mockReset();
  updateContainer.mockReset();
  deleteContainer.mockReset();
  startDecomposition.mockReset();
  push.mockReset();
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

/** A click on a tab writes the address; the router, which follows the
 * History API, then renders the page again. */
async function open(tabId: string) {
  await act(async () =>
    document.querySelector<HTMLElement>(`[data-testid="coverage-tab-${tabId}"]`)!.click(),
  );
  await render();
}

it("opens the tab the address names, so a link can lead to To do", async () => {
  window.history.replaceState(null, "", "?tab=gaps");
  getCoverage.mockResolvedValue(coverageOf([row("a", "no_owner")]));
  listGaps.mockResolvedValue([gap("a")]);
  await render();

  expect(tab().dataset.state).toBe("active");
  expect(document.querySelector('[data-testid="coverage-todo-no-owner"]')).not.toBeNull();
  // The Coverage tab never mounted: the page read the coverage itself.
  expect(document.querySelector('[data-testid="coverage-btn-what-next"]')).not.toBeNull();

  await open("steps");
  expect(window.location.search).toBe("?tab=steps");
  expect(tab().dataset.state).toBe("inactive");
});

// HRP-1229: the goal and the description sit in two cards, the goal first,
// and a long text shows its beginning until it is unfolded.
it("shows the goal and the description side by side and folds a long one", async () => {
  const long = "Every month Finance closes the books. ".repeat(12).trim();
  getContainer.mockResolvedValue({ ...CONTAINER, goal: "Close in five days", description: long });
  getCoverage.mockResolvedValue(coverageOf([]));
  await render();

  const goal = document.querySelector<HTMLElement>('[data-testid="coverage-detail-goal"]')!;
  const description = document.querySelector<HTMLElement>(
    '[data-testid="coverage-detail-description"]',
  )!;
  expect(goal.textContent).toBe("GoalClose in five days");
  expect(goal.compareDocumentPosition(description) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(goal.querySelector("button")).toBeNull();

  const toggle = description.querySelector<HTMLElement>(
    '[data-testid="coverage-detail-description-toggle"]',
  )!;
  expect(description.textContent).not.toContain(long);
  expect(toggle.textContent).toBe("Show more");
  await act(async () => toggle.click());
  expect(description.textContent).toContain(long);
  expect(toggle.textContent).toBe("Show less");
});

it("folds a description that is short in characters and long in lines", async () => {
  const list = ["one", "two", "three", "four", "five", "six"].join("\n");
  getContainer.mockResolvedValue({ ...CONTAINER, description: list });
  getCoverage.mockResolvedValue(coverageOf([]));
  await render();

  const description = document.querySelector<HTMLElement>(
    '[data-testid="coverage-detail-description"]',
  )!;
  expect(description.querySelector("p")!.textContent).toBe("one\ntwo\nthree\nfour…");
  await act(async () =>
    description
      .querySelector<HTMLElement>('[data-testid="coverage-detail-description-toggle"]')!
      .click(),
  );
  expect(description.querySelector("p")!.textContent).toBe(list);
});

it("opened on Steps, still counts To do and offers What's next", async () => {
  window.history.replaceState(null, "", "?tab=steps");
  getCoverage.mockResolvedValue(coverageOf([row("a", "unassigned"), row("b", "no_owner")]));
  await render();

  expect(tab().textContent).toBe("To do (2)");
  expect(document.querySelector('[data-testid="coverage-btn-what-next"]')).not.toBeNull();
});

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

  await open("gaps");
  expect(tab().textContent).toBe("To do (1)");

  getCoverage.mockResolvedValue(coverageOf([row("a", null)]));
  await open("coverage");
  expect(tab().textContent).toBe("To do (0)");
});

// HRP-1228: the page's own kebab - what it archived shows at once, a
// delete leaves for the list, and neither a breakdown nor an archive starts
// while the other is on its way.
describe("the kebab on the page", () => {
  const MANAGED = { ...CONTAINER, my_access: "manage" } as WorkContainer;
  const byId = (testId: string) =>
    document.querySelector<HTMLElement>(`[data-testid="${testId}"]`);
  const off = (testId: string) => byId(testId)!.hasAttribute("data-disabled");

  beforeEach(() => {
    getContainer.mockResolvedValue(MANAGED);
    getCoverage.mockResolvedValue(coverageOf([]));
  });

  async function pick(item: string) {
    await act(async () => byId("coverage-btn-actions")!.click());
    await act(async () => byId(`coverage-btn-${item}`)!.click());
  }

  it("holds Generate while archiving, then shows the process archived", async () => {
    let answer!: (archived: WorkContainer) => void;
    updateContainer.mockImplementation(() => new Promise((resolve) => (answer = resolve)));
    await render();

    await pick("archive");
    expect(off("coverage-btn-generate")).toBe(true);

    await act(async () => answer({ ...MANAGED, status: "archived" }));
    expect(byId("coverage-detail-status")!.dataset.status).toBe("archived");
    expect(byId("coverage-btn-generate")).toBeNull();
  });

  it("keeps Archive and Delete off while a breakdown starts", async () => {
    startDecomposition.mockReturnValue(new Promise(() => {}));
    await render();

    await act(async () => byId("coverage-btn-generate")!.click());
    await act(async () => byId("coverage-btn-actions")!.click());
    expect(off("coverage-btn-archive")).toBe(true);
    expect(off("coverage-btn-delete")).toBe(true);
  });

  it("leaves for the list once the process is deleted", async () => {
    deleteContainer.mockResolvedValue(undefined);
    await render();

    await pick("delete");
    await act(async () => byId("coverage-btn-delete-confirm")!.click());
    expect(deleteContainer).toHaveBeenCalledExactlyOnceWith("p-1");
    expect(push).toHaveBeenCalledExactlyOnceWith("/coverage");
  });

  it("reads the process again once its owner changed", async () => {
    await render();
    expect(getContainer).toHaveBeenCalledOnce();

    await pick("access");
    await act(async () => byId("access-dialog-stub")!.click());
    expect(getContainer).toHaveBeenCalledTimes(2);
  });
});
