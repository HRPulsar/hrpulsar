// @vitest-environment jsdom
//
// The hours arithmetic of the Coverage feedback wave (HRP-858) on screen.
//
// HRP-861 — a step that moves to review used to count its full hours, so a
// process with 124 of its 131 yearly hours in review "freed" 3. The summary
// now reads before → after, and the hours editor carries one number per
// reviewed step: the percent of its hours the checker keeps.
//
// HRP-860 — one bar of three hour shares with a legend that repeats it,
// instead of an hours bar over a step-count quality row.
//
// HRP-862 — the hours an agent of the company already does: a line on the
// process, and a percent in the list that the list itself never computes.
//
// HRP-868 — a step may name its own hourly rate, so the money is the
// backend's sum over the steps and the screen only formats it.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import type { Coverage, CoverageStep, WorkContainer, WorkStep } from "@/lib/api/work";

const getCoverage = vi.fn();
const listContainers = vi.fn();
const updateStep = vi.fn();
const toastError = vi.fn();

vi.mock("@/lib/api/work", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/work")>()),
  workApi: { getCoverage, listContainers, updateStep },
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ canCreateCoverage: false }),
}));
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ user: null }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: toastError } }));

const { CoverageTab } = await import("@/components/coverage/coverage-tab");
const { parseShare, rateOutOfRange, shareOutOfRange } = await import(
  "@/components/coverage/hours-fields"
);
const { default: CoveragePage } = await import("@/app/(dashboard)/coverage/page");

function row(id: string, overrides: Partial<CoverageStep>): CoverageStep {
  return {
    step_id: id,
    position: 1,
    title: `Step ${id}`,
    state: "accepted",
    codes: [],
    required_codes: [],
    in_scope: true,
    mode: "draft_then_review",
    quality: "draft",
    verdict: "human",
    agent: null,
    human: null,
    human_backup: false,
    accountable: null,
    needs_accountable: false,
    gap_label: null,
    hours_per_year: 10,
    hire_need: null,
    skill_status: "none",
    tentative: false,
    review_human_share: 50,
    ...overrides,
  };
}

function step(id: string, overrides: Partial<WorkStep> = {}): WorkStep {
  return {
    id,
    container_id: "c-1",
    position: 1,
    title: `Step ${id}`,
    description: null,
    responsibility: "none",
    reversibility: null,
    hours_per_run: 10,
    runs_per_year: 1,
    output_type: "draft",
    state: "accepted",
    gap_label: null,
    notes: null,
    executor_employee_id: null,
    accountable_employee_id: null,
    review_human_share: null,
    manual_mode: null,
    manual_pack_code: null,
    hourly_rate: null,
    primitive_codes: [],
    capabilities: [],
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

// The process of the feedback thread.
const COVERAGE: Coverage = {
  container_id: "c-1",
  status: "active",
  mapping_pending: false,
  candidate_step_ids: ["default", "own", "agent"],
  shares: { moves: 2.3, to_review: 94.7, stays: 3 },
  hours: {
    total: 131,
    moves: 3,
    to_review: 124,
    stays: 4,
    unestimated: 0,
    to_review_after: 62,
    freed: 65,
    automated: 3,
  },
  quality: { no: 1, draft: 2, strong: 1, better_than_human: 0 },
  hourly_rate: null,
  hourly_rate_currency: null,
  money: null,
  review_human_share_default: 50,
  steps: [
    row("default", {}),
    row("own", { review_human_share: 30 }),
    row("agent", { mode: "automatable", review_human_share: null }),
  ],
};

const STEPS = [step("default"), step("own", { review_human_share: 30 }), step("agent")];

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  getCoverage.mockReset().mockResolvedValue(COVERAGE);
  updateStep.mockReset().mockImplementation(async (id: string, patch: Partial<WorkStep>) => ({
    ...STEPS.find((s) => s.id === id)!,
    ...patch,
  }));
  toastError.mockReset();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function render(steps: WorkStep[] = STEPS) {
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <CoverageTab
          containerId="c-1"
          steps={steps}
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

const byTestId = (id: string) => document.querySelector(`[data-testid="${id}"]`) as HTMLElement;
const shareInput = (stepId: string) =>
  byTestId(`coverage-weights-step-${stepId}-input-review-share`) as HTMLInputElement | null;

async function type(el: HTMLInputElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function click(el: HTMLElement) {
  await act(async () => {
    el.click();
  });
}

describe("the summary", () => {
  it("frees the agent bucket plus what review gives back", async () => {
    await render();

    expect(byTestId("coverage-roi-freed").dataset.hours).toBe("65");
    const review = byTestId("coverage-roi-to-review");
    expect(review.dataset.hours).toBe("124");
    expect(review.dataset.hoursAfter).toBe("62");
    expect(review.textContent).toContain("124 h → ≈ 62 h/year");
  });

  it("says how much of the total an agent already does", async () => {
    await render();

    const automated = byTestId("coverage-roi-automated");
    expect(automated.dataset.hours).toBe("3");
    expect(automated.textContent).toBe("Agents already do 3 of 131 h/year of this work.");
  });

  it("shows no automated line while no step carries an estimate", async () => {
    getCoverage.mockResolvedValue({
      ...COVERAGE,
      shares: null,
      hours: { ...COVERAGE.hours, total: 0, automated: 0 },
    });
    await render();

    expect(byTestId("coverage-roi-automated")).toBeNull();
  });

  // HRP-860: the bar was hours and the legend under it counted steps in four
  // other colours, so "21% a person does this" had no segment to point at.
  it("draws one scale: the legend repeats the bar, colour and percent", async () => {
    await render();

    const colorOf = (el: Element) => [...el.classList].find((c) => c.startsWith("bg-"));
    for (const [bucket, percent] of [
      ["moves", "2%"],
      ["to_review", "95%"],
      ["stays", "3%"],
    ]) {
      const legend = byTestId(`coverage-share-${bucket}`);
      const segment = byTestId(`coverage-bar-${bucket}`);
      expect(legend.textContent).toContain(percent);
      expect(segment.title).toContain(percent);
      expect(colorOf(legend.querySelector("span")!)).toBe(colorOf(segment));
    }
    expect(document.querySelector('[data-testid="coverage-quality-no"]')).toBeNull();
    expect(document.body.textContent).not.toContain("How well an agent does this work");
  });

  it("rounds the three percents so that they add up to a hundred", async () => {
    getCoverage.mockResolvedValue({
      ...COVERAGE,
      shares: { moves: 100 / 3, to_review: 100 / 3, stays: 100 / 3 },
    });
    await render();

    const printed = ["moves", "to_review", "stays"].map((b) =>
      Number(byTestId(`coverage-share-${b}`).textContent!.match(/(\d+)%/)![1]),
    );
    expect(printed.reduce((a, b) => a + b, 0)).toBe(100);
    // The exact share stays on the element, whatever the printed one rounds to.
    expect(byTestId("coverage-share-moves").dataset.share).toBe(String(100 / 3));
  });

  it("keeps an empty bucket in the legend and out of the bar", async () => {
    getCoverage.mockResolvedValue({
      ...COVERAGE,
      shares: { moves: 40, to_review: 60, stays: 0 },
    });
    await render();

    expect(byTestId("coverage-share-stays").textContent).toContain("0%");
    expect(byTestId("coverage-bar-stays")).toBeNull();
    expect(byTestId("coverage-bar-moves")).not.toBeNull();
  });
});

describe("the money", () => {
  // Deliberately not 131 h x 50: the step rates are the backend's business.
  const PRICED: Coverage = {
    ...COVERAGE,
    hourly_rate: 50,
    hourly_rate_currency: "EUR",
    money: {
      total: 9000,
      moves: 600,
      to_review: 7000,
      to_review_after: 3000,
      stays: 1400,
      freed: 4600,
      unpriced: 0,
    },
  };

  it("shows the sums of the backend and multiplies nothing itself", async () => {
    getCoverage.mockResolvedValue(PRICED);
    await render();

    expect(byTestId("coverage-roi-total").textContent).toContain("≈ 9,000 EUR/year");
    expect(byTestId("coverage-roi-freed").textContent).toContain("≈ 4,600 EUR/year");
    expect(byTestId("coverage-roi-to-review").textContent).toContain(
      "7,000 → ≈ 3,000 EUR/year",
    );
    // 131 h x 50 EUR - what the screen used to compute.
    expect(document.body.textContent).not.toContain("6,550");
    expect(byTestId("coverage-roi-unpriced")).toBeNull();
  });

  it("shows hours only while no step is priced, whatever the company rate", async () => {
    getCoverage.mockResolvedValue({ ...PRICED, money: null });
    await render();

    expect(byTestId("coverage-roi-total").textContent).not.toContain("EUR");
    expect(byTestId("coverage-roi-freed").dataset.hours).toBe("65");
  });

  it("asks for the company rate instead of an amount with no currency", async () => {
    // A step may carry a rate while the company has none, and the currency is
    // always the company's: there is nothing to print the sums in.
    getCoverage.mockResolvedValue({
      ...PRICED,
      hourly_rate: null,
      hourly_rate_currency: null,
    });
    await render();

    expect(byTestId("coverage-roi-total").textContent).not.toContain("9,000");
    expect(byTestId("coverage-roi-freed").dataset.hours).toBe("65");
    expect(byTestId("coverage-roi-unpriced")).toBeNull();
    expect(byTestId("coverage-roi-rate").textContent).toContain("No hourly rate, so no money here");
    // HRP-859: "set one" is the link, the sentence around it is not.
    expect(byTestId("coverage-roi-rate").querySelector("a")?.textContent).toBe("set one");
  });

  it("drops the no-rate line once a step's own rate puts money on the card", async () => {
    // HRP-858: the company rate is gone but its currency is not, so the
    // steps that carry their own rate still add up - "no hourly rate, so
    // no money here" would be arguing with the figures above it.
    getCoverage.mockResolvedValue({ ...PRICED, hourly_rate: null });
    await render();

    expect(byTestId("coverage-roi-total").textContent).toContain("EUR");
    expect(byTestId("coverage-roi-rate")).toBeNull();
  });

  it("says so when the money does not cover every estimated step", async () => {
    getCoverage.mockResolvedValue({
      ...PRICED,
      hourly_rate: null,
      money: { ...PRICED.money!, unpriced: 2 },
    });
    await render();

    expect(byTestId("coverage-roi-unpriced").textContent).toContain(
      "2 steps have no hourly rate",
    );
  });
});

describe("the hours editor", () => {
  it("offers a share on the reviewed steps only, prefilled with the effective one", async () => {
    await render();
    await click(byTestId("coverage-btn-weights"));

    expect(shareInput("default")!.value).toBe("50");
    expect(shareInput("own")!.value).toBe("30");
    expect(shareInput("agent")).toBeNull();
    // The default comes off the payload and reaches the hint whole.
    expect(byTestId("coverage-weights-review-share-hint").textContent).toContain("50%");
  });

  it("does not pin the default nobody touched", async () => {
    await render();
    await click(byTestId("coverage-btn-weights"));
    await click(byTestId("coverage-btn-weights-save"));

    expect(updateStep).not.toHaveBeenCalled();
  });

  it("sends the share that was typed, and null for the one that was cleared", async () => {
    await render();
    await click(byTestId("coverage-btn-weights"));
    await type(shareInput("default")!, "20");
    await type(shareInput("own")!, "");
    await click(byTestId("coverage-btn-weights-save"));

    expect(updateStep.mock.calls).toEqual([
      ["default", { review_human_share: 20 }],
      ["own", { review_human_share: null }],
    ]);
  });

  it("refuses a share the backend would refuse, and sends nothing", async () => {
    await render();
    await click(byTestId("coverage-btn-weights"));
    await type(shareInput("default")!, "12.5");
    await click(byTestId("coverage-btn-weights-save"));

    expect(updateStep).not.toHaveBeenCalled();
    expect(toastError).toHaveBeenCalledWith(enMessages.coverage.reviewShareRangeError);
  });
});

describe("the step rate in the hours editor", () => {
  const rateInput = (stepId: string) =>
    byTestId(`coverage-weights-step-${stepId}-input-rate`) as HTMLInputElement;
  const PRICED: Coverage = { ...COVERAGE, hourly_rate: 50, hourly_rate_currency: "EUR" };

  it("falls back to the company rate, shown as the placeholder", async () => {
    getCoverage.mockResolvedValue(PRICED);
    await render();
    await click(byTestId("coverage-btn-weights"));

    expect(rateInput("default").value).toBe("");
    expect(rateInput("default").placeholder).toBe("50");
    expect(rateInput("default").disabled).toBe(false);
    expect(rateInput("default").closest("label")!.textContent).toBe("Hourly rate, EUR");
    expect(byTestId("coverage-weights-rate-locked")).toBeNull();
    // Said in words too: a grey "50" reads like a typed "50" at a glance.
    expect(byTestId("coverage-weights-rate-hint").textContent).toContain("50 EUR/h");
  });

  it("takes a rate on a step no agent will ever take", async () => {
    // The editor lists every step in scope, not only the candidates: a step
    // a person keeps by its mode still has hours and a rate. A boundary step
    // is outside the arithmetic and stays out of the editor.
    getCoverage.mockResolvedValue({
      ...PRICED,
      steps: [
        ...COVERAGE.steps,
        row("blocked", { mode: "blocked_judgment", review_human_share: null }),
        row("boundary", { in_scope: false, review_human_share: null }),
      ],
    });
    await render([...STEPS, step("blocked"), step("boundary")]);
    await click(byTestId("coverage-btn-weights"));

    expect(byTestId("coverage-weights-step-blocked")).not.toBeNull();
    expect(byTestId("coverage-weights-step-boundary")).toBeNull();
    // Hours and a rate, but no review share: it is in no review bucket.
    expect(shareInput("blocked")).toBeNull();
    await type(rateInput("blocked"), "90");
    await click(byTestId("coverage-btn-weights-save"));

    expect(updateStep.mock.calls).toEqual([["blocked", { hourly_rate: 90 }]]);
  });

  it("sends the rate that was typed, and nothing for the steps left alone", async () => {
    getCoverage.mockResolvedValue(PRICED);
    await render();
    await click(byTestId("coverage-btn-weights"));
    await type(rateInput("agent"), "120");
    await click(byTestId("coverage-btn-weights-save"));

    expect(updateStep.mock.calls).toEqual([["agent", { hourly_rate: 120 }]]);
  });

  it("refuses a rate the backend would refuse", async () => {
    getCoverage.mockResolvedValue(PRICED);
    await render();
    await click(byTestId("coverage-btn-weights"));
    await type(rateInput("agent"), "0");
    await click(byTestId("coverage-btn-weights-save"));

    expect(updateStep).not.toHaveBeenCalled();
    expect(toastError).toHaveBeenCalledTimes(1);
  });

  it("asks for the company rate first, and links to where it is set", async () => {
    await render(); // COVERAGE: no company rate
    await click(byTestId("coverage-btn-weights"));

    expect(rateInput("default").disabled).toBe(true);
    expect(rateInput("default").closest("label")!.textContent).toBe("Hourly rate");
    const hint = byTestId("coverage-weights-rate-locked");
    expect(byTestId("coverage-weights-rate-hint")).toBeNull();
    expect(hint.textContent).toContain("Set the company hourly rate first");
    expect(hint.querySelector("a")!.getAttribute("href")).toBe("/company/profile");
  });

  it("keeps a rate the step already carries removable without a company rate", async () => {
    // Set while the company had a rate, which was cleared since: locking the
    // field now would leave a value nobody can take off.
    await render([step("default"), step("own", { hourly_rate: 80 }), step("agent")]);
    await click(byTestId("coverage-btn-weights"));

    expect(rateInput("default").disabled).toBe(true);
    expect(rateInput("own").disabled).toBe(false);
    expect(rateInput("own").value).toBe("80");
    await type(rateInput("own"), "");
    await click(byTestId("coverage-btn-weights-save"));

    expect(updateStep.mock.calls).toEqual([["own", { hourly_rate: null }]]);
  });
});

describe("rateOutOfRange", () => {
  it("takes empty as the company rate and keeps the backend's bounds", () => {
    expect(["", "0.01", "50", "99999999"].some(rateOutOfRange)).toBe(false);
    // Below a cent the backend's Numeric(10, 2) would keep 0.00.
    expect(["0", "0.004", "-5", "100000000", "abc"].every(rateOutOfRange)).toBe(true);
  });
});

describe("parseShare", () => {
  it("reads empty as not set and keeps the bounds the backend has", () => {
    expect(parseShare("")).toBeNull();
    expect(parseShare("0")).toBe(0);
    expect(["0", "100", ""].some(shareOutOfRange)).toBe(false);
    expect(["-1", "101", "12.5", "abc"].every(shareOutOfRange)).toBe(true);
  });
});

describe("the list", () => {
  const listed = (id: string, summary: WorkContainer["coverage_summary"]): WorkContainer => ({
    id,
    tenant_id: "t-1",
    type: "process",
    title: `Process ${id}`,
    description: null,
    goal: null,
    status: "active",
    owner_id: null,
    created_by_id: null,
    source: "manual",
    catalog_version: "v1.1",
    gap_default_label: "hire",
    visibility: "company",
    my_access: "read",
    coverage_summary: summary,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  });

  it("shows the stored percent and a dash where there is none", async () => {
    listContainers.mockResolvedValue({
      items: [
        listed("done", { hours: COVERAGE.hours, shares: null, automated_share: 38.46 }),
        listed("no-hours", { hours: COVERAGE.hours, shares: null, automated_share: null }),
        listed("never-opened", null),
      ],
      total: 3,
    });
    await act(async () => {
      root.render(
        <NextIntlClientProvider locale="en" messages={enMessages}>
          <CoveragePage />
        </NextIntlClientProvider>,
      );
    });

    expect(byTestId("coverage-row-done-automated").textContent).toBe("38%");
    expect(byTestId("coverage-row-done-automated").dataset.share).toBe("38.46");
    expect(byTestId("coverage-row-no-hours-automated").textContent).toBe("—");
    expect(byTestId("coverage-row-never-opened-automated").textContent).toBe("—");
    // The list asks for the list, and for no coverage of any container.
    expect(getCoverage).not.toHaveBeenCalled();
  });
});
