// @vitest-environment jsdom
//
// HRP-926: keeping a public check by email. The block on the result page
// needs the consent before it sends, keeps the marketing opt-in separate,
// sends the interface language (en/de, else en) and reads every answer of
// the API as its own sentence. The pages of the letters' links act on a
// button, not on load (mail scanners open links), and a dead link offers a
// fresh one; "my checks" lists, opens and deletes behind a confirmation.

import { NextIntlClientProvider } from "next-intl";
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import { ApiError } from "@/lib/api";
import type { CheckRead, CheckResult } from "@/lib/api/public-check";

const api = vi.hoisted(() => ({
  saveCheck: vi.fn(),
  requestLink: vi.fn(),
  confirmEmail: vi.fn(),
  unsubscribe: vi.fn(),
  listSaved: vi.fn(),
  getSaved: vi.fn(),
  deleteSaved: vi.fn(),
  getCheck: vi.fn(),
  createCheck: vi.fn(),
}));
const gate = vi.hoisted(() => ({
  widget: null,
  token: null as string | null,
  isReady: true,
  failed: false,
  reset: vi.fn(),
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));
vi.mock("@/lib/turnstile", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/turnstile")>()),
  useTurnstileGate: () => gate,
}));
vi.mock("@/lib/api/public-check", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/public-check")>()),
  ...api,
}));

const { SaveResults, PRIVACY_URL } = await import("@/components/public-check/save-results");
const { ResultView } = await import("@/components/public-check/result-view");
const { CheckResultPage } = await import("@/components/public-check/check-result");
const { CheckForm } = await import("@/components/public-check/check-form");
const pages = await import("@/components/public-check/saved-pages");

const t = enMessages.publicCheck;

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// jsdom's localStorage is unavailable under this vitest setup - the same
// in-memory stub the sibling suites use.
const stored = new Map<string, string>();
const storage = {
  getItem: (k: string) => stored.get(k) ?? null,
  setItem: (k: string, v: string) => void stored.set(k, String(v)),
  removeItem: (k: string) => void stored.delete(k),
  clear: () => stored.clear(),
};
vi.stubGlobal("localStorage", storage);
Element.prototype.scrollIntoView = vi.fn();

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  Object.assign(gate, { token: null, isReady: true, failed: false });
  gate.reset.mockReset();
  vi.restoreAllMocks();
  localStorage.clear();
  // This browser ran check tok-1: it holds the owner key.
  localStorage.setItem("public-check:owner:tok-1", "own-1");
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function render(node: ReactNode, locale = "en") {
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale={locale} messages={enMessages} timeZone="UTC">
        {node}
      </NextIntlClientProvider>,
    );
  });
}

const byId = <T extends HTMLElement = HTMLElement>(id: string) =>
  document.body.querySelector<T>(`[data-testid="${id}"]`);

async function fill(el: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
  await act(async () => {
    setter.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function click(el: HTMLElement | null) {
  await act(async () => {
    el!.click();
  });
}

async function settle() {
  await act(async () => {
    await Promise.resolve();
  });
}

const fail = (status: number, code?: string) => new ApiError(status, "x", undefined, code);
const TERM = "2026-10-12T10:00:00Z";

describe("the save block", () => {
  async function filled(locale = "en") {
    await render(<SaveResults token="tok-1" expiresAt={TERM} />, locale);
    await fill(byId<HTMLInputElement>("check-save-input-email")!, " visitor@example.com ");
  }

  it("says what is missing instead of sending without the consent or an email", async () => {
    await render(<SaveResults token="tok-1" expiresAt={TERM} />);
    const submit = byId<HTMLButtonElement>("check-save-btn-submit")!;
    expect(submit.disabled).toBe(false);
    await click(submit);
    expect(byId("check-save-error")!.textContent).toContain(t.saveErrorEmail);
    await fill(byId<HTMLInputElement>("check-save-input-email")!, "visitor@example.com");
    await click(submit);
    expect(byId("check-save-error")!.textContent).toContain(t.saveConsentRequired);
    expect(byId("check-save-consent")!.getAttribute("aria-invalid")).toBe("true");
    expect(api.saveCheck).not.toHaveBeenCalled();
  });

  it("links the privacy policy in a new tab", async () => {
    await render(<SaveResults token="tok-1" expiresAt={TERM} />);
    const link = byId<HTMLAnchorElement>("check-save-privacy-link")!;
    expect(link.href).toBe(PRIVACY_URL);
    expect(link.target).toBe("_blank");
  });

  it.each([
    ["en", false, "en"],
    ["de", true, "de"],
    ["ru", false, "en"],
  ])("sends the address, the consent and the %s interface's letter language", async (ui, marketing, sent) => {
    api.saveCheck.mockResolvedValue({ status: "confirm" });
    gate.token = "cf-token";
    await filled(ui);
    await click(byId("check-save-consent"));
    if (marketing) await click(byId("check-save-marketing"));
    await click(byId("check-save-btn-submit"));
    expect(api.saveCheck).toHaveBeenCalledWith("tok-1", {
      email: "visitor@example.com",
      consent: true,
      marketing,
      locale: sent,
      owner_key: "own-1",
      turnstile_token: "cf-token",
    });
    // Single-use captcha token: a second save needs a fresh one.
    expect(gate.reset).toHaveBeenCalled();
  });

  it("says to check the inbox, whatever the address", async () => {
    api.saveCheck.mockResolvedValue({ status: "confirm" });
    await filled();
    await click(byId("check-save-consent"));
    await click(byId("check-save-btn-submit"));
    expect(byId("check-save-sent")!.textContent).toBe(
      t.saveSent.replace("{email}", "visitor@example.com"),
    );
    expect(byId("check-save-input-email")).toBeNull();
  });

  it.each([
    [fail(429, "public_check_rate_limited"), t.saveErrorRateLimited],
    [fail(400, "public_check_captcha_failed"), t.errorCaptcha],
    [fail(404, "public_check_not_found"), t.saveErrorExpired],
    [fail(409, "public_check_already_saved"), t.saveErrorAlreadySaved],
    [fail(422), t.saveErrorEmail],
    [fail(500, "boom"), t.errorGeneric],
    [new TypeError("network"), t.errorGeneric],
  ])("reads a refusal as its own sentence (%#)", async (error, text) => {
    api.saveCheck.mockRejectedValue(error);
    await filled();
    await click(byId("check-save-consent"));
    await click(byId("check-save-btn-submit"));
    expect(byId("check-save-error")!.textContent).toContain(text);
    // The form stays for another try.
    expect(byId<HTMLButtonElement>("check-save-btn-submit")!.disabled).toBe(false);
  });

  function readyCheck(expires_at: string | null): { check: CheckRead; result: CheckResult } {
    const result: CheckResult = {
      schema_version: 1,
      preliminary: true,
      catalog_version: "1",
      shares: null,
      hours: { total: 0, moves: 0, to_review: 0, stays: 0, to_review_after: 0, freed: 0, unestimated: 0 },
      money: null,
      buckets: { moves: [], to_review: [], stays: [] },
      out_of_scope: [],
    };
    return {
      result,
      check: {
        status: "ready",
        phase: null,
        error_code: null,
        locale: "en",
        title: "Every month we close the books.",
        description: "Every month we close the books.",
        answers: {},
        created_at: "2026-10-02T10:00:00Z",
        expires_at,
        result,
      },
    };
  }

  it("sits on a result with a term, and not on one kept already", async () => {
    const { check, result } = readyCheck("2026-10-12T10:00:00Z");
    const save = { token: "tok-1" };
    await render(<ResultView check={check} result={result} inputHref="/" registerHref="/register" save={save} />);
    expect(byId("check-save")).not.toBeNull();
    const kept = readyCheck(null);
    await render(<ResultView check={kept.check} result={kept.result} inputHref="/" registerHref="/register" save={save} />);
    expect(byId("check-save")).toBeNull();
  });
});

describe("the owner key", () => {
  it("hides the save block in a browser without the key - a shared link", async () => {
    localStorage.clear();
    await render(<SaveResults token="tok-1" expiresAt={TERM} />);
    expect(byId("check-save")).toBeNull();
  });

  it("hides the block, and nothing else, when storage throws", async () => {
    vi.spyOn(storage, "getItem").mockImplementation(() => {
      throw new DOMException("denied", "SecurityError");
    });
    api.getCheck.mockResolvedValue({
      status: "ready",
      phase: null,
      error_code: null,
      locale: "en",
      description: "Every month we close the books.",
      answers: {},
      created_at: "2026-10-02T10:00:00Z",
      expires_at: TERM,
      result: {
        schema_version: 1,
        preliminary: true,
        catalog_version: "1",
        shares: null,
        hours: { total: 0, moves: 0, to_review: 0, stays: 0, to_review_after: 0, freed: 0, unestimated: 0 },
        money: null,
        buckets: { moves: [], to_review: [], stays: [] },
        out_of_scope: [],
      },
    });
    await render(
      <CheckResultPage token="tok-1" inputHref="/" resultBase="/r" registerHref="/register" shareUrl="https://check.hrpulsar.com/r/tok-1" />,
    );
    await settle();
    expect(byId("check-result")).not.toBeNull();
    expect(byId("check-save")).toBeNull();
  });

  it("is kept by the browser that created the check", async () => {
    api.createCheck.mockResolvedValue({ token: "tok-9", owner_key: "own-9", status: "pending", expires_at: TERM });
    await render(<CheckForm resultBase="/r" utm={null} />);
    const area = byId<HTMLTextAreaElement>("check-input-description")!;
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!;
    await act(async () => {
      setter.call(area, "Every month the accounting team closes the books.");
      area.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await click(byId("check-btn-submit"));
    expect(localStorage.getItem("public-check:owner:tok-9")).toBe("own-9");
  });

  it("is kept for the new check of a retry too", async () => {
    api.getCheck.mockResolvedValue({
      status: "error",
      phase: null,
      error_code: "overload",
      locale: "en",
      description: "Every month we close the books.",
      answers: {},
      created_at: "2026-10-02T10:00:00Z",
      expires_at: TERM,
      result: null,
    });
    api.createCheck.mockResolvedValue({ token: "tok-8", owner_key: "own-8", status: "pending", expires_at: TERM });
    await render(
      <CheckResultPage token="tok-1" inputHref="/" resultBase="/r" registerHref="/register" shareUrl="https://check.hrpulsar.com/r/tok-1" />,
    );
    await settle();
    await click(byId("check-btn-retry"));
    expect(localStorage.getItem("public-check:owner:tok-8")).toBe("own-8");
  });

  it("survives a storage that refuses to keep it", async () => {
    vi.spyOn(storage, "setItem").mockImplementation(() => {
      throw new DOMException("full", "QuotaExceededError");
    });
    const { rememberOwnerKey, ownerKeyFor } = await import("@/components/public-check/owner-key");
    expect(() => rememberOwnerKey("tok-7", "own-7")).not.toThrow();
    expect(ownerKeyFor("tok-7")).toBeNull();
  });
});

describe("the result page after a save", () => {
  it("keeps the term until the letter is clicked, and says to check the inbox", async () => {
    const result: CheckResult = {
      schema_version: 1,
      preliminary: true,
      catalog_version: "1",
      shares: null,
      hours: { total: 0, moves: 0, to_review: 0, stays: 0, to_review_after: 0, freed: 0, unestimated: 0 },
      money: null,
      buckets: { moves: [], to_review: [], stays: [] },
      out_of_scope: [],
    };
    api.getCheck.mockResolvedValue({
      status: "ready",
      phase: null,
      error_code: null,
      locale: "en",
      description: "Every month we close the books.",
      answers: {},
      created_at: "2026-10-02T10:00:00Z",
      expires_at: TERM,
      result,
    });
    api.saveCheck.mockResolvedValue({ status: "confirm" });
    await render(
      <CheckResultPage token="tok-1" inputHref="/" resultBase="/r" registerHref="/register" shareUrl="https://check.hrpulsar.com/r/tok-1" />,
    );
    await settle();
    expect(byId("check-result-expires")).not.toBeNull();
    await fill(byId<HTMLInputElement>("check-save-input-email")!, "visitor@example.com");
    await click(byId("check-save-consent"));
    await click(byId("check-save-btn-submit"));
    expect(byId("check-save-sent")).not.toBeNull();
    expect(byId("check-result-expires")).not.toBeNull();
  });
});

describe("the link request", () => {
  it("answers the same whatever the address", async () => {
    api.requestLink.mockResolvedValue({ status: "sent" });
    await render(<pages.MyChecksRequestPage />);
    await fill(byId<HTMLInputElement>("check-link-input-email")!, "someone@example.com");
    await click(byId("check-link-btn-submit"));
    expect(api.requestLink).toHaveBeenCalledWith({ email: "someone@example.com" });
    expect(byId("check-link-sent")!.textContent).toBe(t.linkSent);
  });

  it("reads a switched-off service as unavailable", async () => {
    api.requestLink.mockRejectedValue(fail(404, "public_check_not_found"));
    await render(<pages.MyChecksRequestPage />);
    await fill(byId<HTMLInputElement>("check-link-input-email")!, "someone@example.com");
    await click(byId("check-link-btn-submit"));
    expect(byId("check-link-error")!.textContent).toContain(t.errorUnavailable);
  });
});

describe("the confirmation page", () => {
  it("confirms on the button, not on load", async () => {
    api.confirmEmail.mockResolvedValue({ status: "confirmed" });
    await render(<pages.ConfirmEmailPage token="conf-1" myHref="/my" />);
    expect(api.confirmEmail).not.toHaveBeenCalled();
    await click(byId("check-confirm-btn"));
    expect(api.confirmEmail).toHaveBeenCalledWith("conf-1");
    expect(byId("check-confirm-done")).not.toBeNull();
    expect(byId("check-confirm-my-link")!.getAttribute("href")).toBe("/my");
  });

  it("offers a fresh link when this one is dead", async () => {
    api.confirmEmail.mockRejectedValue(fail(404, "public_check_link_invalid"));
    await render(<pages.ConfirmEmailPage token="old" myHref="/my" />);
    await click(byId("check-confirm-btn"));
    expect(byId("check-link-invalid")!.textContent).toContain(t.linkInvalidText);
    expect(byId("check-link-request")).not.toBeNull();
  });
});

describe("the unsubscribe page", () => {
  it("unsubscribes on the button", async () => {
    api.unsubscribe.mockResolvedValue({ status: "unsubscribed" });
    await render(<pages.UnsubscribePage token="u-1" />);
    expect(api.unsubscribe).not.toHaveBeenCalled();
    await click(byId("check-unsubscribe-btn"));
    expect(api.unsubscribe).toHaveBeenCalledWith("u-1");
    expect(byId("check-unsubscribe-done")!.textContent).toBe(t.unsubscribeDone);
  });

  it("says when the link is unknown", async () => {
    api.unsubscribe.mockRejectedValue(fail(404, "public_check_link_invalid"));
    await render(<pages.UnsubscribePage token="nope" />);
    await click(byId("check-unsubscribe-btn"));
    expect(byId("check-link-invalid")!.textContent).toContain(t.unsubscribeInvalidText);
  });
});

describe("my checks", () => {
  const list = {
    email: "visitor@example.com",
    checks: [
      {
        id: "c-2",
        created_at: "2026-10-02T10:00:00Z",
        title: "Close the month",
        status: "ready",
        share_moves: 42.4,
        expires_at: null,
      },
      {
        id: "c-1",
        created_at: "2026-10-01T10:00:00Z",
        title: "Hire a person",
        status: "error",
        share_moves: null,
        expires_at: null,
      },
    ],
  };

  async function open() {
    await render(
      <pages.SavedChecksPage
        token="m-1"
        myHref="/my"
        inputHref="/"
        moveRegisterHref="https://app.example/register?utm_source=public_check"
        moveImportHref="https://app.example/coverage/saved-checks"
      />,
    );
    await settle();
  }

  it("lists the checks, each opening through the same link", async () => {
    api.listSaved.mockResolvedValue(list);
    await open();
    expect(api.listSaved).toHaveBeenCalledWith("m-1");
    expect(byId("check-my")!.textContent).toContain("visitor@example.com");
    const items = [...document.querySelectorAll<HTMLElement>('[data-testid="check-my-item"]')];
    expect(items.map((li) => li.dataset.checkId)).toEqual(["c-2", "c-1"]);
    expect(items[0].querySelector("a")!.getAttribute("href")).toBe("/my/m-1/c-2");
    expect(items[0].textContent).toContain("42%");
    expect(items[0].textContent).toContain(t.statusReady);
    expect(items[1].textContent).toContain(t.statusError);
    expect(items[1].textContent).not.toContain("%");
  });

  it("says so when there is nothing", async () => {
    api.listSaved.mockResolvedValue({ email: "a@example.com", checks: [] });
    await open();
    expect(byId("check-my-empty")!.textContent).toBe(t.myEmpty);
  });

  it("offers a fresh link when this one is dead", async () => {
    api.listSaved.mockRejectedValue(fail(404, "public_check_link_invalid"));
    await open();
    expect(byId("check-link-invalid")).not.toBeNull();
  });

  it("deletes my data only after the confirmation", async () => {
    api.listSaved.mockResolvedValue(list);
    api.deleteSaved.mockResolvedValue(null);
    await open();
    await click(byId("check-my-btn-delete"));
    expect(api.deleteSaved).not.toHaveBeenCalled();
    expect(byId("check-my-delete-dialog")!.textContent).toContain(t.myDeleteText);
    await click(byId("check-my-delete-dialog-confirm"));
    expect(api.deleteSaved).toHaveBeenCalledWith("m-1");
    expect(byId("check-my-deleted")!.textContent).toContain(t.myDeletedText);
  });

  it("opens a ready result without the save block", async () => {
    api.getSaved.mockResolvedValue({
      status: "ready",
      phase: null,
      error_code: null,
      locale: "en",
      description: "Close the month.",
      answers: {},
      created_at: "2026-10-02T10:00:00Z",
      expires_at: null,
      result: {
        schema_version: 1,
        preliminary: true,
        catalog_version: "1",
        shares: null,
        hours: { total: 0, moves: 0, to_review: 0, stays: 0, to_review_after: 0, freed: 0, unestimated: 0 },
        money: null,
        buckets: { moves: [], to_review: [], stays: [] },
        out_of_scope: [],
      },
    });
    await render(
      <pages.SavedResultPage token="m-1" id="c-2" myHref="/my" inputHref="/" registerHref="/register" />,
    );
    await settle();
    expect(api.getSaved).toHaveBeenCalledWith("m-1", "c-2");
    expect(byId("check-result")).not.toBeNull();
    expect(byId("check-save")).toBeNull();
    expect(byId("check-saved-back")!.getAttribute("href")).toBe("/my/m-1");
  });

  it.each([
    ["public_check_not_found", "check-saved-not-found"],
    ["public_check_link_invalid", "check-link-invalid"],
  ])("tells a missing check (%s) from a dead link", async (code, testId) => {
    api.getSaved.mockRejectedValue(fail(404, code));
    await render(
      <pages.SavedResultPage token="m-1" id="c-9" myHref="/my" inputHref="/" registerHref="/register" />,
    );
    await settle();
    expect(byId(testId)).not.toBeNull();
    if (testId === "check-saved-not-found") {
      expect(byId(testId)!.textContent).toContain(t.savedNotFoundText);
      expect(byId("check-saved-back")!.getAttribute("href")).toBe("/my/m-1");
      expect(byId("check-link-request")).toBeNull();
    }
  });

  it("says a failed check failed", async () => {
    api.getSaved.mockResolvedValue({ status: "error", error_code: "overload", result: null });
    await render(
      <pages.SavedResultPage token="m-1" id="c-1" myHref="/my" inputHref="/" registerHref="/register" />,
    );
    await settle();
    expect(byId("check-saved-not-ready")!.textContent).toContain(t.runErrorOverload);
  });
});
