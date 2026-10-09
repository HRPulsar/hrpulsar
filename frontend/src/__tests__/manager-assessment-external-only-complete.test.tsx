// @vitest-environment jsdom
//
// HRP-1022: a round only an external evaluator scored - nobody inside holds a
// sheet on it - still shows its progress row with Mark as complete: live once
// every Critical competence is scored by the submitted sheets, greyed out
// with the reason until then.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";

const ROUND = {
  id: "r-1",
  type: "final",
  round_number: null,
  status: "in_progress",
  completed_at: null,
  archived_at: null,
  evaluators: [],
  invites: [
    {
      id: "inv-1",
      email: "ext@example.com",
      evaluator_name: "Ext",
      status: "submitted",
      submitted_at: "2026-10-02T10:00:00Z",
      revoked_at: null,
      expires_at: "2099-01-01T00:00:00Z",
      allow_reediting: false,
      delivery_status: "sent",
      delivery_error: null,
      delivery_retry_count: 0,
    },
  ],
};

// What the submitted external sheet put into the round aggregate.
let scored: string[] = [];

vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {},
  api: {
    get: vi.fn((url: string) => {
      if (url.endsWith("/assessment-rounds")) return Promise.resolve([ROUND]);
      if (url.startsWith("/recruitment/vacancies/vac-1/profile"))
        return Promise.resolve({ profile_data: { competences: [] } });
      if (url === "/recruitment/vacancies/vac-1")
        return Promise.resolve({
          assessment_scale_snapshot: {
            levels: [{ value: 1, label: "Low" }, { value: 4, label: "High" }],
          },
        });
      // Nobody inside holds a sheet on the round.
      if (url.endsWith("/assessments")) return Promise.resolve([]);
      if (url.endsWith("/aggregate"))
        return Promise.resolve({
          average: scored.length ? 3 : null,
          average_weight: null,
          divergence_threshold: 1,
          competences: scored.map((id) => ({
            competence_id: id,
            average: 3,
            average_weight: null,
            diverges: false,
            scorers: [{ evaluator: "Ext", evaluator_type: "external", score: 3 }],
          })),
        });
      return Promise.reject(new Error(`not mocked: ${url}`));
    }),
    patch: vi.fn(() => Promise.resolve({})),
    post: vi.fn(() => Promise.resolve({})),
  },
}));

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ user: viewer }),
}));
const RECRUITER = { id: "u-rec", roles: ["recruiter"], sections: { recruitment: "manage" } };
let viewer = RECRUITER;

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

vi.mock("@/components/recruitment/evaluation-sheet-form", async (orig) => ({
  ...(await orig<object>()),
  toProfileCompetences: () =>
    Promise.resolve([
      { id: "c-crit", name: "Craft", criticality: "critical", indicators: [] },
      { id: "c-nice", name: "Style", criticality: "desirable", indicators: [] },
    ]),
  CompetenceScoreList: () => <div data-testid="score-list-stub" />,
}));

const { ManagerAssessmentSection } = await import(
  "@/components/recruitment/manager-assessment-section"
);

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
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
        <ManagerAssessmentSection
          vacancies={[{ id: "cv-1", vacancy_id: "vac-1", vacancy_title: "Engineer" }]}
          initialVacancyId="vac-1"
        />
      </NextIntlClientProvider>,
    );
  });
  for (let i = 0; i < 6; i++) {
    await act(async () => {
      await Promise.resolve();
    });
  }
}

const byId = (id: string) =>
  container.querySelector(`[data-testid="${id}"]`) as HTMLButtonElement | null;

describe("Mark as complete on a round only external evaluators scored (HRP-1022)", () => {
  it("is live once the submitted sheets cover every Critical competence", async () => {
    scored = ["c-crit"];
    await render();
    expect(byId("assessment-progress-counter")!.textContent).toContain("1");
    const btn = byId("assessment-round-complete-btn");
    expect(btn).not.toBeNull();
    expect(btn!.disabled).toBe(false);
    // No sheet of one's own - nothing to fill in.
    expect(byId("score-list-stub")).toBeNull();
  });

  it("shows no progress row to a viewer who neither evaluates nor runs rounds", async () => {
    // A hiring manager at view reads no aggregate, so the row would say 0/N.
    viewer = { id: "u-hm", roles: ["hiring_manager"], sections: { recruitment: "view" } };
    try {
      scored = ["c-crit"];
      await render();
      expect(byId("assessment-progress-counter")).toBeNull();
      expect(byId("assessment-round-complete-btn")).toBeNull();
    } finally {
      viewer = RECRUITER;
    }
  });

  it("is greyed out with the reason while a Critical competence is unscored", async () => {
    scored = ["c-nice"];
    await render();
    const btn = byId("assessment-round-complete-btn");
    expect(btn!.disabled).toBe(true);
    expect(btn!.parentElement!.getAttribute("title")).toContain("Craft");
  });
});

// HRP-379 REDO 02.10: the email's `#manager-assessments` jump keeps the block
// in place while the blocks above it are still loading, and hands the scroll
// back the moment the user touches the page.
describe("the submitted-assessment email's jump (HRP-379)", () => {
  it("re-aligns on layout changes until the user takes over", async () => {
    const scrolled = vi.fn();
    Element.prototype.scrollIntoView = scrolled;
    let onResize: (() => void) | null = null;
    const disconnect = vi.fn();
    vi.stubGlobal(
      "ResizeObserver",
      class {
        constructor(cb: () => void) {
          onResize = cb;
        }
        observe() {}
        disconnect = disconnect;
      },
    );
    window.location.hash = "#manager-assessments";
    try {
      scored = ["c-crit"];
      await render();
      expect(scrolled).toHaveBeenCalledWith({ block: "start" });
      const jumps = scrolled.mock.calls.length;
      // A block above finished loading and pushed this one down.
      act(() => onResize!());
      expect(scrolled.mock.calls.length).toBe(jumps + 1);
      // The user scrolls: the follow ends for good.
      act(() => {
        window.dispatchEvent(new Event("wheel"));
      });
      expect(disconnect).toHaveBeenCalled();
    } finally {
      window.location.hash = "";
      vi.unstubAllGlobals();
    }
  });
});

