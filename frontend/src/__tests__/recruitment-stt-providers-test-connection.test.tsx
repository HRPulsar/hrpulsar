// @vitest-environment jsdom
//
// HRP-986 REDO: "Test connection" on the transcription providers page - the
// LLM page's button, posting to the row's own /test endpoint; a saved row of
// a provider the chain cannot run has nothing to test.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";

const post = vi.fn<(...args: unknown[]) => Promise<unknown>>(() =>
  Promise.resolve({ status: "ok" }),
);
const toastSuccess = vi.fn();
const toastError = vi.fn();

vi.mock("@/lib/api", () => ({
  api: {
    get: vi.fn(() =>
      Promise.resolve([
        {
          id: "row-dg",
          provider: "deepgram",
          api_key_masked: "dg-••••",
          is_active: true,
          settings: null,
          created_at: "2026-11-01T00:00:00Z",
          updated_at: "2026-11-01T00:00:00Z",
        },
        {
          id: "row-old",
          provider: "google",
          api_key_masked: null,
          is_active: false,
          settings: null,
          created_at: "2026-11-01T00:00:00Z",
          updated_at: "2026-11-01T00:00:00Z",
        },
      ]),
    ),
    post: (...args: unknown[]) => post(...args),
  },
}));
vi.mock("sonner", () => ({
  toast: {
    error: (msg: string) => toastError(msg),
    success: (msg: string) => toastSuccess(msg),
  },
}));
vi.mock("@/components/require-role", () => ({
  RequireRole: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock("@/components/recruitment", () => ({
  RecruitmentBreadcrumbs: () => null,
}));

const Page = (
  await import(
    "@/app/(dashboard)/recruitment/settings/transcription-providers/page"
  )
).default;

const rec = enMessages.recruitment;
let container: HTMLDivElement;
let root: Root;

beforeEach(async () => {
  post.mockClear();
  toastSuccess.mockClear();
  toastError.mockClear();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <Page />
      </NextIntlClientProvider>,
    );
  });
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

const byTestId = (id: string) =>
  container.querySelector<HTMLButtonElement>(`[data-testid="${id}"]`);

it("tests the row's own connection and says it works", async () => {
  const button = byTestId("stt-btn-test-row-dg")!;
  expect(button.textContent).toContain(rec.llmTestButton);

  await act(async () => {
    button.click();
  });

  expect(post).toHaveBeenCalledWith(
    "/recruitment/settings/transcription-providers/row-dg/test",
  );
  expect(toastSuccess).toHaveBeenCalledWith(rec.sttTestOk);
});

it("shows the backend's reason when the check fails", async () => {
  post.mockRejectedValueOnce(new Error("The provider rejected the API key."));

  await act(async () => {
    byTestId("stt-btn-test-row-dg")!.click();
  });

  expect(toastError).toHaveBeenCalledWith("The provider rejected the API key.");
  expect(toastSuccess).not.toHaveBeenCalled();
});

it("offers no check on a provider the chain cannot run", () => {
  expect(byTestId("stt-btn-test-row-old")).toBeNull();
});
