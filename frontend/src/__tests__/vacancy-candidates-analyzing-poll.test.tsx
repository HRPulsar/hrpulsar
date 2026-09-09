// @vitest-environment jsdom
//
// HRP-493 REDO — a row stuck on "Analyzing…".
//
// The AI VERDICT column shows a spinner while the run for that
// candidate-vacancy is in flight, but the table was fetched exactly
// once. When the run finished the verdict landed in the database and on
// the candidate card's AI Insights block, while this table went on
// showing the spinner until the recruiter pressed F5.
//
// So: poll while any row is still analysing, and stop as soon as none
// is. The flag itself is derived server-side from the AIAnalysisRun
// status — the same row AI Insights reads — so the two surfaces flip on
// one fact instead of two guesses.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import type { CandidateVacancyEnrichedRow } from "@/lib/recruitment-types";

let listResponses: CandidateVacancyEnrichedRow[][] = [];
let listCalls = 0;

vi.mock("@/lib/api", () => ({
  // Plain Error, not a subclass: a `class` expression inside a factory
  // returning a parenthesised object literal trips the TS parser here
  // (TS1359), and nothing in this suite exercises the 412 branch that
  // narrows on it.
  ApiError: Error,
  api: {
    get: vi.fn((url: string) => {
      if (url.includes("/candidates/enriched")) {
        const row = listResponses[Math.min(listCalls, listResponses.length - 1)];
        listCalls += 1;
        return Promise.resolve(row);
      }
      return Promise.resolve([]);
    }),
    patch: vi.fn(() => Promise.resolve({})),
    post: vi.fn(() => Promise.resolve({})),
    delete: vi.fn(() => Promise.resolve({})),
  },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

// jsdom's localStorage is unavailable under this vitest setup — same
// in-memory stub the sibling suites use. The table persists its sort
// there on mount.
const storage = new Map<string, string>();
vi.stubGlobal("localStorage", {
  getItem: (k: string) => storage.get(k) ?? null,
  setItem: (k: string, v: string) => void storage.set(k, String(v)),
  removeItem: (k: string) => void storage.delete(k),
  clear: () => storage.clear(),
});

const { VacancyCandidatesTable } = await import(
  "@/components/recruitment/vacancy-candidates-table"
);

function mkRow(
  overrides: Partial<CandidateVacancyEnrichedRow> = {},
): CandidateVacancyEnrichedRow {
  return {
    id: "cv-1",
    candidate_id: "cand-1",
    candidate_name: "Maria Ivanovna",
    last_position: "Systems analyst",
    experience_years: 20,
    stage_id: null,
    stage_name: null,
    stage_type: null,
    manager_score: null,
    ai_score: "0.52",
    ai_readiness: "resume_and_transcript",
    ai_verdict: "pending",
    ai_verdict_summary: null,
    ai_key_strength: null,
    ai_key_risk: null,
    ai_risk_mitigation: null,
    ai_analysis_in_progress: true,
    version: 1,
    added_at: "2026-07-14T09:00:00Z",
    ...overrides,
  } as CandidateVacancyEnrichedRow;
}

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.useFakeTimers();
  listCalls = 0;
  listResponses = [];
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.useRealTimers();
});

async function mount() {
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <VacancyCandidatesTable vacancyId="vac-1" reloadToken={0} />
      </NextIntlClientProvider>,
    );
  });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
}

async function tick(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

const verdictCell = () =>
  document.querySelector('[data-testid$="-ai-verdict-analyzing"]');

describe("Analyzing… row (HRP-493)", () => {
  it("re-reads the list while a run is in flight", async () => {
    listResponses = [[mkRow()]];
    await mount();
    expect(listCalls).toBe(1);
    expect(verdictCell()).not.toBeNull();

    await tick(5000);
    expect(listCalls).toBe(2);
    await tick(5000);
    expect(listCalls).toBe(3);
  });

  it("swaps the spinner for the verdict without a reload", async () => {
    listResponses = [
      [mkRow()],
      [
        mkRow({
          ai_analysis_in_progress: false,
          ai_verdict: "not_recommended",
        }),
      ],
    ];
    await mount();
    expect(verdictCell()).not.toBeNull();

    await tick(5000);
    expect(verdictCell()).toBeNull();
  });

  it("stops polling once no row is analysing", async () => {
    listResponses = [
      [mkRow()],
      [mkRow({ ai_analysis_in_progress: false, ai_verdict: "needs_check" })],
    ];
    await mount();
    await tick(5000);
    const settled = listCalls;

    await tick(30000);
    expect(listCalls).toBe(settled);
  });

  it("never starts polling when nothing is analysing", async () => {
    listResponses = [
      [mkRow({ ai_analysis_in_progress: false, ai_verdict: "recommended" })],
    ];
    await mount();
    await tick(30000);
    expect(listCalls).toBe(1);
  });

  it("skips ticks while the tab is hidden", async () => {
    listResponses = [[mkRow()]];
    await mount();
    const visibility = vi
      .spyOn(document, "visibilityState", "get")
      .mockReturnValue("hidden");
    await tick(15000);
    expect(listCalls).toBe(1);
    visibility.mockRestore();
  });
});
