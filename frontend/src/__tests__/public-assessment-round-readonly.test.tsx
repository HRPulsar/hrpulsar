// @vitest-environment jsdom
//
// HRP-376 REDO — a submitted evaluator on a closed round gets a read-only
// sheet, whatever "Allow re-editing after submit" says. Before this, the
// page derived read-only from `allow_reediting` alone: on a completed
// round the form stayed editable and every click answered 409, so the
// evaluator collected "Failed to save — please retry" toasts instead of
// being told the round was closed.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";

let roundStatus = "in_progress";
let allowReediting = true;

const patch = vi.fn(() => Promise.resolve({}));

vi.mock("@/lib/api", () => {
  return {
    ApiError: class ApiError extends Error {},
    api: {
      get: vi.fn((path: string) => {
        if (path.endsWith("/resume-preview")) {
          return Promise.resolve({
            kind: "none",
            filename: null,
            mime_type: null,
            preview_url: null,
            download_url: null,
            blocks: [],
            truncated: false,
          });
        }
        return Promise.resolve({
          invite_id: "inv-1",
          status: "submitted",
          expires_at: new Date(Date.now() + 86_400_000).toISOString(),
          evaluator_name: "Ext Eval",
          allow_reediting: allowReediting,
          candidate_vacancy_id: "cv-1",
          round_id: "rd-1",
          assessment_id: "as-1",
          personal_message: null,
          consent_accepted: true,
          round_status: roundStatus,
          tenant_name: "Pulsar",
          candidate_name: "Jane Doe",
          vacancy_title: "QA Engineer",
          questions: [],
          recruiter_name: "Owner Name",
          recruiter_email: "owner@example.com",
          scale_levels: [
            { value: 1, label: "1 — Not suitable" },
            { value: 2, label: "2 — Below expectations" },
          ],
          competences: [
            {
              id: "comp-1",
              name: "Manual Testing",
              criticality: "critical",
              indicators: [],
            },
          ],
          critical_submit_threshold: 0.5,
          assessment: {
            id: "as-1",
            status: "submitted",
            final_notes: null,
            competence_scores: [],
            indicator_scores: [],
          },
        });
      }),
      post: vi.fn(() => Promise.resolve({})),
      patch,
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

function banner(): string {
  return (
    container.querySelector(
      '[data-testid="public-assessment-submitted-banner"]',
    )?.textContent ?? ""
  );
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

describe("public evaluation page — closed round is read-only", () => {
  it("completed round with re-editing on: read-only, no Submit, no PATCH", async () => {
    roundStatus = "completed";
    allowReediting = true;
    await mount();

    expect(banner()).toContain(enMessages.auth.evaluationCompletedReadOnlyNote);
    expect(
      container.querySelector('[data-testid="public-assessment-submit-btn"]'),
    ).toBeNull();

    // The whole point of the REDO: clicking an answer must not fire a
    // mutation that the backend will only reject with a toast.
    const radio = container.querySelector<HTMLInputElement>(
      '[data-testid^="assessment-competence-radio-"]',
    );
    // Fake timers only from here: anything the click schedules (the 1.5 s
    // autosave debounce) has to be given its chance to fire.
    vi.useFakeTimers();
    if (radio) {
      await act(async () => {
        radio.click();
        vi.advanceTimersByTime(5000);
      });
    }
    vi.useRealTimers();
    expect(patch).not.toHaveBeenCalled();
  });

  it("completed round with re-editing off names the round", async () => {
    roundStatus = "completed";
    allowReediting = false;
    await mount();

    expect(banner()).toContain(enMessages.auth.roundCompletedReadOnlyNote);
    expect(
      container.querySelector('[data-testid="public-assessment-submit-btn"]'),
    ).toBeNull();
  });

  it("archived round says archived", async () => {
    roundStatus = "archived";
    allowReediting = true;
    await mount();

    expect(banner()).toContain(enMessages.auth.evaluationArchivedReadOnlyNote);
    expect(
      container.querySelector('[data-testid="public-assessment-submit-btn"]'),
    ).toBeNull();
  });

  it("open round with re-editing on still offers the edit path", async () => {
    roundStatus = "in_progress";
    allowReediting = true;
    await mount();

    expect(
      container.querySelector('[data-testid="public-assessment-reedit-note"]'),
    ).not.toBeNull();
    expect(
      container.querySelector('[data-testid="public-assessment-submit-btn"]'),
    ).not.toBeNull();
  });
});
