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

import {
  DemoFeedbackPopup,
  OPEN_DEMO_FEEDBACK_EVENT,
} from "@/components/dashboard/demo-feedback-popup";
import { submitFeedback } from "@/lib/api/feedback";

const DELAY = 5 * 60_000;

// jsdom's localStorage is unavailable under this vitest setup — same
// in-memory stub the sibling suites use.
function memoryStorage(map: Map<string, string>) {
  return {
    getItem: (k: string) => map.get(k) ?? null,
    setItem: (k: string, v: string) => void map.set(k, String(v)),
    removeItem: (k: string) => void map.delete(k),
    clear: () => map.clear(),
  };
}
const storage = new Map<string, string>();
const session = new Map<string, string>();
vi.stubGlobal("localStorage", memoryStorage(storage));
vi.stubGlobal("sessionStorage", memoryStorage(session));

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

function byTestId(id: string) {
  return document.querySelector(`[data-testid="${id}"]`);
}

function popup() {
  return byTestId("demo-feedback-popup");
}

function input(id: string) {
  return byTestId(id) as HTMLInputElement;
}

function type(el: HTMLInputElement | HTMLTextAreaElement, value: string) {
  const proto = Object.getPrototypeOf(el);
  act(() => {
    Object.getOwnPropertyDescriptor(proto, "value")!.set!.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

function openContact() {
  act(() => {
    window.dispatchEvent(new Event(OPEN_DEMO_FEEDBACK_EVENT));
  });
}

function click(id: string) {
  act(() => {
    (byTestId(id) as HTMLButtonElement).click();
  });
}

async function submit() {
  await act(async () => {
    (byTestId("demo-feedback-submit") as HTMLButtonElement).click();
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.mocked(submitFeedback).mockClear();
  storage.clear();
  session.clear();
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

describe("DemoFeedbackPopup on demand", () => {
  it("opens at once from the banner button, even after a dismissal", () => {
    storage.set("demo_feedback_done:t-demo", "1");
    mount();
    expect(popup()).toBeNull();
    act(() => {
      window.dispatchEvent(new Event(OPEN_DEMO_FEEDBACK_EVENT));
    });
    expect(popup()).not.toBeNull();
  });

  it("asks for contacts, not for a rating", () => {
    mount();
    act(() => {
      window.dispatchEvent(new Event(OPEN_DEMO_FEEDBACK_EVENT));
    });
    expect(byTestId("demo-feedback-rating-up")).toBeNull();
    expect(byTestId("demo-feedback-input-name")).not.toBeNull();
    expect(byTestId("demo-feedback-input-email")).not.toBeNull();
    // Off unless the site turns it on — the flagship has no phone field.
    expect(byTestId("demo-feedback-input-phone")).toBeNull();
    // Send stays clickable; the browser asks for the missing email.
    expect(
      (byTestId("demo-feedback-submit") as HTMLButtonElement).disabled,
    ).toBe(false);
    expect(input("demo-feedback-input-email").required).toBe(true);
  });

  it("offers a phone field where the site enables it", () => {
    window.__ENV__ = { NEXT_PUBLIC_DEMO_CONTACT_PHONE: "true" };
    try {
      mount();
      act(() => {
        window.dispatchEvent(new Event(OPEN_DEMO_FEEDBACK_EVENT));
      });
      // Either contact will do: a phone lifts the email requirement.
      type(input("demo-feedback-input-phone"), "+7 900 000-00-00");
      expect(input("demo-feedback-input-email").required).toBe(false);
    } finally {
      delete window.__ENV__;
    }
  });
});

describe("DemoFeedbackPopup after a call-back request", () => {
  it("still runs the survey, with the contacts filled in", async () => {
    mount();
    act(() => {
      window.dispatchEvent(new Event(OPEN_DEMO_FEEDBACK_EVENT));
    });
    type(input("demo-feedback-input-name"), "Anna");
    type(input("demo-feedback-input-email"), "anna@company.com");
    type(input("demo-feedback-input-message"), "A walkthrough, please");
    await act(async () => {
      (byTestId("demo-feedback-submit") as HTMLButtonElement).click();
    });
    expect(popup()).toBeNull();

    // A navigation remounts the layout — the contacts must survive it.
    act(() => root.unmount());
    root = createRoot(container);
    mount();
    act(() => {
      vi.advanceTimersByTime(DELAY);
    });

    expect(byTestId("demo-feedback-rating-up")).not.toBeNull();
    expect(input("demo-feedback-input-name").value).toBe("Anna");
    expect(input("demo-feedback-input-email").value).toBe("anna@company.com");
    // The comment went with the request; the survey asks its own.
    expect(input("demo-feedback-input-message").value).toBe("");
    // Carried-over contacts are not an answer: nothing to send yet.
    expect(
      (byTestId("demo-feedback-submit") as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it("brings the survey that fell due while the request was open", async () => {
    mount();
    openContact();
    act(() => {
      vi.advanceTimersByTime(DELAY);
    });
    // The request keeps the card while the visitor types.
    expect(byTestId("demo-feedback-rating-up")).toBeNull();
    type(input("demo-feedback-input-email"), "anna@company.com");
    await submit();
    expect(byTestId("demo-feedback-rating-up")).not.toBeNull();
  });

  it("leaves the survey's answers out of the request", async () => {
    mount();
    act(() => {
      vi.advanceTimersByTime(DELAY);
    });
    click("demo-feedback-rating-down");
    click("demo-feedback-clarity-no");
    openContact();
    type(input("demo-feedback-input-email"), "anna@company.com");
    await submit();
    expect(vi.mocked(submitFeedback).mock.calls[0][0]).toMatchObject({
      rating: null,
      clarity: null,
      contact_email: "anna@company.com",
    });
  });
});
