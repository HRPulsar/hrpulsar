// @vitest-environment jsdom
//
// HRP-985 (review B3): Whisper on the workspace's own server keeps the
// audio there. Platform providers take over only when the workspace
// switches it on, on that row, and the switch keeps the row's address.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";

const ROWS = [
  {
    id: "w1",
    provider: "whisper",
    api_key_masked: null,
    is_active: true,
    settings: { base_url: "http://whisper.lan/v1" },
    created_at: "",
    updated_at: "",
  },
  {
    id: "d1",
    provider: "deepgram",
    api_key_masked: "dg-…",
    is_active: true,
    settings: null,
    created_at: "",
    updated_at: "",
  },
];

const put = vi.fn<(...args: unknown[]) => Promise<unknown>>(() =>
  Promise.resolve({}),
);

vi.mock("@/lib/api", () => ({
  api: {
    get: vi.fn(() => Promise.resolve(ROWS)),
    put: (...args: unknown[]) => put(...args),
  },
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
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

let container: HTMLDivElement;
let root: Root;

beforeEach(async () => {
  put.mockClear();
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
  container.querySelector(`[data-testid="${id}"]`) as HTMLElement | null;

it("offers the switch on the Whisper server row only, off by default", () => {
  const box = byTestId("stt-checkbox-platform-fallback-w1");
  expect(box).not.toBeNull();
  expect(box!.getAttribute("aria-checked")).toBe("false");
  expect(byTestId("stt-checkbox-platform-fallback-d1")).toBeNull();
  expect(container.textContent).toContain(
    enMessages.recruitment.sttPlatformFallbackLabel,
  );
});

it("switching it on keeps the server address", async () => {
  await act(async () => {
    byTestId("stt-checkbox-platform-fallback-w1")!.click();
  });
  expect(put).toHaveBeenCalledWith(
    "/recruitment/settings/transcription-providers/w1",
    {
      settings: {
        base_url: "http://whisper.lan/v1",
        allow_platform_fallback: true,
      },
    },
  );
});
