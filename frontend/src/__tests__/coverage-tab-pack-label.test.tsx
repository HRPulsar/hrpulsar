// @vitest-environment jsdom
//
// 2.0.0 review §3 — an agent pack the interface catalog does not know (a
// backend newer than the frontend, an enterprise-only pack) used to print
// the message path on the coverage row. It reads as its code now, the way
// an unknown capability does; the tab also says it is loading instead of
// rendering nothing.

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
  title: "Check the invoice",
  state: "accepted",
  codes: [],
  required_codes: [],
  in_scope: true,
  mode: "automatable",
  quality: "strong",
  verdict: "agent",
  agent: {
    pack_id: "p-1",
    pack_code: "packs_not_in_the_catalog",
    agent_id: null,
    agent_name: null,
  },
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

const COVERAGE: Coverage = {
  container_id: "c-1",
  status: "active",
  mapping_pending: false,
  candidate_step_ids: [],
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

async function render() {
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <CoverageTab
          containerId="c-1"
          steps={[]}
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

it("falls back to the pack code when the catalog has no label", async () => {
  getCoverage.mockResolvedValue(COVERAGE);

  await render();

  const row = document.querySelector('[data-testid="coverage-agent-s-1"]')!;
  expect(row.textContent).toContain("packs_not_in_the_catalog");
  expect(row.textContent).not.toContain("agentPack");
});

it("says it is loading instead of rendering nothing", async () => {
  getCoverage.mockReturnValue(new Promise(() => {}));

  await render();

  expect(container.textContent).toContain(enMessages.common.loading);
});
