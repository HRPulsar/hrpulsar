// @vitest-environment jsdom
//
// HRP-371 REDO — nothing on the evaluator's page may open the resume file
// on its own. The pane used to render `<iframe src={ctx.resume_url}>`
// while the preview request was still in flight; a browser cannot render
// a .docx, so that iframe dropped the file into Downloads on first paint
// and again after every F5 — the duplicate "(1)" / "(2)" copies in the
// tester's screenshot. These tests pin the two shapes the pane may take:
// an extracted text preview, and the structured view of a resume that
// was typed in by hand (case 2, no file at all).

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";

type Preview = Record<string, unknown>;

let preview: Preview = {};
let releasePreview: (() => void) | null = null;

vi.mock("@/lib/api", () => {
  return {
    ApiError: class ApiError extends Error {},
    api: {
      get: vi.fn((path: string) => {
        if (path.endsWith("/resume-preview")) {
          // Held open on purpose: the window between the context landing
          // and the preview arriving is exactly when the old fallback
          // iframe painted and started the download.
          return new Promise((resolve) => {
            releasePreview = () => resolve(preview);
          });
        }
        return Promise.resolve({
          invite_id: "inv-1",
          status: "in_progress",
          expires_at: new Date(Date.now() + 86_400_000).toISOString(),
          evaluator_name: "Ext Eval",
          allow_reediting: true,
          candidate_vacancy_id: "cv-1",
          round_id: "rd-1",
          assessment_id: "as-1",
          personal_message: null,
          consent_accepted: true,
          round_status: "in_progress",
          tenant_name: "Pulsar",
          candidate_name: "Jane Doe",
          vacancy_title: "QA Engineer",
          // The field the old backend shipped and the pane fell back to.
          // A server that still sends it must not make the page open it.
          resume_url: "https://s3/raw-docx",
          resume_filename: "cv.docx",
          resume_mime_type: "application/docx",
          questions: [],
          recruiter_name: "Owner Name",
          recruiter_email: "owner@example.com",
          scale_levels: [],
          competences: [],
          critical_submit_threshold: 0.5,
          assessment: {
            id: "as-1",
            status: "draft",
            final_notes: null,
            competence_scores: [],
            indicator_scores: [],
          },
        });
      }),
      post: vi.fn(() => Promise.resolve({})),
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

async function settlePreview() {
  releasePreview?.();
  await settle();
}

/** Every URL the rendered page would fetch or navigate to on its own. */
function autoLoadedUrls(): string[] {
  return [...container.querySelectorAll("iframe, embed, object, img")].map(
    (el) => el.getAttribute("src") ?? el.getAttribute("data") ?? "",
  );
}

beforeEach(() => {
  releasePreview = null;
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

describe("public evaluation page — the resume never downloads itself", () => {
  it("loads no file URL while the preview is still in flight", async () => {
    preview = {
      kind: "text",
      filename: "cv.docx",
      mime_type: "application/docx",
      preview_url: null,
      download_url: "https://s3/signed-attachment",
      blocks: ["Jane Doe", "QA Lead at Acme"],
      parsed: null,
      truncated: false,
    };
    await mount();

    // The gap the bug lived in.
    expect(autoLoadedUrls()).toEqual([]);

    await settlePreview();

    // Text preview shows; the file itself is only behind the button.
    const pane = container.querySelector(
      '[data-testid="public-assessment-resume-preview"]',
    );
    expect(pane?.textContent).toContain("QA Lead at Acme");
    expect(autoLoadedUrls()).toEqual([]);
    const download = container.querySelector<HTMLAnchorElement>(
      '[data-testid="public-assessment-resume-download-btn"]',
    );
    expect(download?.getAttribute("href")).toBe("https://s3/signed-attachment");
  });

  it("renders a hand-entered resume with no download at all", async () => {
    preview = {
      kind: "parsed",
      filename: null,
      mime_type: null,
      preview_url: null,
      download_url: null,
      blocks: [],
      parsed: {
        summary: "Ten years of QA.",
        experience: ["QA Lead — Acme (2019 – now)"],
        education: ["TU — BSc (2015)"],
        skills: ["pytest", "Playwright"],
      },
      truncated: false,
    };
    await mount();
    await settlePreview();

    const pane = container.querySelector(
      '[data-testid="public-assessment-resume-parsed"]',
    );
    expect(pane).not.toBeNull();
    expect(pane?.textContent).toContain("Ten years of QA.");
    expect(pane?.textContent).toContain("QA Lead — Acme (2019 – now)");
    expect(pane?.textContent).toContain("pytest");
    // Nothing to download — the button must not be there at all.
    expect(
      container.querySelector(
        '[data-testid="public-assessment-resume-download-btn"]',
      ),
    ).toBeNull();
    expect(autoLoadedUrls()).toEqual([]);
  });

  it("keeps the inline frame for a pdf, which the browser can render", async () => {
    preview = {
      kind: "pdf",
      filename: "cv.pdf",
      mime_type: "application/pdf",
      preview_url: "https://s3/inline-pdf",
      download_url: "https://s3/signed-attachment",
      blocks: [],
      parsed: null,
      truncated: false,
    };
    await mount();
    expect(autoLoadedUrls()).toEqual([]);

    await settlePreview();
    expect(autoLoadedUrls()).toEqual(["https://s3/inline-pdf"]);
  });
});
