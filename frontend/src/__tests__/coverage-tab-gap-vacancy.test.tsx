// @vitest-environment jsdom
//
// HRP-801 REDO (QA 23.10): on the Coverage row of a gap, "Nobody on the team
// yet" stands alone - the Hire / Agency label after it is gone (a) - and a
// step already handed over says "Go to the vacancy": the talent-market card
// where "look inside first" put it (b), the Recruitment draft otherwise (c, d).

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import type { Coverage, CoverageStep } from "@/lib/api/work";

const getCoverage = vi.fn();
let sections = ["recruitment", "talent-market"];

vi.mock("@/lib/api/work", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/work")>()),
  workApi: { getCoverage },
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({
    canViewSection: (code: string) => sections.includes(code),
    canAdminister: false,
  }),
}));
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ user: null }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const { CoverageTab } = await import("@/components/coverage/coverage-tab");

const GAP: CoverageStep = {
  step_id: "s-1",
  position: 1,
  title: "Check the counterparty",
  state: "accepted",
  codes: ["P6"],
  required_codes: ["P6"],
  in_scope: true,
  mode: "review_required",
  quality: "no",
  verdict: "gap",
  agent: null,
  human: null,
  human_backup: false,
  accountable: null,
  needs_accountable: false,
  gap_label: "agency",
  hours_per_year: null,
  hire_need: { id: "n-1", vacancy_id: "v-1", label: "hire", talent_card_id: "tc-1" },
  skill_status: "none",
  tentative: false,
  review_human_share: null,
};

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  sections = ["recruitment", "talent-market"];
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
    hours: { total: 0, moves: 0, to_review: 0, stays: 1, unestimated: 1, to_review_after: 0, freed: 0, automated: 0 },
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
          canOpenHireNeed
          canRegisterAgent={false}
          onStepsChanged={() => {}}
        />
      </NextIntlClientProvider>,
    );
  });
}

const link = () =>
  container.querySelector<HTMLAnchorElement>('[data-testid="coverage-link-vacancy-s-1"]');

it("says nobody covers the step, without the label, and links to the card", async () => {
  await render(GAP);
  const row = container.querySelector('[data-testid="coverage-match-row-s-1"]')!;
  expect(row.textContent).toContain(enMessages.coverage.gapVerdictNobody);
  expect(row.textContent).not.toContain("Agency");
  expect(link()!.textContent).toBe(enMessages.coverage.goToVacancy);
  expect(link()!.getAttribute("href")).toBe("/talent-market/tc-1");
});

it("falls back to the Recruitment draft where the card is not the reader's", async () => {
  sections = ["recruitment"];
  await render(GAP);
  expect(link()!.getAttribute("href")).toBe("/recruitment/requisitions/v-1");

  sections = [];
  await render(GAP);
  expect(link()).toBeNull();
});

it("offers the hire window while nothing is handed over", async () => {
  await render({ ...GAP, hire_need: null });
  expect(link()).toBeNull();
  const open = container.querySelector('[data-testid="coverage-btn-hire-s-1"]')!;
  expect(open.textContent).toBe(enMessages.coverage.openHireNeedOne);
});
