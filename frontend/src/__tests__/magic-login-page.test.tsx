// @vitest-environment jsdom
//
// HRP-1161: the link of the approval letter works once and the account was
// made with a random password, so its first entry sets one. The backend asks
// for it before it burns the link; the page shows the form and sends the
// same link again, with the password.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import { ApiError } from "@/lib/api";

// One router and one set of params for the whole run, as in the app: the
// page signs in from an effect that depends on them.
const { magicLogin, push, router, params } = vi.hoisted(() => {
  const push = vi.fn();
  return {
    magicLogin: vi.fn(),
    push,
    router: { push },
    params: new URLSearchParams("token=the-link"),
  };
});

vi.mock("next/navigation", () => ({
  useRouter: () => router,
  useSearchParams: () => params,
}));
vi.mock("@/lib/signup", () => ({ magicLogin }));
vi.mock("@/components/auth-logo", () => ({ AuthLogo: () => null }));

const { default: MagicLoginPage } = await import("@/app/(auth)/magic-login/page");

const SESSION = { access_token: "a", refresh_token: "r", token_type: "bearer", user: {} };
const asksForPassword = () =>
  Promise.reject(new ApiError(409, "Set a password", undefined, "magic_login_password_required"));

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  magicLogin.mockReset();
  push.mockReset();
  localStorage.clear();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

const byId = (id: string) => container.querySelector<HTMLElement>(`[data-testid="${id}"]`);

async function render() {
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <MagicLoginPage />
      </NextIntlClientProvider>,
    );
  });
}

async function type(testId: string, value: string) {
  const input = byId(testId) as HTMLInputElement;
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
  await act(async () => {
    set.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

const submit = () => act(async () => byId("magic-login-btn-submit")!.click());

it("signs in at once an account that already has its password", async () => {
  magicLogin.mockResolvedValue(SESSION);
  await render();

  expect(magicLogin).toHaveBeenCalledExactlyOnceWith("the-link", undefined);
  expect(byId("magic-login-input-password")).toBeNull();
  expect(localStorage.getItem("access_token")).toBe("a");
  expect(push).toHaveBeenCalledExactlyOnceWith("/dashboard");
});

it("asks a first entry for a password, then signs in with the same link", async () => {
  magicLogin.mockImplementationOnce(asksForPassword).mockResolvedValue(SESSION);
  await render();

  // Not an error: the form, and nobody is signed in yet.
  expect(byId("magic-login-error")).toBeNull();
  expect(container.textContent).toContain(enMessages.auth.createPasswordTitle);
  expect(push).not.toHaveBeenCalled();

  await type("magic-login-input-password", "a-password-of-my-own");
  await type("magic-login-input-confirm", "a-password-of-my-own");
  await submit();

  expect(magicLogin).toHaveBeenLastCalledWith("the-link", "a-password-of-my-own");
  expect(localStorage.getItem("refresh_token")).toBe("r");
  expect(push).toHaveBeenCalledExactlyOnceWith("/dashboard");
});

it("does not send a password that is too short or typed two ways", async () => {
  magicLogin.mockImplementationOnce(asksForPassword);
  await render();

  await type("magic-login-input-password", "a-password-of-my-own");
  await type("magic-login-input-confirm", "another-password");
  await submit();
  expect(byId("magic-login-error")!.textContent).toBe(enMessages.auth.passwordsDoNotMatch);

  await type("magic-login-input-password", "short");
  await type("magic-login-input-confirm", "short");
  await submit();
  expect(byId("magic-login-error")!.textContent).toBe(enMessages.auth.passwordTooShort);

  expect(magicLogin).toHaveBeenCalledTimes(1);
});

it("leaves the form for the error, with the way to a password, when the link stops working", async () => {
  magicLogin
    .mockImplementationOnce(asksForPassword)
    .mockRejectedValue(new ApiError(401, "Magic-login link is invalid or expired."));
  await render();

  await type("magic-login-input-password", "a-password-of-my-own");
  await type("magic-login-input-confirm", "a-password-of-my-own");
  await submit();

  expect(byId("magic-login-error")!.textContent).toBe("Magic-login link is invalid or expired.");
  expect(byId("magic-login-input-password")).toBeNull();
  expect(byId("magic-login-link-forgot")!.getAttribute("href")).toBe("/forgot-password");
  expect(byId("magic-login-link-signin")!.getAttribute("href")).toBe("/login");
  expect(push).not.toHaveBeenCalled();
});

it("says sign-in failed when the refusal comes without a message", async () => {
  // A rate limit answers 429 with no `detail`, and over HTTP/2 no status text.
  magicLogin.mockRejectedValue(new ApiError(429, ""));
  await render();

  expect(byId("magic-login-error")!.textContent).toBe(enMessages.auth.signInFailed);
  expect(container.textContent).toContain(enMessages.common.tryAgain);
});

it("leaves a long password whole: the server says when it is too long", async () => {
  magicLogin.mockImplementationOnce(asksForPassword);
  await render();

  // A cut-off paste would match in both fields and set a password nobody holds.
  expect(byId("magic-login-input-password")!.hasAttribute("maxlength")).toBe(false);
  expect(byId("magic-login-input-confirm")!.hasAttribute("maxlength")).toBe(false);
});
