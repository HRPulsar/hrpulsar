// @vitest-environment jsdom
//
// HRP-383 — the public evaluator page must tell an evaluator whose
// pre_interview slot was claimed by someone else what actually happened.
// The backend answers 409 on the context read; before this branch existed
// everything that was not a 410 fell through to "This link is invalid",
// which sent the evaluator back to the recruiter over a non-problem.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";

let getStatus = 409;

vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {},
  api: {
    get: vi.fn(() =>
      Promise.reject(
        Object.assign(new Error("conflict"), { status: getStatus }),
      ),
    ),
    post: vi.fn(() => Promise.resolve({})),
    patch: vi.fn(() => Promise.resolve({})),
  },
}));

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
  // The page defers its first load() through a zero-delay timeout.
  await act(async () => {
    vi.advanceTimersByTime(10);
    await Promise.resolve();
  });
}

beforeEach(() => {
  vi.useFakeTimers();
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

describe("public evaluation page — slot already taken", () => {
  it("renders the evaluator-facing page on 409", async () => {
    getStatus = 409;
    await mount();

    const page = container.querySelector(
      '[data-testid="public-error-slot-taken-page"]',
    );
    expect(page).not.toBeNull();
    // Copy comes from our own catalog, not from the backend message.
    expect(page?.textContent).toContain(enMessages.auth.slotTakenTitle);
    expect(page?.textContent).toContain(enMessages.auth.slotTakenBody);
    // The old behaviour — and the bug this pins — was the generic page.
    expect(
      container.querySelector('[data-testid="public-error-invalid-token-page"]'),
    ).toBeNull();
  });

  it("still shows the generic invalid page for other failures", async () => {
    getStatus = 500;
    await mount();

    expect(
      container.querySelector('[data-testid="public-error-invalid-token-page"]'),
    ).not.toBeNull();
    expect(
      container.querySelector('[data-testid="public-error-slot-taken-page"]'),
    ).toBeNull();
  });
});
