// @vitest-environment jsdom
//
// HRP-442 REDO + HRP-740 — the Interview questions block, mounted.
//
// HRP-442: the "Interview questions ready" email links to
// `...?questionSet=<id>#interview-questions`. The right tab opened, but
// the page never moved: the page-level anchor jump runs when the
// candidate card lands, and at that moment this block is a one-line
// "Loading…" placeholder. The jump has to come from the block itself,
// once its own request has resolved.
//
// HRP-740: regeneration rewrites the set in place, so the "Generated
// <date>" line has to read the last generation, not the row's birthday.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";

const questionSets: unknown[] = [];

vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {},
  api: {
    get: vi.fn((url: string) => {
      if (url.includes("/question-sets")) return Promise.resolve(questionSets);
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
  toast: Object.assign(vi.fn(), {
    success: vi.fn(),
    error: vi.fn(),
    message: vi.fn(),
  }),
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
let scrolled: Element[];

beforeEach(() => {
  questionSets.length = 0;
  scrolled = [];
  // jsdom has no layout, so scrollIntoView is not implemented at all.
  Element.prototype.scrollIntoView = function scrollIntoView(this: Element) {
    scrolled.push(this);
  };
  window.location.hash = "";
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
  // The sets request resolves on the microtask queue; the effect that
  // reads its result runs on the commit after that.
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

const section = () =>
  document.querySelector<HTMLElement>(
    '[data-testid="recruitment-interview-questions-section"]',
  );

describe("Interview questions deep-link anchor (HRP-442)", () => {
  it("scrolls to the block once its sets have loaded", async () => {
    questionSets.push(mkSet());
    window.location.hash = "#interview-questions";
    await mount();
    expect(scrolled).toEqual([section()]);
  });

  it("scrolls only once, not on every reload of the list", async () => {
    questionSets.push(mkSet());
    window.location.hash = "#interview-questions";
    await mount();
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(scrolled).toHaveLength(1);
  });

  it("leaves the page alone when the URL carries no anchor", async () => {
    questionSets.push(mkSet());
    await mount();
    expect(scrolled).toEqual([]);
  });

  it("leaves the page alone for someone else's anchor", async () => {
    questionSets.push(mkSet());
    window.location.hash = "#ai-insights";
    await mount();
    expect(scrolled).toEqual([]);
  });
});

describe("Generated date after a re-generate (HRP-740)", () => {
  it("shows the date of the latest generation, not the first", async () => {
    questionSets.push(
      mkSet({
        generation_mode: "regenerated",
        created_at: "2026-07-14T09:00:00Z",
        updated_at: "2026-09-07T11:30:00Z",
      }),
    );
    await mount();
    const text = section()?.textContent ?? "";
    expect(text).toContain("Generated 2026-09-07");
    expect(text).not.toContain("2026-07-14");
  });

  it("still dates a first generation from its own run", async () => {
    questionSets.push(mkSet());
    await mount();
    expect(section()?.textContent ?? "").toContain("Generated 2026-07-14");
  });

  it("gives a hand-built set no generation line", async () => {
    questionSets.push(
      mkSet({ generation_mode: "manual", updated_at: "2026-09-07T11:30:00Z" }),
    );
    await mount();
    expect(section()?.textContent ?? "").not.toContain("Generated");
  });
});
