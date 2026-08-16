// @vitest-environment jsdom
//
// HRP-587 — the demo feedback popup's five-minute delay counts from the
// start of the demo session, not from the latest mount: reloads and
// route-group switches unmount the dashboard layout, and a restarting
// countdown meant the most engaged visitors never saw the prompt
// (review fix).

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ user: { tenant_id: "t-demo", tenant_is_demo: true } }),
}));
vi.mock("@/lib/api/feedback", () => ({
  submitFeedback: vi.fn(() => Promise.resolve()),
}));

import { DemoFeedbackPopup } from "@/components/dashboard/demo-feedback-popup";

const DELAY = 5 * 60_000;

// jsdom's localStorage is unavailable under this vitest setup — same
// in-memory stub the sibling suites use.
const storage = new Map<string, string>();
vi.stubGlobal("localStorage", {
  getItem: (k: string) => storage.get(k) ?? null,
  setItem: (k: string, v: string) => void storage.set(k, String(v)),
  removeItem: (k: string) => void storage.delete(k),
  clear: () => storage.clear(),
});

let container: HTMLDivElement;
let root: Root;

function mount() {
  act(() => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <DemoFeedbackPopup />
      </NextIntlClientProvider>,
    );
  });
}

function popup() {
  return document.querySelector('[data-testid="demo-feedback-popup"]');
}

beforeEach(() => {
  vi.useFakeTimers();
  storage.clear();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.useRealTimers();
});

describe("DemoFeedbackPopup delay (HRP-587)", () => {
  it("appears after the configured delay", () => {
    mount();
    expect(popup()).toBeNull();
    act(() => {
      vi.advanceTimersByTime(DELAY);
    });
    expect(popup()).not.toBeNull();
  });

  it("keeps counting across remounts instead of restarting", () => {
    mount();
    act(() => {
      vi.advanceTimersByTime(3 * 60_000);
    });
    act(() => root.unmount());
    root = createRoot(container);
    mount();
    // 3 minutes elapsed before the remount — only 2 more are owed.
    act(() => {
      vi.advanceTimersByTime(2 * 60_000);
    });
    expect(popup()).not.toBeNull();
  });

  it("never returns once answered or dismissed", () => {
    storage.set("demo_feedback_done:t-demo", "1");
    mount();
    act(() => {
      vi.advanceTimersByTime(DELAY * 2);
    });
    expect(popup()).toBeNull();
  });
});
