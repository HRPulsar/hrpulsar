// @vitest-environment jsdom
//
// HRP-630 (QA 06.10, task 2): at `Recruitment x Hiring manager = view` the
// Interview questions block is read-only - no new set, no adding, no
// regenerating - and Export PDF stays. `manage` keeps every write.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";

let manages = false;

const SET = {
  id: "set-1",
  candidate_vacancy_id: "cv-1",
  round_id: null,
  assessment_round_id: null,
  set_type: "pre_interview",
  name: "Interview 1",
  status: "ready",
  generation_mode: "initial",
  source_round_ids: null,
  coverage_note: null,
  archived_at: null,
  version: 1,
  created_at: "2026-07-14T09:00:00Z",
  updated_at: "2026-07-14T09:00:00Z",
  questions: [],
};

vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {},
  api: {
    get: vi.fn((url: string) => {
      if (url.includes("consent/latest"))
        return Promise.resolve({ status: "signed", active: true });
      if (url.includes("/question-sets")) return Promise.resolve([SET]);
      if (url.includes("/profile")) return Promise.resolve({ profile_data: {} });
      return Promise.resolve([]);
    }),
    post: vi.fn(() => Promise.resolve({})),
    patch: vi.fn(() => Promise.resolve({})),
    delete: vi.fn(() => Promise.resolve({})),
  },
}));

vi.mock("@/hooks/use-cost-confirmation", () => ({
  useCreditGate: () => ({
    isSaas: false,
    cost: null,
    balance: null,
    insufficient: false,
    refresh: () => {},
  }),
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

// The hiring manager evaluates at any open level; `manage` is the switch.
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({
    canEvaluateCandidates: true,
    canManageSection: () => manages,
  }),
}));

const { InterviewQuestionSets } = await import(
  "@/components/recruitment/interview-question-sets"
);

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  Element.prototype.scrollIntoView = () => {};
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function mount() {
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <InterviewQuestionSets
          candidateId="cand-1"
          vacancyOptions={[
            { id: "vac-1", title: "Analyst", candidate_vacancy_id: "cv-1" },
          ]}
          initialVacancyId="vac-1"
        />
      </NextIntlClientProvider>,
    );
  });
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

const byTestId = (id: string) =>
  container.querySelector(`[data-testid="recruitment-interview-questions-${id}"]`);

const WRITES = ["new-set-btn", "add-btn", "add-menu-btn", "regenerate-btn"];

describe("Interview questions for a hiring manager at view (HRP-630)", () => {
  it("reads the set and exports it, and offers no write", async () => {
    manages = false;
    await mount();
    expect(byTestId("export-btn")).not.toBeNull();
    for (const id of WRITES) expect(byTestId(id), id).toBeNull();
  });

  it("keeps every write at manage", async () => {
    manages = true;
    await mount();
    expect(byTestId("export-btn")).not.toBeNull();
    for (const id of WRITES) expect(byTestId(id), id).not.toBeNull();
  });
});
