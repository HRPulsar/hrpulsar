// @vitest-environment jsdom
//
// HRP-667 — the "post to the internal talent market" offer is shown to
// every recruitment viewer, but POST /talent-card is admin/recruiter
// only. The project rule (REDO checklist) is to show an action a role
// cannot take as disabled with the reason, never to let it 403.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import type { VacancyInternalCandidates } from "@/lib/recruitment-types";

const NOT_POSTED: VacancyInternalCandidates = {
  talent_card_id: null,
  talent_card_status: null,
  has_library_competences: true,
  internal_search_allowed: true,
  items: [],
};

let roles: string[] = [];
let payload: VacancyInternalCandidates = NOT_POSTED;

vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {},
  api: {
    get: vi.fn(() => Promise.resolve(payload)),
    post: vi.fn(() => Promise.resolve(payload)),
  },
}));

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ user: { roles } }),
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

const { InternalCandidatesBlock } = await import(
  "@/components/recruitment/internal-candidates-block"
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

async function render(
  withRoles: string[],
  data: VacancyInternalCandidates = NOT_POSTED,
) {
  roles = withRoles;
  payload = data;
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <InternalCandidatesBlock vacancyId="vac-1" />
      </NextIntlClientProvider>,
    );
  });
  await act(async () => {
    await Promise.resolve();
  });
}

const postButton = () =>
  container.querySelector(
    '[data-testid="vacancy-internal-candidates-post-btn"]',
  ) as HTMLButtonElement | null;

describe("Internal candidates offer — who may post (HRP-667)", () => {
  it("keeps the button live for a recruiter", async () => {
    await render(["recruiter"]);
    expect(postButton()!.disabled).toBe(false);
    expect(container.textContent).toContain(
      "Post this vacancy to the internal talent market",
    );
  });

  it("keeps the button live for an admin", async () => {
    await render(["admin"]);
    expect(postButton()!.disabled).toBe(false);
  });

  it("shows hr the button disabled with the reason, not a 403", async () => {
    await render(["hr"]);
    const btn = postButton();
    // Visible on purpose — hiding it would leave the role wondering why
    // colleagues see an action they do not.
    expect(btn).not.toBeNull();
    expect(btn!.disabled).toBe(true);
    expect(container.textContent).toContain(
      "Only an admin or a recruiter can post this vacancy",
    );
  });

  it("does the same for a hiring manager", async () => {
    await render(["hiring_manager"]);
    expect(postButton()!.disabled).toBe(true);
  });
});

describe("Internal search switch and manual picks (HRP-678 / HRP-693)", () => {
  it("disables the post button with its own reason when the switch is off", async () => {
    await render(["recruiter"], {
      ...NOT_POSTED,
      internal_search_allowed: false,
    });
    expect(postButton()!.disabled).toBe(true);
    // The recruiter set this themselves — name that reason, not the
    // competences one.
    expect(container.textContent).toContain(
      "Internal search is turned off for this vacancy",
    );
  });

  it("labels a manually added employee below the bar instead of a dash", async () => {
    await render(["recruiter"], {
      talent_card_id: "card-1",
      talent_card_status: "draft",
      has_library_competences: true,
      internal_search_allowed: true,
      items: [
        {
          employee_id: "emp-1",
          employee_name: "Ada Byron",
          position_title: "Engineer",
          match_score: null,
          status: "not_matched",
          candidate_id: null,
        },
        {
          employee_id: "emp-2",
          employee_name: "Grace Hopper",
          position_title: "Engineer",
          match_score: 84,
          status: "matched",
          candidate_id: null,
        },
      ],
    });
    const badge = container.querySelector(
      '[data-testid="vacancy-internal-candidate-manual-emp-1"]',
    );
    expect(badge).not.toBeNull();
    expect(badge!.textContent).toContain("Added manually");
    // The scored row keeps its percentage and gains no badge.
    expect(
      container.querySelector(
        '[data-testid="vacancy-internal-candidate-manual-emp-2"]',
      ),
    ).toBeNull();
    expect(container.textContent).toContain("84% match");
    // The unscored row carries the label and no percentage.
    const manualRow = container.querySelector(
      '[data-testid="vacancy-internal-candidate-emp-1"]',
    );
    expect(manualRow!.textContent).not.toContain("% match");
  });
});

// HRP-711 — the Add action on a shortlist row. Same rule as the offer
// above, one rung stricter: posting the vacancy is offered to everyone
// and disabled for most, but adding a candidate is an action only
// admin/recruiter have anywhere in recruitment, so the roles that cannot
// do it are not shown a button at all — there is nothing to explain.
const ROSTER = (candidateId: string | null): VacancyInternalCandidates => ({
  talent_card_id: "card-1",
  talent_card_status: "draft",
  has_library_competences: true,
  internal_search_allowed: true,
  items: [
    {
      employee_id: "emp-1",
      employee_name: "Ada Byron",
      position_title: "Engineer",
      match_score: 71,
      status: "matched",
      candidate_id: candidateId,
    },
  ],
});

const addButton = () =>
  container.querySelector(
    '[data-testid="vacancy-internal-candidate-emp-1-add-btn"]',
  ) as HTMLButtonElement | null;

const addedLink = () =>
  container.querySelector(
    '[data-testid="vacancy-internal-candidate-emp-1-added-link"]',
  );

describe("Add to candidates — who may do it (HRP-711)", () => {
  it("offers the action to a recruiter", async () => {
    await render(["recruiter"], ROSTER(null));
    expect(addButton()).not.toBeNull();
    expect(addButton()!.textContent).toContain("Add to candidates");
  });

  it("offers it to an admin", async () => {
    await render(["admin"], ROSTER(null));
    expect(addButton()).not.toBeNull();
  });

  it("hides it from hr and from a hiring manager", async () => {
    await render(["hr"], ROSTER(null));
    expect(addButton()).toBeNull();
    await render(["hiring_manager"], ROSTER(null));
    expect(addButton()).toBeNull();
  });

  it("links to the candidate once the employee is already in the pipeline", async () => {
    await render(["recruiter"], ROSTER("cand-9"));
    expect(addButton()).toBeNull();
    const link = addedLink();
    expect(link).not.toBeNull();
    expect(link!.textContent).toContain("In candidates");
    expect(link!.querySelector("a")?.getAttribute("href") ?? link!.getAttribute("href")).toBe(
      "/recruitment/candidates/cand-9",
    );
  });

  it("still shows the link to a role that may not add", async () => {
    await render(["hr"], ROSTER("cand-9"));
    expect(addedLink()).not.toBeNull();
  });
});
