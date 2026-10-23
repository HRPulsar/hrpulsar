// @vitest-environment jsdom
//
// HRP-667 — the "post to the internal talent market" offer. POST
// /talent-card is `manage` on recruitment (HRP-830) and needs the market
// open to the caller (HRP-824). HRP-629: whoever cannot post sees no offer
// at all - only the vacancy's candidates - until a card exists.

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
// HRP-824: the tenant's matrix opens the market to every role by default;
// HRP-830: the recruiter's row runs hiring.
const RUNS_HIRING = { "talent-market": "view", recruitment: "manage" };
const READS_HIRING = { "talent-market": "view", recruitment: "view" };
let sections: Record<string, string> = RUNS_HIRING;
let payload: VacancyInternalCandidates = NOT_POSTED;
// HRP-829 REDO: the ids GET /employees/card-access says the viewer may open.
let openCards: string[] = [];

vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {},
  api: {
    get: vi.fn((url: string) =>
      Promise.resolve(url.startsWith("/employees/card-access") ? openCards : payload),
    ),
    post: vi.fn(() => Promise.resolve(payload)),
  },
}));

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ user: { roles, sections } }),
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

const { InternalCandidatesBlock } = await import(
  "@/components/recruitment/internal-candidates-block"
);
const { resetCardAccess } = await import("@/components/employees/employee-name");

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  resetCardAccess();
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
  withSections: Record<string, string> = RUNS_HIRING,
) {
  roles = withRoles;
  sections = withSections;
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

  const offer = () =>
    container.querySelector('[data-testid="vacancy-internal-candidates-offer"]');

  it("shows no offer when the market is closed for the caller (HRP-824, HRP-629)", async () => {
    // The API refuses a posting into a section the tenant closed for the
    // recruiter's role.
    await render(["recruiter"], NOT_POSTED, { recruitment: "manage" });
    expect(offer()).toBeNull();
  });

  it("shows a view holder no offer, whatever the role (HRP-629)", async () => {
    // The rule is the right to post, not the role's name: a manager, hr or
    // a hiring manager at `view` sees just the vacancy's candidates - with
    // the switch off or no competences alike.
    for (const role of ["manager", "hr", "hiring_manager"]) {
      for (const data of [
        NOT_POSTED,
        { ...NOT_POSTED, internal_search_allowed: false },
        { ...NOT_POSTED, has_library_competences: false },
      ]) {
        await render([role], data, READS_HIRING);
        expect(offer(), role).toBeNull();
        expect(container.textContent).toBe("");
      }
    }
  });

  it("keeps the posted card's shortlist for a view holder (HRP-629 case 1)", async () => {
    await render(["manager"], ROSTER(null), READS_HIRING);
    expect(
      container.querySelector('[data-testid="vacancy-internal-candidates"]'),
    ).not.toBeNull();
    expect(
      container.querySelector(
        '[data-testid="vacancy-internal-candidates-card-link"]',
      ),
    ).not.toBeNull();
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

  // HRP-693 REDO (QA 20.10): no "added manually" label in any case - every
  // row reads the talent market's percentage, however it got on the list.
  it("shows every row's talent-market percentage and no manual label", async () => {
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
          match_score: 62,
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
    const row = (id: string) =>
      container.querySelector(`[data-testid="vacancy-internal-candidate-${id}"]`)!
        .textContent;
    // A manual pick below the bar and a matched row read the same way.
    expect(row("emp-1")).toContain("62% match");
    expect(row("emp-2")).toContain("84% match");
    expect(container.textContent).not.toContain("Added manually");
    expect(container.textContent).not.toContain("below the match bar");
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

  it("keeps offering it when the market is closed - it is recruitment's own write (HRP-824)", async () => {
    await render(["recruiter"], ROSTER(null), { recruitment: "manage" });
    expect(addButton()).not.toBeNull();
  });

  it("hides it from a view holder, whatever the role", async () => {
    await render(["hr"], ROSTER(null), READS_HIRING);
    expect(addButton()).toBeNull();
    await render(["hiring_manager"], ROSTER(null), READS_HIRING);
    expect(addButton()).toBeNull();
  });

  it("links to the candidate once the employee is already in the pipeline", async () => {
    await render(["recruiter"], ROSTER("cand-9"));
    expect(addButton()).toBeNull();
    const link = addedLink();
    expect(link).not.toBeNull();
    expect(link!.textContent).toContain("In candidates");
    expect(link!.querySelector("a")?.getAttribute("href") ?? link!.getAttribute("href")).toBe(
      // HRP-840: the link is on the vacancy page, so it carries the vacancy
      // context and Back on the card returns here.
      "/recruitment/candidates/cand-9?vacancyId=vac-1",
    );
  });

  it("still shows the link to a role that may not add", async () => {
    await render(["hr"], ROSTER("cand-9"), READS_HIRING);
    expect(addedLink()).not.toBeNull();
  });
});

// HRP-667 REDO — the name is a link to the employee's profile, but only
// for a viewer the API says may open it. The shortlist itself is the same
// for everyone who may read the vacancy (HRP-703); only the link is
// scoped, so nobody is offered a link that lands on a 403.
const NAMED = (canView: boolean): VacancyInternalCandidates => ({
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
      candidate_id: null,
      can_view_profile: canView,
    },
  ],
});

const nameCell = () =>
  container.querySelector('[data-testid="vacancy-internal-candidate-emp-1-name"]');

// HRP-829 REDO: whether the name links is the card rule's answer
// (GET /employees/card-access), not the row's `can_view_profile`.
async function renderNamed(canOpen: boolean, employees = "view") {
  openCards = canOpen ? ["emp-1"] : [];
  await render(["recruiter"], NAMED(!canOpen), { ...RUNS_HIRING, employees });
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 5));
  });
}

describe("Internal candidate name links (HRP-667)", () => {
  it("links the name when the viewer may open that profile", async () => {
    await renderNamed(true);
    const cell = nameCell();
    expect(cell).not.toBeNull();
    expect(cell!.tagName).toBe("A");
    expect(cell!.getAttribute("href")).toBe("/employees/emp-1");
    expect(cell!.textContent).toContain("Ada Byron");
  });

  it("renders plain text when they may not", async () => {
    await renderNamed(false);
    const cell = nameCell();
    expect(cell).not.toBeNull();
    expect(cell!.tagName).not.toBe("A");
    // The row itself is untouched — the shortlist is not narrowed.
    expect(cell!.textContent).toContain("Ada Byron");
  });

  it("is plain text with the employees section closed, unasked", async () => {
    const { api } = await import("@/lib/api");
    vi.mocked(api.get).mockClear();
    openCards = ["emp-1"];
    roles = ["recruiter"];
    payload = NAMED(true);
    await render(["recruiter"], NAMED(true), RUNS_HIRING);
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 5));
    });
    expect(nameCell()!.tagName).not.toBe("A");
    const urls = vi.mocked(api.get).mock.calls.map(([url]) => String(url));
    expect(urls.some((url) => url.startsWith("/employees/card-access"))).toBe(false);
  });
});
