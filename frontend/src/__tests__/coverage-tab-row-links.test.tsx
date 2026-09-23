// @vitest-environment jsdom
//
// HRP-864: what a coverage row lets the reader follow. The names of the
// executor, the matched person ("Backup: ...") and the accountable are links
// to the employee card - the card answers a reader who may not open it, so
// the row checks nothing. A step title in a summary bucket scrolls to the
// step's row. An agent type opens what an agent of that type does; a pack the
// catalog does not describe stays plain text.

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
  codes: ["P1"],
  required_codes: ["P1"],
  in_scope: true,
  mode: "automatable",
  quality: "strong",
  verdict: "agent",
  agent: { pack_id: "p-1", pack_code: "extraction", agent_id: null, agent_name: null },
  human: { employee_id: "e-1", name: "Jane Doe", position: "Controller", label: "assessed", missing_codes: [] },
  human_backup: true,
  accountable: { employee_id: "e-2", name: "John Roe", position: null },
  needs_accountable: false,
  gap_label: null,
  hours_per_year: null,
  hire_need: null,
  skill_status: "none",
  tentative: false,
  review_human_share: null,
};

function coverageOf(...steps: CoverageStep[]): Coverage {
  return {
    container_id: "c-1",
    status: "active",
    mapping_pending: false,
    candidate_step_ids: [],
    shares: null,
    hours: { total: 0, moves: 0, to_review: 0, stays: 0, unestimated: steps.length , to_review_after: 0, freed: 0, automated: 0 },
    quality: { no: 0, draft: 0, strong: steps.length, better_than_human: 0 },
    hourly_rate: null,
    hourly_rate_currency: null,
    money: null,
    review_human_share_default: 50,
    steps,
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
  vi.restoreAllMocks();
});

async function render(coverage: Coverage) {
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

it("links the matched person and the accountable to their cards, inside the sentence", async () => {
  await render(coverageOf(STEP));

  const human = byId("coverage-link-human-s-1")!;
  expect(human.getAttribute("href")).toBe("/employees/e-1");
  expect(human.textContent).toBe("Jane Doe");
  // The sentence keeps its words around the link.
  expect(byId("coverage-human-s-1")!.textContent).toContain("Backup: Jane Doe");

  const accountable = byId("coverage-link-accountable-s-1")!;
  expect(accountable.getAttribute("href")).toBe("/employees/e-2");
  expect(byId("coverage-accountable-s-1")!.textContent).toContain("Accountable: John Roe");
});

it("links an assigned executor, and names the agent type that could take the step", async () => {
  await render(
    coverageOf({
      ...STEP,
      verdict: "human",
      human_backup: false,
      human: { ...STEP.human!, label: "assigned" },
    }),
  );

  expect(byId("coverage-link-executor-s-1")!.getAttribute("href")).toBe("/employees/e-1");
  expect(byId("coverage-link-human-s-1")).toBeNull();
  // The pack inside "An agent type could take this: ..." is the same chip.
  expect(byId("coverage-agent-s-1")!.textContent).toBe("An agent type could take this: Extraction");
  expect(byId("coverage-pack-chip-s-1")).not.toBeNull();
});

it("leaves a person without an id as plain text", async () => {
  await render(
    coverageOf({
      ...STEP,
      human: { ...STEP.human!, employee_id: null as unknown as string },
    }),
  );

  expect(byId("coverage-link-human-s-1")).toBeNull();
  expect(byId("coverage-human-s-1")!.textContent).toContain("Backup: Jane Doe");
});

it("scrolls from a summary bucket to the step's row", async () => {
  const scrollIntoView = vi.fn();
  // jsdom does not implement it.
  Element.prototype.scrollIntoView = scrollIntoView;
  await render(coverageOf(STEP, { ...STEP, step_id: "s-2", position: 2, title: "File the return" }));

  await act(async () => {
    byId("coverage-summary-automatable-step-s-2")!.click();
  });

  expect(scrollIntoView).toHaveBeenCalledTimes(1);
  const row = byId("coverage-match-row-s-2")!;
  expect(scrollIntoView.mock.instances[0]).toBe(row);
  expect(document.activeElement).toBe(row);
});

it("says what an agent of the type does, from the catalog", async () => {
  await render(coverageOf(STEP));

  expect(byId("coverage-pack-chip-s-1-popover")).toBeNull();
  await act(async () => {
    byId("coverage-pack-chip-s-1")!.click();
  });

  expect(byId("coverage-pack-chip-s-1-popover")!.textContent).toContain(
    enMessages.reference.agentPack.extraction.description,
  );
});

it("keeps a pack the catalog does not describe as plain text", async () => {
  await render(coverageOf({ ...STEP, agent: { ...STEP.agent!, pack_code: "own_pack" } }));

  expect(byId("coverage-pack-chip-s-1")).toBeNull();
  const chip = byId("coverage-agent-s-1")!;
  expect(chip.textContent).toContain("own_pack");
  expect(chip.textContent).not.toContain("agentPack");
});
