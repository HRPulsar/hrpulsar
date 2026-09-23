// @vitest-environment jsdom
//
// HRP-871: the "assessed" / "expected" chip opens what the match stands on -
// the person's competences behind the step's capabilities, the score of each
// and the passing score it was held against. An expected match says so in
// its own words and shows no score. There is nothing to open for an assigned
// executor, and nothing at all for a reader the person is hidden from: the
// coverage row then has no `human`.

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

type Human = NonNullable<CoverageStep["human"]>;

const HUMAN: Human = {
  employee_id: "e-1",
  name: "Jane Doe",
  position: "Controller",
  label: "assessed",
  missing_codes: [],
  passing_score: 60,
  grounds: [{ competence_id: "k-1", title: "Credit risk judgement", state: "assessed", percent: 82, codes: ["P6"] }],
};

const STEP: CoverageStep = {
  step_id: "s-1",
  position: 1,
  title: "Decide on the credit hold",
  state: "accepted",
  codes: ["P6"],
  required_codes: ["P6"],
  in_scope: true,
  mode: "blocked_judgment",
  quality: "no",
  verdict: "human",
  agent: null,
  human: HUMAN,
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
  const coverage: Coverage = {
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

async function open() {
  await act(async () => {
    byId("coverage-btn-grounds-s-1")!.click();
  });
}

it("shows the competence, its score and the passing score behind an assessed match", async () => {
  await render(STEP);
  expect(byId("coverage-grounds-drawer")).toBeNull();

  await open();

  expect(byId("coverage-grounds-drawer-title")!.textContent).toBe("Match details: Jane Doe");
  expect(byId("coverage-grounds-drawer-text")!.textContent).toBe(enMessages.coverage.groundsAssessedText);
  expect(byId("coverage-grounds-drawer-threshold")!.textContent).toBe("Passing score: 60%");
  const row = byId("coverage-grounds-row-k-1")!;
  expect(row.textContent).toContain("Credit risk judgement");
  expect(row.textContent).toContain("Covers: P6");
  expect(row.textContent).toContain("82%");
});

it("words an expected match on its own and shows no score", async () => {
  await render({
    ...STEP,
    human: {
      ...HUMAN,
      label: "expected",
      grounds: [{ ...HUMAN.grounds![0], state: "expected", percent: null }],
    },
  });

  await open();

  expect(byId("coverage-grounds-drawer")!.getAttribute("data-label")).toBe("expected");
  expect(byId("coverage-grounds-drawer-text")!.textContent).toBe(enMessages.coverage.groundsExpectedText);
  const row = byId("coverage-grounds-row-k-1")!;
  expect(row.textContent).toContain(enMessages.coverage.groundsNotAssessed);
  expect(row.textContent).not.toContain("%");
});

it("has nothing to open for an assigned executor", async () => {
  await render({ ...STEP, human: { ...HUMAN, label: "assigned", passing_score: null, grounds: [] } });

  expect(byId("coverage-executor-s-1")).not.toBeNull();
  expect(byId("coverage-btn-grounds-s-1")).toBeNull();
});

it("has nothing to open when the person is hidden from the reader", async () => {
  // redact_people drops the matched person; the verdict stays.
  await render({ ...STEP, human: null });

  expect(byId("coverage-verdict-s-1")!.getAttribute("data-verdict")).toBe("human");
  expect(byId("coverage-human-s-1")).toBeNull();
  expect(byId("coverage-btn-grounds-s-1")).toBeNull();
});

it("keeps a plain chip for a match that carries no grounds", async () => {
  await render({ ...STEP, human: { ...HUMAN, grounds: undefined } });

  expect(byId("coverage-human-s-1")!.textContent).toContain(enMessages.coverage.humanLabel_assessed);
  expect(byId("coverage-btn-grounds-s-1")).toBeNull();
});
