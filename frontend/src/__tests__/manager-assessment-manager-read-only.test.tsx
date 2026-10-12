// @vitest-environment jsdom
//
// HRP-629: below `manage` on recruitment, the manager reads the Manager
// assessments block and fills in only their own sheet - the one they hold
// as an internal evaluator on a round. Creating, closing and staffing rounds
// and inviting outside evaluators is `manage`, whatever the role's name.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import { api } from "@/lib/api";

const ME = "u-manager";
// One object per render config: the block keys its sheet fetch on `user`.
let user = { id: ME, roles: [] as string[], sections: {} as Record<string, string> };

const round = (id: string, type: string, evaluators: string[]) => ({
  id,
  type,
  round_number: type === "interview" ? 1 : null,
  status: "in_progress",
  completed_at: null,
  archived_at: null,
  invites: [
    {
      id: `inv-${id}`,
      email: "ext@example.com",
      evaluator_name: "Ext",
      status: "pending",
      submitted_at: null,
      revoked_at: null,
      expires_at: "2099-01-01T00:00:00Z",
      allow_reediting: false,
      delivery_status: "sent",
      delivery_error: null,
      delivery_retry_count: 0,
    },
  ],
  evaluators: evaluators.map((user_id) => ({
    user_id,
    full_name: user_id,
    initials: "XX",
    submitted: false,
  })),
});

// The manager is an evaluator on the interview round only.
const MINE = round("r-mine", "interview", [ME, "u-recruiter"]);
const OTHER = round("r-other", "final", ["u-recruiter"]);

const sheet = (roundId: string, evaluator: string) => ({
  id: `sheet-${roundId}-${evaluator}`,
  round_id: roundId,
  evaluator_type: "user",
  evaluator_user_id: evaluator,
  evaluator_invite_id: null,
  evaluator_display_name: null,
  status: "draft",
  final_notes: null,
  competence_scores: [],
  indicator_scores: [],
});

vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {},
  api: {
    get: vi.fn((url: string) => {
      if (url.endsWith("/assessment-rounds"))
        return Promise.resolve([MINE, OTHER]);
      if (url.startsWith("/recruitment/vacancies/vac-1/profile"))
        return Promise.resolve({ profile_data: { competences: [] } });
      if (url === "/recruitment/vacancies/vac-1")
        return Promise.resolve({
          assessment_scale_snapshot: {
            levels: [{ value: 1, label: "Low" }, { value: 5, label: "High" }],
          },
        });
      const sheets = url.match(/^\/v1\/assessment-rounds\/(.+)\/assessments$/);
      if (sheets) {
        const id = sheets[1];
        const owners = id === MINE.id ? [ME, "u-recruiter"] : ["u-recruiter"];
        return Promise.resolve(owners.map((o) => sheet(id, o)));
      }
      if (url.endsWith("/aggregate"))
        return Promise.resolve({
          average: null,
          average_weight: null,
          divergence_threshold: 1,
          competences: [],
        });
      return Promise.reject(new Error(`not mocked: ${url}`));
    }),
    patch: vi.fn(() => Promise.resolve({})),
    post: vi.fn(() => Promise.resolve({})),
  },
}));

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ user }),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

// The score list stands in for the sheet: one button scores the single
// competence, and it is live only when the sheet takes input.
vi.mock("@/components/recruitment/evaluation-sheet-form", async (orig) => ({
  ...(await orig<object>()),
  toProfileCompetences: () =>
    Promise.resolve([
      { id: "c-1", name: "Craft", criticality: "desirable", indicators: [] },
    ]),
  CompetenceScoreList: ({
    disabled,
    onCompetenceScore,
  }: {
    disabled: boolean;
    onCompetenceScore: (id: string, value: number) => void;
  }) => (
    <button
      data-testid="score-stub"
      disabled={disabled}
      onClick={() => onCompetenceScore("c-1", 4)}
    />
  ),
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
  vi.mocked(api.patch).mockClear();
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.useRealTimers();
});

const flush = async () => {
  for (let i = 0; i < 6; i++) {
    await act(async () => {
      await Promise.resolve();
    });
  }
};

async function render(withRoles: string[], recruitment: string) {
  user = { id: ME, roles: withRoles, sections: { recruitment } };
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
  await flush();
}

const byId = (id: string) =>
  container.querySelector(`[data-testid="${id}"]`) as HTMLButtonElement | null;
const anyById = (prefix: string) =>
  container.querySelector(`[data-testid^="${prefix}"]`);

async function openTab(id: string) {
  await act(async () => byId(`assessment-round-tab-${id}`)!.click());
  await flush();
}

// What QA listed (HRP-629, 02.10): round kebabs, + New round, + Add
// evaluator, Mark as complete, Invite external evaluator - and the rest of
// the round's writes with them.
const WRITES = [
  "assessment-round-kebab-",
  "assessment-round-new-btn",
  "assessment-round-add-",
  "assessment-add-evaluator-btn",
  "assessment-round-complete-btn",
  "invite-evaluator-modal-open",
  "assessment-round-invite-inv-r-mine-kebab",
];

describe("Manager assessments for a manager below manage (HRP-629)", () => {
  it("offers none of the round's writes on any tab", async () => {
    await render(["manager"], "view");
    for (const tab of [MINE.id, OTHER.id]) {
      await openTab(tab);
      for (const id of WRITES) expect(anyById(id), `${tab}: ${id}`).toBeNull();
      // No "start scoring" either: putting oneself on a round is staffing it.
      expect(container.textContent).not.toContain("Start scoring");
    }
  });

  it("lets them fill in their own sheet on the round they evaluate", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    await render(["manager"], "view");
    await openTab(MINE.id);
    const score = byId("score-stub");
    expect(score).not.toBeNull();
    expect(score!.disabled).toBe(false);
    await act(async () => score!.click());
    await act(async () => {
      vi.advanceTimersByTime(2000);
    });
    await flush();
    expect(api.patch).toHaveBeenCalledWith(
      `/v1/assessments/sheet-${MINE.id}-${ME}/competence-scores/c-1`,
      { score_value: 4, score_source: "manual" },
    );
  });

  // HRP-629 REDO (QA 09.10): not being on the round's evaluator list no
  // longer means an empty tab — the colleagues' sheets render read-only.
  it("shows the evaluators' sheets read-only on a round they do not evaluate", async () => {
    await render(["manager"], "view");
    await openTab(OTHER.id);
    const readonly = anyById("assessment-readonly-sheet-");
    expect(readonly).not.toBeNull();
    // The colleague's name heads their sheet.
    expect(readonly!.textContent).toContain("u-recruiter");
    const score = byId("score-stub");
    expect(score).not.toBeNull();
    expect(score!.disabled).toBe(true);
    await act(async () => score!.click());
    await flush();
    expect(api.patch).not.toHaveBeenCalled();
  });

  it("shows the same read-only sheets with a status badge once the round is closed", async () => {
    OTHER.status = "complete";
    try {
      await render(["manager"], "view");
      await openTab(OTHER.id);
      expect(anyById("assessment-readonly-sheet-")).not.toBeNull();
      expect(byId("score-stub")!.disabled).toBe(true);
      expect(byId("assessment-round-status-badge")).not.toBeNull();
      for (const id of WRITES) expect(anyById(id), id).toBeNull();
    } finally {
      OTHER.status = "in_progress";
    }
  });

  // HRP-630 (QA 06.10): the hiring manager at view, named an internal
  // evaluator on a round, gets the same exception as the manager - their
  // own sheet on that round and nothing else.
  it("lets a hiring manager at view fill in their own sheet and nothing else", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    await render(["hiring_manager"], "view");
    for (const tab of [MINE.id, OTHER.id]) {
      await openTab(tab);
      for (const id of WRITES) expect(anyById(id), `${tab}: ${id}`).toBeNull();
    }
    await openTab(OTHER.id);
    // HRP-629 REDO: the colleague's sheet reads, it does not take input.
    expect(byId("score-stub")!.disabled).toBe(true);
    await openTab(MINE.id);
    const score = byId("score-stub");
    expect(score!.disabled).toBe(false);
    await act(async () => score!.click());
    await act(async () => {
      vi.advanceTimersByTime(2000);
    });
    await flush();
    expect(api.patch).toHaveBeenCalledWith(
      `/v1/assessments/sheet-${MINE.id}-${ME}/competence-scores/c-1`,
      { score_value: 4, score_source: "manual" },
    );
  });

  it("keeps every write for whoever manages recruitment, a manager included", async () => {
    for (const who of [["recruiter"], ["manager"]]) {
      await render(who, "manage");
      await openTab(MINE.id);
      for (const id of [
        "assessment-round-kebab-",
        "assessment-round-new-btn",
        "assessment-add-evaluator-btn",
        "assessment-round-complete-btn",
        "invite-evaluator-modal-open",
      ])
        expect(anyById(id), `${who}: ${id}`).not.toBeNull();
    }
  });
});
