// @vitest-environment jsdom
//
// The demo feedback card (HRP-587, HRP-1158, HRP-1160): a timer card for
// visitors who only browse, a card per value moment — once per kind —
// and the save-access block both carry until an email is left.

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
vi.mock("@/lib/demo", () => ({
  saveDemoAccess: vi.fn(() => Promise.resolve({})),
}));
vi.mock("@/lib/google-ads", () => ({ trackDemoConversion: vi.fn() }));
// Always-ready captcha so Send is live at once.
vi.mock("@/lib/turnstile", () => ({
  TURNSTILE_FAILED_MESSAGE_KEY: "turnstileFailed",
  useTurnstileGate: () => ({
    widget: null,
    token: "tok",
    isReady: true,
    failed: false,
    reset: vi.fn(),
  }),
}));

import {
  DEMO_SAVE_STATE_EVENT,
  DemoFeedbackPopup,
  OPEN_DEMO_FEEDBACK_EVENT,
} from "@/components/dashboard/demo-feedback-popup";
import { MUTATION_EVENT, type MutationEventDetail } from "@/lib/api";
import { submitFeedback } from "@/lib/api/feedback";
import { saveDemoAccess } from "@/lib/demo";

const DELAY = 60_000;
const MOMENT_DELAY = 1_500;

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
  return byTestId("demo-feedback-popup") as HTMLElement | null;
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

/** A successful request as `request()` reports it, then the card delay. */
function mutate(path: string, data: unknown = {}, method = "POST") {
  act(() => {
    window.dispatchEvent(
      new CustomEvent<MutationEventDetail>(MUTATION_EVENT, {
        detail: { method, path, status: 201, data },
      }),
    );
  });
  act(() => {
    vi.advanceTimersByTime(MOMENT_DELAY);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.mocked(submitFeedback).mockReset().mockResolvedValue(undefined);
  vi.mocked(saveDemoAccess).mockReset().mockResolvedValue({
    signup_request_id: "s",
    email: "e",
    status: "pending_email_verify",
  });
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

describe("timer card (HRP-587, HRP-1158)", () => {
  it("appears after a minute", () => {
    mount();
    act(() => {
      vi.advanceTimersByTime(DELAY - 1);
    });
    expect(popup()).toBeNull();
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(popup()?.dataset.context).toBe("survey");
  });

  it("keeps counting across remounts instead of restarting", () => {
    mount();
    act(() => {
      vi.advanceTimersByTime(40_000);
    });
    act(() => root.unmount());
    root = createRoot(container);
    mount();
    act(() => {
      vi.advanceTimersByTime(20_000);
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

  it("asks no sales contacts, only the save block", () => {
    mount();
    act(() => {
      vi.advanceTimersByTime(DELAY);
    });
    expect(byTestId("demo-feedback-rating-up")).not.toBeNull();
    expect(byTestId("demo-feedback-input-name")).toBeNull();
    expect(byTestId("demo-feedback-input-email")).toBeNull();
    expect(byTestId("demo-feedback-save-email")).not.toBeNull();
  });

  it("is not shown once a value moment happened", () => {
    mount();
    mutate("/pdp", { title: "Plan" });
    click("demo-feedback-dismiss");
    act(() => {
      vi.advanceTimersByTime(DELAY);
    });
    expect(popup()).toBeNull();
  });
});

describe("value moments (HRP-1158)", () => {
  it.each([
    ["/pdp", { title: "Q3 plan", assessment_id: null }, "pdp_created", "Your plan “Q3 plan”"],
    ["/pdp", { title: "Q3 plan", assessment_id: "a-1" }, "pdp_from_assessment", "Your plan “Q3 plan”"],
    ["/assessments", { employee_name: "Will Gapp" }, "assessment_created", "Your assessment: Will Gapp"],
    ["/assessment-groups", { title: "Q4 review" }, "assessment_created", "Your assessment: Q4 review"],
    ["/work/decomposition/sessions/s-1/apply", { created_steps: [] }, "decomposition_applied", "Your process breakdown"],
    ["/work/containers/c-1/gaps/hire-need", { id: "h-1" }, "hire_need_created", "Your hire need"],
  ])("%s gives its own card", (path, data, context, heading) => {
    mount();
    mutate(path, data);
    expect(popup()?.dataset.context).toBe(context);
    expect(byTestId("demo-feedback-heading")?.textContent).toBe(heading);
    expect(byTestId("demo-feedback-answer-partly")).not.toBeNull();
  });

  it.each([
    ["PATCH", "/pdp/p-1"],
    ["POST", "/pdp/p-1/comments"],
    ["POST", "/assessments/a-1/status"],
    ["POST", "/work/decomposition/sessions"],
  ])("ignores %s %s", (method, path) => {
    mount();
    mutate(path, {}, method);
    expect(popup()).toBeNull();
  });

  it("waits for the navigation that follows a create", () => {
    mount();
    act(() => {
      window.dispatchEvent(
        new CustomEvent(MUTATION_EVENT, {
          detail: { method: "POST", path: "/pdp", status: 201, data: {} },
        }),
      );
    });
    expect(popup()).toBeNull();
    act(() => {
      vi.advanceTimersByTime(MOMENT_DELAY);
    });
    expect(popup()).not.toBeNull();
  });

  it("asks once per kind", () => {
    mount();
    mutate("/pdp", { title: "One" });
    click("demo-feedback-dismiss");
    expect(storage.get("demo_feedback_done:t-demo:pdp_created")).toBe("1");
    mutate("/pdp", { title: "Two" });
    expect(popup()).toBeNull();
    // Another kind still asks.
    mutate("/assessments", { employee_name: "Will Gapp" });
    expect(popup()?.dataset.context).toBe("assessment_created");
  });

  it("replaces an open timer card and marks it shown", () => {
    mount();
    act(() => {
      vi.advanceTimersByTime(DELAY);
    });
    type(input("demo-feedback-input-message"), "typed on the survey");
    mutate("/pdp", { title: "Plan" });
    expect(popup()?.dataset.context).toBe("pdp_created");
    expect(input("demo-feedback-input-message").value).toBe("");
    expect(storage.get("demo_feedback_done:t-demo")).toBe("1");
  });

  it("an open moment keeps the slot; the other kind is not marked", () => {
    mount();
    mutate("/pdp", { title: "Plan" });
    mutate("/assessments", { employee_name: "Will Gapp" });
    expect(popup()?.dataset.context).toBe("pdp_created");
    click("demo-feedback-dismiss");
    expect(popup()).toBeNull();
    expect(storage.has("demo_feedback_done:t-demo:assessment_created")).toBe(false);
  });
});

describe("sending a moment card", () => {
  it("sends the answer with its context", async () => {
    mount();
    mutate("/pdp", { title: "Q3 plan", assessment_id: "a-1" });
    click("demo-feedback-answer-partly");
    type(input("demo-feedback-input-message"), "Deadlines are missing");
    await submit();
    expect(vi.mocked(submitFeedback).mock.calls[0][0]).toMatchObject({
      source: "demo",
      context: "pdp_from_assessment",
      context_title: "Q3 plan",
      answer: "partly",
      message: "Deadlines are missing",
      contact_email: null,
    });
    expect(saveDemoAccess).not.toHaveBeenCalled();
    expect(popup()).toBeNull();
    // Closed without an email: the banner may now remind.
    expect(storage.get("demo_save_skipped:t-demo")).toBe("1");
  });

  it("an email alone sends only save access, keeping the data", async () => {
    mount();
    mutate("/pdp", { title: "Plan" });
    type(input("demo-feedback-save-email"), "anna@company.com");
    await submit();
    expect(submitFeedback).not.toHaveBeenCalled();
    expect(vi.mocked(saveDemoAccess).mock.calls[0][0]).toMatchObject({
      email: "anna@company.com",
      first_name: null,
      keep_demo_data: true,
      turnstile_token: "tok",
    });
    expect(popup()).toBeNull();
    expect(storage.get("demo_saved:t-demo")).toBe("1");
    expect(storage.has("demo_save_skipped:t-demo")).toBe(false);
  });

  it("answer and email go together, tied in Slack by the email", async () => {
    mount();
    mutate("/assessments", { employee_name: "Will Gapp" });
    click("demo-feedback-answer-yes");
    type(input("demo-feedback-save-email"), "anna@company.com");
    type(input("demo-feedback-save-name"), "Anna");
    await submit();
    expect(vi.mocked(submitFeedback).mock.calls[0][0]).toMatchObject({
      answer: "yes",
      contact_email: "anna@company.com",
      contact_name: "Anna",
    });
    expect(vi.mocked(saveDemoAccess).mock.calls[0][0]).toMatchObject({
      first_name: "Anna",
    });
  });

  it("keeps the card on a half failure and retries only that half", async () => {
    vi.mocked(saveDemoAccess).mockRejectedValueOnce(new Error("Try again later"));
    mount();
    mutate("/pdp", { title: "Plan" });
    click("demo-feedback-answer-no");
    type(input("demo-feedback-save-email"), "anna@company.com");
    await submit();
    expect(popup()).not.toBeNull();
    expect(byTestId("demo-feedback-error")?.textContent).toContain("Try again later");

    await submit();
    expect(submitFeedback).toHaveBeenCalledTimes(1);
    expect(saveDemoAccess).toHaveBeenCalledTimes(2);
    expect(popup()).toBeNull();
  });

  it("drops the save block once an email was left anywhere", () => {
    mount();
    act(() => {
      storage.set("demo_saved:t-demo", "1");
      window.dispatchEvent(new Event(DEMO_SAVE_STATE_EVENT));
    });
    mutate("/pdp", { title: "Plan" });
    expect(popup()).not.toBeNull();
    expect(byTestId("demo-feedback-save")).toBeNull();
  });
});

describe("Talk to us (HRP-587)", () => {
  it("opens at once from the banner button, even after a dismissal", () => {
    storage.set("demo_feedback_done:t-demo", "1");
    mount();
    expect(popup()).toBeNull();
    act(() => {
      window.dispatchEvent(new Event(OPEN_DEMO_FEEDBACK_EVENT));
    });
    expect(popup()).not.toBeNull();
  });

  it("asks for contacts, not for a rating or a save", () => {
    mount();
    act(() => {
      window.dispatchEvent(new Event(OPEN_DEMO_FEEDBACK_EVENT));
    });
    expect(byTestId("demo-feedback-rating-up")).toBeNull();
    expect(byTestId("demo-feedback-save")).toBeNull();
    expect(byTestId("demo-feedback-input-name")).not.toBeNull();
    // Off unless the site turns it on — the flagship has no phone field.
    expect(byTestId("demo-feedback-input-phone")).toBeNull();
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

  it("never fills the save block of the card that follows", async () => {
    mount();
    act(() => {
      window.dispatchEvent(new Event(OPEN_DEMO_FEEDBACK_EVENT));
    });
    type(input("demo-feedback-input-email"), "anna@company.com");
    await submit();
    expect(vi.mocked(submitFeedback).mock.calls[0][0]).toMatchObject({
      contact_email: "anna@company.com",
    });
    mutate("/pdp", { title: "Plan" });
    expect(input("demo-feedback-save-email").value).toBe("");
  });

  it("a moment that comes meanwhile waits for the request to close", async () => {
    mount();
    act(() => {
      window.dispatchEvent(new Event(OPEN_DEMO_FEEDBACK_EVENT));
    });
    mutate("/pdp", { title: "Plan" });
    expect(popup()?.dataset.context).toBe("contact");
    click("demo-feedback-dismiss");
    expect(popup()?.dataset.context).toBe("pdp_created");
  });
});
