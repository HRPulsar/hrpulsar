// @vitest-environment jsdom
//
// HRP-471 — a question set is generated in the background. While the
// worker writes it the block shows progress and a Cancel, the tab bar no
// longer says "Generating…", and the other sets stay usable.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";

const questionSets: unknown[] = [];
const posted: string[] = [];

vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {},
  api: {
    get: vi.fn((url: string) => {
      if (url.includes("/question-sets")) return Promise.resolve(questionSets);
      if (url.includes("/profile")) return Promise.resolve({ profile_data: {} });
      return Promise.resolve([]);
    }),
    post: vi.fn((url: string) => {
      posted.push(url);
      return Promise.resolve({});
    }),
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
  toast: Object.assign(vi.fn(), {
    success: vi.fn(),
    error: vi.fn(),
    message: vi.fn(),
  }),
}));

// HRP-830: the generate, new-set and cancel buttons follow the recruitment
// matrix; the cases below are a caller who may evaluate candidates.
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ canEvaluateCandidates: true }),
}));

const { InterviewQuestionSets } = await import(
  "@/components/recruitment/interview-question-sets"
);

const VACANCY = {
  id: "vac-1",
  title: "Systems analyst",
  candidate_vacancy_id: "cv-1",
  has_parsed_resume: true,
};

function mkQuestion(id: string) {
  return {
    id,
    question_set_id: "set-ready",
    text: `Question ${id}`,
    goal: "verify_skill",
    priority: "should_ask",
    competence_id: null,
    resume_anchor_jsonb: null,
    expected_answer_indicators: [],
    follow_ups: [],
    rationale: null,
    source: "ai_generated",
    source_blind_spot_id: null,
    sort_order: 0,
    status: "active",
    covered_at: null,
    covered_by: null,
    covered_method: null,
    version: 1,
  };
}

function mkSet(overrides: Record<string, unknown> = {}) {
  return {
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
    ...overrides,
  };
}

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  questionSets.length = 0;
  posted.length = 0;
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
          vacancyOptions={[VACANCY]}
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
  container.querySelector<HTMLElement>(`[data-testid="${id}"]`);

describe("Interview questions — generation in progress (HRP-471)", () => {
  it("case 1: the first set keeps the empty state, disabled button and a Cancel", async () => {
    questionSets.push(mkSet({ status: "generating" }));
    await mount();

    expect(byTestId("recruitment-interview-questions-empty")).not.toBeNull();
    const generate = byTestId(
      "recruitment-interview-questions-generate-btn",
    ) as HTMLButtonElement;
    expect(generate.disabled).toBe(true);
    expect(generate.textContent).toContain("Generating…");
    expect(byTestId("recruitment-interview-questions-tabbar")).toBeNull();

    await act(async () => {
      byTestId("recruitment-interview-questions-cancel-btn")!.click();
    });
    expect(posted).toContain("/v1/question-sets/set-1/cancel");
  });

  it("case 2: a regenerating set shows progress on its tab and leaves the others usable", async () => {
    questionSets.push(
      mkSet({ id: "set-2", name: "Interview 2", status: "regenerating" }),
      mkSet({
        id: "set-ready",
        name: "Interview 1",
        questions: [mkQuestion("q-1")],
      }),
    );
    await mount();

    expect(byTestId("recruitment-interview-questions-progress")).not.toBeNull();
    expect(byTestId("recruitment-interview-questions-cancel-btn")).not.toBeNull();
    expect(byTestId("recruitment-interview-questions-regenerate-btn")).toBeNull();
    // The tab bar says "New set", never "Generating…".
    const newSet = byTestId(
      "recruitment-interview-questions-new-set-btn",
    ) as HTMLButtonElement;
    expect(newSet.textContent).not.toContain("Generating…");
    expect(newSet.disabled).toBe(true);

    await act(async () => {
      byTestId("recruitment-interview-questions-tab-set-ready")!.click();
    });
    expect(byTestId("recruitment-interview-questions-progress")).toBeNull();
    expect(container.textContent).toContain("Question q-1");
    expect(
      byTestId("recruitment-interview-questions-regenerate-btn"),
    ).not.toBeNull();
  });

  it("names a failed generation and offers Re-generate", async () => {
    questionSets.push(mkSet({ status: "failed" }));
    await mount();

    expect(byTestId("recruitment-interview-questions-failed")).not.toBeNull();
    expect(
      byTestId("recruitment-interview-questions-regenerate-btn"),
    ).not.toBeNull();
  });
});

describe("Interview questions — settling a set in flight (review 01.10)", () => {
  async function poll() {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
  }

  afterEach(() => {
    vi.useRealTimers();
  });

  it("a failed poll keeps the sets on screen and polling on", async () => {
    const { api } = await import("@/lib/api");
    questionSets.push(
      mkSet({ status: "regenerating", questions: [mkQuestion("q-1")] }),
    );
    // Only the poll's interval is faked: mount() waits on a real setTimeout.
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    await mount();
    vi.mocked(api.get).mockImplementationOnce(() =>
      Promise.reject(new Error("502")),
    );
    await poll();
    expect(byTestId("recruitment-interview-questions-progress")).not.toBeNull();
    expect(byTestId("recruitment-interview-questions-empty")).toBeNull();
    const calls = vi.mocked(api.get).mock.calls.length;
    await poll();
    expect(vi.mocked(api.get).mock.calls.length).toBeGreaterThan(calls);
  });

  it("a regeneration that lands back on its old questions is a failure", async () => {
    const { toast } = await import("sonner");
    questionSets.push(
      mkSet({ status: "regenerating", questions: [mkQuestion("q-1")] }),
    );
    // Only the poll's interval is faked: mount() waits on a real setTimeout.
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    await mount();
    questionSets[0] = mkSet({ status: "ready", questions: [mkQuestion("q-1")] });
    await poll();
    expect(toast.error).toHaveBeenCalled();
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("a regeneration with new questions is announced as ready", async () => {
    const { toast } = await import("sonner");
    vi.mocked(toast.success).mockClear();
    questionSets.push(
      mkSet({ status: "regenerating", questions: [mkQuestion("q-1")] }),
    );
    // Only the poll's interval is faked: mount() waits on a real setTimeout.
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    await mount();
    questionSets[0] = mkSet({ status: "ready", questions: [mkQuestion("q-2")] });
    await poll();
    expect(toast.success).toHaveBeenCalled();
  });
});
