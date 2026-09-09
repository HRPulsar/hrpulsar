// @vitest-environment jsdom
//
// HRP-381 — every dead end on the external evaluation link gets its own
// page. Three different situations used to land on "This link is
// invalid. Please contact the recruiter who sent it.": a declined
// invitation, a candidate who is gone, and an archived vacancy. The page
// now routes on the backend's error *code*, not on substrings of a
// localized message — that match silently stopped working in German.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";

let failure: { status: number; code?: string; message: string } = {
  status: 410,
  message: "boom",
};

const post = vi.fn(() => Promise.resolve({}));

vi.mock("@/lib/api", () => {
  class ApiError extends Error {
    constructor(
      public status: number,
      message: string,
      public detail?: unknown,
      public code?: string,
    ) {
      super(message);
    }
  }
  return {
    ApiError,
    api: {
      get: vi.fn(() =>
        Promise.reject(
          new ApiError(
            failure.status,
            failure.message,
            undefined,
            failure.code,
          ),
        ),
      ),
      post,
      patch: vi.fn(() => Promise.resolve({})),
    },
  };
});

vi.mock("next/navigation", () => ({
  useParams: () => ({ token: "tok-123" }),
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

const PublicAssessmentPage = (
  await import("@/app/(invite)/public/assessments/[token]/page")
).default;

let container: HTMLDivElement;
let root: Root;

async function mount() {
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <PublicAssessmentPage />
      </NextIntlClientProvider>,
    );
  });
  await settle();
}

/** Wait for the page to finish loading.
 *
 * Real timers on purpose: building the competence rows hashes their names
 * through `crypto.subtle.digest`, which resolves on the real event loop —
 * flushing microtasks alone raced it and the sheet was still blank when
 * the assertions ran.
 */
async function settle() {
  for (let i = 0; i < 50; i += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 2));
    });
    if (
      container.querySelector("[data-testid^='public-assessment-']") ||
      container.querySelector("[data-testid^='public-error-']")
    ) {
      // One more turn so the follow-up request lands too.
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 2));
      });
      return;
    }
  }
}

function page(testid: string): HTMLElement | null {
  return container.querySelector(`[data-testid="${testid}"]`);
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.useRealTimers();
  vi.clearAllMocks();
});

describe("public evaluation page — error states", () => {
  it("a declined invitation says so on every later visit", async () => {
    failure = {
      status: 410,
      code: "invitation_declined",
      message: "This invitation was declined",
    };
    await mount();

    const declined = page("public-error-declined-page");
    expect(declined).not.toBeNull();
    expect(declined?.textContent).toContain(enMessages.auth.declinedTitle);
    expect(declined?.textContent).toContain(enMessages.auth.declinedBody);
    expect(page("public-error-invalid-token-page")).toBeNull();
  });

  it("a gone candidate names the candidate", async () => {
    failure = {
      status: 410,
      code: "candidate_no_longer_available",
      message: "Candidate is no longer available",
    };
    await mount();

    expect(page("public-error-candidate-gone-page")?.textContent).toContain(
      enMessages.auth.candidateGoneTitle,
    );
    expect(page("public-error-invalid-token-page")).toBeNull();
  });

  it("an archived vacancy names the vacancy", async () => {
    failure = {
      status: 410,
      code: "vacancy_no_longer_available",
      message: "The vacancy for this invitation is no longer available",
    };
    await mount();

    expect(page("public-error-vacancy-gone-page")?.textContent).toContain(
      enMessages.auth.vacancyGoneTitle,
    );
    expect(page("public-error-invalid-token-page")).toBeNull();
  });

  it("revoked and expired keep their pages, by code", async () => {
    failure = {
      status: 410,
      code: "invitation_revoked",
      // Deliberately not English: the old routing read the message text,
      // so a German backend answer fell through to the invalid page.
      message: "Diese Einladung wurde widerrufen",
    };
    await mount();
    expect(page("public-error-revoked-token-page")).not.toBeNull();

    act(() => root.unmount());
    container.remove();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    failure = {
      status: 410,
      code: "invitation_expired",
      message: "Diese Einladung ist abgelaufen",
    };
    await mount();
    expect(page("public-error-expired-token-page")).not.toBeNull();
  });

  it("an unknown token is still the generic invalid page", async () => {
    failure = {
      status: 410,
      code: "invalid_invite_link",
      message: "Invalid invite link",
    };
    await mount();
    expect(page("public-error-invalid-token-page")).not.toBeNull();
  });

  it("declining in the consent screen lands on the declined page", async () => {
    // Reach the consent screen first: context resolves, consent pending.
    const api = (await import("@/lib/api")).api as unknown as {
      get: ReturnType<typeof vi.fn>;
    };
    api.get.mockImplementationOnce(() =>
      Promise.resolve({
        invite_id: "inv-1",
        status: "pending",
        expires_at: new Date(Date.now() + 86_400_000).toISOString(),
        evaluator_name: "Ext Eval",
        allow_reediting: true,
        candidate_vacancy_id: "cv-1",
        round_id: "rd-1",
        assessment_id: null,
        personal_message: null,
        consent_accepted: false,
        tenant_name: "Pulsar",
      }),
    );
    await mount();
    const declineBtn = container.querySelector<HTMLButtonElement>(
      '[data-testid="public-assessment-consent-decline-btn"]',
    );
    expect(declineBtn).not.toBeNull();

    await act(async () => {
      declineBtn!.click();
    });
    await settle();

    expect(post).toHaveBeenCalled();
    expect(page("public-error-declined-page")).not.toBeNull();
    expect(page("public-error-invalid-token-page")).toBeNull();
  });
});
