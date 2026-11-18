// @vitest-environment jsdom
//
// HRP-1192 / HRP-1202: a skill being written is followed by one poll on the
// process page, not by the dialog that started it. "Generate N" on the To
// do tab used to leave its rows on "Generating" until F5, and closing the
// dialog stopped the watch. Here the page's poll sees the step ready and
// every place that shows the status - the To do row, the Coverage row, the
// agent guide - reloads without a refresh.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import type { Coverage, CoverageStep, Gap, StepSkill } from "@/lib/api/work";

const listGaps = vi.fn();
const getCoverage = vi.fn();
const generateSkill = vi.fn();
const getSkill = vi.fn();
const toastSuccess = vi.fn();
const toastError = vi.fn();

vi.mock("@/lib/api/work", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/work")>()),
  workApi: { listGaps, getCoverage, generateSkill, getSkill },
}));
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ user: null }) }));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ canViewSection: () => true }),
}));
vi.mock("@/hooks/use-cost-confirmation", () => ({
  useCostConfirmation: () => ({ cost: null }),
}));
vi.mock("@/lib/ee-hooks", () => ({ EECreditCostBadge: () => null }));
vi.mock("sonner", () => ({ toast: { success: toastSuccess, error: toastError } }));

const { GapsTab } = await import("@/components/coverage/gaps-tab");
const { CoverageTab } = await import("@/components/coverage/coverage-tab");
const { useSkillWatch } = await import("@/components/coverage/use-skill-watch");

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

const SKILL: StepSkill = {
  id: "sk-1",
  step_id: "s-1",
  pack_id: null,
  status: "ready",
  skill_name: "check-invoice",
  content: "# Check",
  error_code: null,
  error_message: null,
  generated_at: "2026-11-17T00:00:00Z",
};

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
  verdict: "agent",
  agent: { pack_id: "p-1", pack_code: "extraction", agent_id: null, agent_name: null },
  human: null,
  human_backup: false,
  executors: [],
  accountable: null,
  needs_accountable: false,
  gap_label: null,
  hours_per_year: null,
  hire_need: null,
  skill_status: "generating",
  tentative: false,
  review_human_share: null,
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
  quality: { no: 0, draft: 0, strong: 1, better_than_human: 0 },
  hourly_rate: null,
  hourly_rate_currency: null,
  money: null,
  review_human_share_default: 50,
  steps: [STEP],
};

/** The process page's side: one watch, handed to the tab on screen. */
function Page({ tab, mount = 0 }: { tab: "gaps" | "coverage"; mount?: number }) {
  const skillWatch = useSkillWatch();
  const props = {
    containerId: "c-1",
    primitives: [],
    canEdit: true,
    canOpenHireNeed: false,
    canRegisterAgent: false,
    onStepsChanged: () => {},
    skillWatch,
  };
  // `mount` remounts the tab, as switching tabs does: it loads afresh.
  return tab === "gaps" ? (
    <GapsTab key={mount} {...props} />
  ) : (
    <CoverageTab key={mount} {...props} steps={[]} />
  );
}

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.useFakeTimers();
  for (const fn of [listGaps, getCoverage, generateSkill, getSkill, toastSuccess, toastError]) {
    fn.mockReset();
  }
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.useRealTimers();
});

async function render(tab: "gaps" | "coverage", mount = 0) {
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <Page tab={tab} mount={mount} />
      </NextIntlClientProvider>,
    );
  });
}

const byId = (id: string) => document.querySelector<HTMLElement>(`[data-testid="${id}"]`);

async function click(testId: string) {
  const el = byId(testId);
  expect(el, testId).toBeTruthy();
  await act(async () => {
    el!.click();
  });
}

async function tick(ms = 3_000) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

it("shows the bulk run's skills ready on the To do tab without a reload", async () => {
  const s2 = { ...GAP, step_id: "s-2", position: 2 };
  listGaps
    .mockResolvedValueOnce([GAP, s2])
    .mockResolvedValueOnce([
      { ...GAP, skill_status: "generating" },
      { ...s2, skill_status: "generating" },
    ])
    .mockResolvedValue([
      { ...GAP, skill_status: "ready" },
      { ...s2, skill_status: "ready" },
    ]);
  generateSkill.mockResolvedValue({ ...SKILL, status: "generating" });
  getSkill.mockResolvedValue(SKILL);

  await render("gaps");
  await click("coverage-btn-generate-all-skills");
  await click("confirm-dialog-btn-confirm");

  expect(byId("coverage-todo-row-s-1-skill-status")!.dataset.status).toBe("generating");
  expect(getSkill).not.toHaveBeenCalled();

  await tick();

  expect(getSkill.mock.calls.map((c) => c[0]).sort()).toEqual(["s-1", "s-2"]);
  for (const id of ["s-1", "s-2"]) {
    const status = byId(`coverage-todo-row-${id}-skill-status`)!;
    expect(status.dataset.status).toBe("ready");
    expect(status.textContent).toBe(enMessages.coverage.skillStatus_ready);
    expect(byId(`coverage-todo-row-${id}-btn-skill`)!.textContent).toContain(
      enMessages.coverage.openSkill,
    );
  }
  const said = toastSuccess.mock.calls.map((c) => c[0]);
  expect(said).toContain("The skill for step 1 is ready");
  expect(said).toContain("The skill for step 2 is ready");

  // Nothing is generating any more: the poll stops.
  await tick(30_000);
  expect(getSkill).toHaveBeenCalledTimes(2);
});

it("updates the Coverage row and the agent guide once the skill is written", async () => {
  getCoverage
    .mockResolvedValueOnce(COVERAGE)
    .mockResolvedValue({ ...COVERAGE, steps: [{ ...STEP, skill_status: "ready" }] });
  getSkill.mockResolvedValueOnce({ ...SKILL, status: "generating" }).mockResolvedValue(SKILL);

  await render("coverage");
  expect(byId("coverage-skill-status-s-1")!.dataset.status).toBe("generating");
  expect(byId("coverage-guide-skill-s-1")!.dataset.status).toBe("generating");

  await tick();
  // Still writing: nothing reloads.
  expect(getCoverage).toHaveBeenCalledTimes(1);

  await tick();
  expect(byId("coverage-skill-status-s-1")!.dataset.status).toBe("ready");
  expect(byId("coverage-btn-get-skill-s-1")!.textContent).toContain(enMessages.coverage.openSkill);
  expect(byId("coverage-guide-skill-s-1")!.dataset.status).toBe("ready");
});

it("brings a failed generation to the screen in the reader's words", async () => {
  getCoverage
    .mockResolvedValueOnce(COVERAGE)
    .mockResolvedValue({ ...COVERAGE, steps: [{ ...STEP, skill_status: "failed" }] });
  getSkill.mockResolvedValue({
    ...SKILL,
    status: "failed",
    content: null,
    error_code: "overload",
    error_message: "upstream overloaded",
  });

  await render("coverage");
  await tick();

  expect(toastError).toHaveBeenCalledWith(`Step 1: ${enMessages.coverage.genErrorOverload}`);
  expect(byId("coverage-skill-status-s-1")!.dataset.status).toBe("failed");
});

/** A server that answers both the list and the skill row from one status,
 * as the real one does; generating again flips it back. */
function serveSkill(initial: StepSkill["status"]) {
  const server = { status: initial };
  getSkill.mockImplementation(async () => ({
    ...SKILL,
    status: server.status,
    content: server.status === "ready" ? "# Check" : null,
  }));
  listGaps.mockImplementation(async () => [{ ...GAP, skill_status: server.status }]);
  generateSkill.mockImplementation(async () => {
    server.status = "generating";
    return { ...SKILL, status: "generating", content: null };
  });
  return server;
}

it("follows a long generation to its late file, with no failure on the way", async () => {
  // Review: the old 4-minute bound reported a five-minute run as failed and
  // left the step on "Generating" when the file came - the server keeps a
  // run alive for 15 minutes.
  const server = serveSkill("generating");

  await render("gaps");
  await tick(5 * 60_000);
  expect(toastError).not.toHaveBeenCalled();
  expect(byId("coverage-todo-row-s-1-skill-status")!.dataset.status).toBe("generating");

  server.status = "ready";
  await tick();

  expect(toastError).not.toHaveBeenCalled();
  expect(toastSuccess).toHaveBeenCalledWith("The skill for step 1 is ready");
  expect(byId("coverage-todo-row-s-1-skill-status")!.dataset.status).toBe("ready");
});

it("stops silently past the server's cutoff, and follows the next run again", async () => {
  // No answer but "generating" for longer than the server ever keeps a run:
  // the watch stops without claiming a failure it never saw.
  const server = serveSkill("generating");

  await render("gaps");
  await tick(17 * 60_000);
  expect(toastError).not.toHaveBeenCalled();
  const calls = getSkill.mock.calls.length;
  await tick(30_000);
  // Given up: the reload that still reads "generating" does not restart it.
  expect(getSkill).toHaveBeenCalledTimes(calls);

  // A later load reads the run failed; the company retries it.
  server.status = "failed";
  await render("gaps", 1);
  expect(byId("coverage-todo-row-s-1-skill-status")!.dataset.status).toBe("failed");
  await click("coverage-todo-row-s-1-btn-skill");
  await click("coverage-skill-confirm-btn-confirm");
  expect(generateSkill).toHaveBeenCalledWith("s-1");
  expect(byId("coverage-todo-row-s-1-skill-status")!.dataset.status).toBe("generating");

  // The new run is followed again and lands without a reload.
  server.status = "ready";
  await tick();
  expect(toastSuccess).toHaveBeenCalledWith("The skill for step 1 is ready");
  expect(byId("coverage-todo-row-s-1-skill-status")!.dataset.status).toBe("ready");
});
