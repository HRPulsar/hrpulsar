// @vitest-environment jsdom
//
// HRP-863: the company's override of a step's mode and agent pack, right on
// the coverage row. An editor of a step in scope gets the two menus; a reader
// and a step out of scope do not. A pick PATCHes the step, hands the saved
// step to the steps tab and re-reads the coverage - the summary moves with it.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import type { Coverage, CoverageStep } from "@/lib/api/work";

const getCoverage = vi.fn();
const updateStep = vi.fn();
const listPacks = vi.fn();

vi.mock("@/lib/api/work", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/work")>()),
  workApi: { getCoverage, updateStep, listPacks },
}));
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ user: null }) }));
const toastError = vi.fn();
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: toastError } }));

const { CoverageTab } = await import("@/components/coverage/coverage-tab");

const STEP: CoverageStep = {
  step_id: "s-1",
  position: 1,
  title: "Check the invoice",
  state: "accepted",
  codes: ["P6"],
  required_codes: ["P6"],
  in_scope: true,
  mode: "blocked_judgment",
  quality: "no",
  verdict: "gap",
  agent: null,
  human: null,
  human_backup: false,
  accountable: null,
  needs_accountable: false,
  gap_label: "hire",
  hours_per_year: null,
  hire_need: null,
  skill_status: "none",
  tentative: false,
  review_human_share: null,
};

function coverageOf(step: CoverageStep): Coverage {
  return {
    container_id: "c-1",
    status: "active",
    mapping_pending: false,
    candidate_step_ids: [],
    shares: null,
    hours: { total: 0, moves: 0, to_review: 0, stays: 0, unestimated: 1 , to_review_after: 0, freed: 0, automated: 0 },
    quality: { no: 1, draft: 0, strong: 0, better_than_human: 0 },
    hourly_rate: null,
    hourly_rate_currency: null,
    money: null,
    review_human_share_default: 50,
    steps: [step],
  };
}

let container: HTMLDivElement;
let root: Root;
const onStepsChanged = vi.fn();

beforeEach(() => {
  for (const mock of [getCoverage, updateStep, listPacks, onStepsChanged, toastError]) mock.mockReset();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function render(canEdit: boolean) {
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
          onStepsChanged={onStepsChanged}
        />
      </NextIntlClientProvider>,
    );
  });
}

const byId = (id: string) => document.querySelector(`[data-testid="${id}"]`);

async function click(id: string) {
  const el = byId(id);
  expect(el, id).not.toBeNull();
  await act(async () => {
    (el as HTMLElement).click();
  });
}

it("gives an editor the two menus and marks a value set by hand", async () => {
  getCoverage.mockResolvedValue(
    coverageOf({
      ...STEP,
      mode: "automatable",
      mode_manual: true,
      verdict: "agent",
      gap_label: null,
      agent: { pack_id: "p-1", pack_code: "drafting", pack_manual: true, agent_id: null, agent_name: null },
    }),
  );

  await render(true);

  expect(byId("coverage-btn-change-mode-s-1")).not.toBeNull();
  expect(byId("coverage-btn-change-pack-s-1")!.textContent).toBe(enMessages.coverage.changeAgent);
  expect(byId("coverage-manual-mode-s-1")!.textContent).toBe(enMessages.coverage.manualChip);
  expect(byId("coverage-manual-pack-s-1")).not.toBeNull();
  // Nothing is fetched until a pack menu is opened.
  expect(listPacks).not.toHaveBeenCalled();
});

it("keeps the verdict and the quality light off a hand-set step with no agent named", async () => {
  getCoverage.mockResolvedValue(coverageOf({ ...STEP, mode: "automatable", mode_manual: true }));

  await render(true);

  // The company said the step can go to an agent; the row does not answer
  // that with "nobody covers this" or with the quality of the codes.
  expect(byId("coverage-verdict-s-1")).toBeNull();
  expect(byId("coverage-quality-s-1")).toBeNull();
  expect(byId("coverage-mode-s-1")!.textContent).toContain(enMessages.coverage.mode_automatable);
  expect(byId("coverage-manual-mode-s-1")).not.toBeNull();
});

it("brings both back once an agent is named on the hand-set step", async () => {
  const named = {
    ...STEP,
    mode: "automatable" as const,
    mode_manual: true,
    agent: { pack_id: "p-1", pack_code: "drafting", pack_manual: true, agent_id: null, agent_name: null },
  };
  getCoverage.mockResolvedValue(coverageOf(named));

  await render(true);

  expect(byId("coverage-verdict-s-1")).not.toBeNull();
  expect(byId("coverage-quality-s-1")).not.toBeNull();
});

it("keeps both on a step set by hand to a blocked mode, where no agent can be named", async () => {
  getCoverage.mockResolvedValue(coverageOf({ ...STEP, mode_manual: true }));
  await render(true);
  // To do lists the step as "nobody does this"; the row says the same.
  expect(byId("coverage-verdict-s-1")!.getAttribute("data-verdict")).toBe("gap");
  expect(byId("coverage-quality-s-1")).not.toBeNull();
});

it("keeps the verdict of a hand-set step a person is assigned to", async () => {
  getCoverage.mockResolvedValue(
    coverageOf({
      ...STEP,
      mode: "automatable",
      mode_manual: true,
      verdict: "human",
      gap_label: null,
      human: { employee_id: "e-1", name: "Ada", position: null, label: "assigned", missing_codes: [] },
    }),
  );
  await render(true);
  expect(byId("coverage-verdict-s-1")!.getAttribute("data-verdict")).toBe("human");
});

it("keeps both on a step whose mode nobody touched", async () => {
  getCoverage.mockResolvedValue(coverageOf(STEP));

  await render(true);

  expect(byId("coverage-verdict-s-1")!.getAttribute("data-verdict")).toBe("gap");
  expect(byId("coverage-quality-s-1")).not.toBeNull();
});

it("offers to choose an agent where no single pack matched", async () => {
  getCoverage.mockResolvedValue(coverageOf({ ...STEP, mode: "draft_then_review" }));

  await render(true);

  expect(byId("coverage-btn-change-pack-s-1")!.textContent).toBe(enMessages.coverage.setAgent);
  expect(byId("coverage-manual-mode-s-1")).toBeNull();
});

it("offers no agent type in a blocked mode, where coverage would ignore it", async () => {
  getCoverage.mockResolvedValue(coverageOf(STEP));

  await render(true);

  expect(byId("coverage-btn-change-mode-s-1")).not.toBeNull();
  expect(byId("coverage-btn-change-pack-s-1")).toBeNull();
});

it("shows a reader the value and the chip, never the controls", async () => {
  getCoverage.mockResolvedValue(coverageOf({ ...STEP, mode_manual: true }));

  await render(false);

  expect(byId("coverage-mode-s-1")).not.toBeNull();
  expect(byId("coverage-manual-mode-s-1")).not.toBeNull();
  expect(byId("coverage-btn-change-mode-s-1")).toBeNull();
  expect(byId("coverage-btn-change-pack-s-1")).toBeNull();
});

it("offers nothing on a step out of scope", async () => {
  getCoverage.mockResolvedValue(
    coverageOf({ ...STEP, in_scope: false, verdict: "out_of_scope", mode: "blocked_physical", gap_label: null }),
  );

  await render(true);

  expect(byId("coverage-mode-s-1")).not.toBeNull();
  expect(byId("coverage-btn-change-mode-s-1")).toBeNull();
  expect(byId("coverage-btn-change-pack-s-1")).toBeNull();
});

it("saves a picked mode, updates the steps tab and re-reads the coverage", async () => {
  getCoverage.mockResolvedValue(coverageOf(STEP));
  updateStep.mockResolvedValue({ id: "s-1", manual_mode: "automatable" });

  await render(true);
  await click("coverage-btn-change-mode-s-1");
  await click("coverage-btn-change-mode-s-1-option-automatable");

  expect(updateStep).toHaveBeenCalledWith("s-1", { manual_mode: "automatable" });
  expect(onStepsChanged).toHaveBeenCalledTimes(1);
  expect(getCoverage).toHaveBeenCalledTimes(2);
});

it("returns the computed value with a null", async () => {
  getCoverage.mockResolvedValue(coverageOf({ ...STEP, mode_manual: true }));
  updateStep.mockResolvedValue({ id: "s-1", manual_mode: null });

  await render(true);
  await click("coverage-btn-change-mode-s-1");
  await click("coverage-btn-change-mode-s-1-reset");

  expect(updateStep).toHaveBeenCalledWith("s-1", { manual_mode: null });
});

it("loads the packs on the first open and saves the picked one", async () => {
  getCoverage.mockResolvedValue(coverageOf({ ...STEP, mode: "draft_then_review" }));
  listPacks.mockResolvedValue([
    { id: "p-1", code: "drafting" },
    { id: "p-2", code: "own_pack_not_in_the_catalog" },
  ]);
  updateStep.mockResolvedValue({ id: "s-1", manual_pack_code: "drafting" });

  await render(true);
  await click("coverage-btn-change-pack-s-1");

  expect(listPacks).toHaveBeenCalledTimes(1);
  // A pack of the tenant's own reads as its code, never as a message path.
  const own = byId("coverage-btn-change-pack-s-1-option-own_pack_not_in_the_catalog")!;
  expect(own.textContent).toBe("own_pack_not_in_the_catalog");

  await click("coverage-btn-change-pack-s-1-option-drafting");
  expect(updateStep).toHaveBeenCalledWith("s-1", { manual_pack_code: "drafting" });
});

it("says so when the packs cannot be loaded, and asks again on the next open", async () => {
  getCoverage.mockResolvedValue(coverageOf({ ...STEP, mode: "draft_then_review" }));
  listPacks.mockRejectedValue(new Error("boom"));

  await render(true);
  await click("coverage-btn-change-pack-s-1");

  expect(toastError).toHaveBeenCalledWith(enMessages.common.loadFailed);
  // No empty list is cached, so the menu is not stuck on "Loading...".
  await click("coverage-btn-change-pack-s-1"); // closes it
  await click("coverage-btn-change-pack-s-1"); // opens it again
  expect(listPacks).toHaveBeenCalledTimes(2);
});

it("marks a named agent type set by hand next to an assigned person", async () => {
  getCoverage.mockResolvedValue(
    coverageOf({
      ...STEP,
      mode: "draft_then_review",
      verdict: "human",
      gap_label: null,
      agent: { pack_id: "p-1", pack_code: "drafting", pack_manual: true, agent_id: null, agent_name: null },
      human: { employee_id: "e-1", name: "Anna Weber", position: null, label: "assigned", missing_codes: [] },
    }),
  );

  await render(true);

  expect(byId("coverage-manual-pack-s-1")!.textContent).toBe(enMessages.coverage.manualChip);
});
