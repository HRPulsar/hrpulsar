// @vitest-environment jsdom
//
// HRP-924: the input page of the public process check. The description has
// the backend's limits and a counter, an example fills the field in one
// click, the optional answers and the UTM of the visit go into the request,
// the breakdown language follows the interface (en/de, else en), a created
// check moves straight to its result page, and every refusal of the HRP-923
// contract reads as its own sentence - a 422 also marks the field.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import { ApiError } from "@/lib/api";
import {
  DESCRIPTION_MIN,
  checkLocaleFor,
  utmFrom,
} from "@/lib/api/public-check";

const { createCheck, push, gate } = vi.hoisted(() => ({
  createCheck: vi.fn(),
  push: vi.fn(),
  // The captcha gate as the page sees it; the default is "no site key".
  gate: {
    widget: null,
    token: null as string | null,
    isReady: true,
    failed: false,
    reset: vi.fn(),
  },
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/turnstile", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/turnstile")>()),
  useTurnstileGate: () => gate,
}));
vi.mock("@/lib/api/public-check", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/public-check")>()),
  createCheck,
}));

const { CheckForm } = await import("@/components/public-check/check-form");

const t = enMessages.publicCheck;

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
Element.prototype.scrollIntoView = vi.fn();

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  createCheck.mockReset();
  push.mockReset();
  Object.assign(gate, { token: null, isReady: true, failed: false });
  gate.reset.mockReset();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function render(locale = "en", utm: Parameters<typeof CheckForm>[0]["utm"] = null) {
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale={locale} messages={enMessages} timeZone="UTC">
        <CheckForm resultBase="/r" utm={utm} />
      </NextIntlClientProvider>,
    );
  });
}

const byId = <T extends HTMLElement = HTMLElement>(id: string) =>
  container.querySelector<T>(`[data-testid="${id}"]`)!;

async function fill(el: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement, value: string) {
  const proto = Object.getPrototypeOf(el) as object;
  const setter = Object.getOwnPropertyDescriptor(proto, "value")!.set!;
  await act(async () => {
    setter.call(el, value);
    el.dispatchEvent(new Event(el instanceof HTMLSelectElement ? "change" : "input", { bubbles: true }));
  });
}

async function submit() {
  await act(async () => {
    byId("check-form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
}

const PROCESS = "Every month we close the books and send the reports to management.";

describe("the description", () => {
  it("cannot be sent below the backend's minimum and counts its characters", async () => {
    await render();
    const send = byId<HTMLButtonElement>("check-btn-submit");
    expect(send.disabled).toBe(true);
    expect(byId<HTMLTextAreaElement>("check-input-description").maxLength).toBe(4000);

    await fill(byId("check-input-description"), "x".repeat(DESCRIPTION_MIN - 1));
    expect(send.disabled).toBe(true);
    expect(byId("check-description-count").textContent).toBe("19 / 4,000");

    await fill(byId("check-input-description"), "x".repeat(DESCRIPTION_MIN));
    expect(send.disabled).toBe(false);
  });

  it("is filled by an example in one click", async () => {
    await render();
    await act(async () => byId("check-example-month-end-close").click());
    expect(byId<HTMLTextAreaElement>("check-input-description").value).toBe(
      t.exampleMonthEndCloseText,
    );
    expect(byId<HTMLButtonElement>("check-btn-submit").disabled).toBe(false);
  });
});

describe("sending a check", () => {
  it("sends the description, the answers and the UTM, then opens the result page", async () => {
    createCheck.mockResolvedValue({ token: "tok-9", status: "pending", expires_at: null });
    await render("de", { source: "linkedin", campaign: "hook_a" });

    await fill(byId("check-input-description"), `  ${PROCESS}  `);
    await fill(byId("check-input-industry"), " Logistics ");
    await fill(byId("check-input-team-size"), "12");
    await fill(byId("check-select-frequency"), "monthly");
    await fill(byId("check-input-hourly-rate"), "45.5");
    await fill(byId("check-select-currency"), "USD");
    await submit();

    expect(createCheck).toHaveBeenCalledWith({
      description: PROCESS,
      answers: {
        industry: "Logistics",
        team_size: 12,
        frequency: "monthly",
        hourly_rate: 45.5,
        currency: "USD",
      },
      locale: "de",
      utm: { source: "linkedin", campaign: "hook_a" },
    });
    // No captcha site key here: the token field is not sent at all.
    expect(createCheck.mock.calls[0][0]).not.toHaveProperty("turnstile_token");
    expect(push).toHaveBeenCalledWith("/r/tok-9");
  });

  it("leaves the unanswered questions empty, EUR by default", async () => {
    createCheck.mockResolvedValue({ token: "tok-1", status: "pending", expires_at: null });
    await render();
    await fill(byId("check-input-description"), PROCESS);
    await submit();
    expect(createCheck.mock.calls[0][0]).toMatchObject({
      answers: { industry: null, team_size: null, frequency: null, hourly_rate: null, currency: "EUR" },
      locale: "en",
      utm: null,
    });
  });

  it.each([
    ["public_check_rate_limited", 429, t.errorRateLimited],
    ["public_check_captcha_failed", 400, t.errorCaptcha],
    ["public_check_daily_limit", 429, t.errorDailyLimit],
    ["public_check_unavailable", 503, t.errorUnavailable],
    ["public_check_not_found", 404, t.errorUnavailable],
    ["something_new", 500, t.errorGeneric],
  ])("says %s in its own words", async (code, status, text) => {
    createCheck.mockRejectedValue(new ApiError(status, "x", "x", code));
    await render();
    await fill(byId("check-input-description"), PROCESS);
    await submit();
    expect(byId("check-error").textContent).toBe(text);
    expect(push).not.toHaveBeenCalled();
    expect(byId<HTMLButtonElement>("check-btn-submit").disabled).toBe(false);
  });

  it("marks the field a 422 names", async () => {
    createCheck.mockRejectedValue(
      new ApiError(422, "x", [{ loc: ["body", "answers", "team_size"], msg: "too big" }]),
    );
    await render();
    await fill(byId("check-input-description"), PROCESS);
    await submit();
    expect(byId("check-error").textContent).toBe(t.errorInvalid);
    expect(byId("check-input-team-size").getAttribute("aria-invalid")).toBe("true");
    expect(byId("check-input-description").hasAttribute("aria-invalid")).toBe(false);
  });

  it("states the description's limits on a 422 for it", async () => {
    createCheck.mockRejectedValue(
      new ApiError(422, "x", [{ loc: ["body", "description"], msg: "too short" }]),
    );
    await render();
    await fill(byId("check-input-description"), PROCESS);
    await submit();
    expect(byId("check-error").textContent).toBe(
      "The description must be between 20 and 4000 characters long.",
    );
    expect(byId("check-input-description").getAttribute("aria-invalid")).toBe("true");
  });
});

describe("the captcha (HRP-923 contract)", () => {
  it("sends the widget's token and resets it after a refusal", async () => {
    Object.assign(gate, { token: "cf-token", isReady: true });
    createCheck.mockRejectedValue(new ApiError(400, "x", "x", "public_check_captcha_failed"));
    await render();
    await fill(byId("check-input-description"), PROCESS);
    await submit();
    expect(createCheck.mock.calls[0][0].turnstile_token).toBe("cf-token");
    expect(byId("check-error").textContent).toBe(t.errorCaptcha);
    expect(gate.reset).toHaveBeenCalledTimes(1);
  });

  it("waits for the widget, and on its failure offers a retry instead of sending", async () => {
    Object.assign(gate, { isReady: false, failed: false });
    await render();
    await fill(byId("check-input-description"), PROCESS);
    expect(byId<HTMLButtonElement>("check-btn-submit").disabled).toBe(true);
    expect(byId("check-btn-submit").textContent).toBe(enMessages.auth.verifying);

    Object.assign(gate, { failed: true });
    await render();
    expect(byId("check-verify-error").textContent).toContain(enMessages.auth.turnstileFailed);
    await act(async () => byId("check-verify-retry").click());
    expect(gate.reset).toHaveBeenCalledTimes(1);
    await submit();
    expect(createCheck).not.toHaveBeenCalled();
  });
});

describe("request helpers", () => {
  it("breaks down in the interface language when the backend has it, else in English", () => {
    expect(checkLocaleFor("en")).toBe("en");
    expect(checkLocaleFor("de")).toBe("de");
    expect(checkLocaleFor("ru")).toBe("en");
  });

  it("takes the utm_* of the URL, first value, cut to the backend's limit", () => {
    expect(utmFrom({})).toBeNull();
    expect(utmFrom({ utm_source: " ", ref: "x" })).toBeNull();
    expect(
      utmFrom({
        utm_source: ["linkedin", "x"],
        utm_medium: "social",
        utm_campaign: "c".repeat(250),
        utm_id: "dropped",
      }),
    ).toEqual({ source: "linkedin", medium: "social", campaign: "c".repeat(200) });
  });
});
