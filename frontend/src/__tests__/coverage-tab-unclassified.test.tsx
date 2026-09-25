// @vitest-environment jsdom
//
// HRP-944: a step typed in with no capabilities and never classified is not a
// step that needs none. The row says so and points at the two ways to fix it,
// instead of the out-of-scope line about accountability.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import type { Coverage, CoverageStep } from "@/lib/api/work";

const getCoverage = vi.fn();

vi.mock("@/lib/api/work", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/work")>()),
  workApi: { getCoverage, updateStep: vi.fn(), listPacks: vi.fn() },
}));
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ user: null }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const { CoverageTab } = await import("@/components/coverage/coverage-tab");

const STEP: CoverageStep = {
  step_id: "s-1",
  position: 1,
  title: "Approve the budget",
  state: "tenant_edited",
  codes: [],
  required_codes: [],
  in_scope: false,
  mode: null,
  quality: null,
  verdict: "unclassified",
  agent: null,
  human: null,
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

function coverageOf(step: CoverageStep): Coverage {
  return {
    container_id: "c-1",
    status: "draft",
    mapping_pending: false,
    candidate_step_ids: [],
    shares: null,
    hours: { total: 0, moves: 0, to_review: 0, stays: 0, unestimated: 0, to_review_after: 0, freed: 0, automated: 0 },
    quality: { no: 0, draft: 0, strong: 0, better_than_human: 0 },
    hourly_rate: null,
    hourly_rate_currency: null,
    money: null,
    review_human_share_default: 50,
    steps: [step],
  };
}

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

async function render(canEdit: boolean) {
  getCoverage.mockResolvedValue(coverageOf(STEP));
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
          onStepsChanged={vi.fn()}
        />
      </NextIntlClientProvider>,
    );
  });
}

it("names an unclassified step and says how to classify it", async () => {
  await render(true);

  const badge = document.querySelector('[data-testid="coverage-verdict-s-1"]');
  expect(badge?.getAttribute("data-verdict")).toBe("unclassified");
  expect(badge?.textContent).toBe(enMessages.coverage.verdict_unclassified);
  expect(document.querySelector('[data-testid="coverage-unclassified-s-1"]')?.textContent).toBe(
    enMessages.coverage.unclassifiedHint,
  );
  expect(container.textContent).not.toContain(enMessages.coverage.outOfScopeAccountability);
});

it("tells a reader only what is missing, not what to do", async () => {
  // A reader - or anyone on an archived map - has no picker and no
  // Reclassify button, so the row must not send them looking for one.
  await render(false);
  expect(document.querySelector('[data-testid="coverage-unclassified-s-1"]')?.textContent).toBe(
    enMessages.coverage.unclassifiedReadOnly,
  );
  expect(container.textContent).not.toContain(enMessages.coverage.unclassifiedHint);
});
