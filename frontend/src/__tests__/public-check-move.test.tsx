// @vitest-environment jsdom
//
// HRP-927: saved public checks move into an HRPulsar workspace. "My checks"
// offers the move while a ready check is not moved yet - registration with
// the address for an address without an account, the import page of the app
// host with the list's link for one with an account. The import page moves
// on a button and says what came of it in the backend's words.

import { NextIntlClientProvider } from "next-intl";
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import { ApiError } from "@/lib/api";
import type { SavedChecks } from "@/lib/api/public-check";

const api = vi.hoisted(() => ({ listSaved: vi.fn(), moveSaved: vi.fn() }));
const router = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));
const query = vi.hoisted(() => ({ params: new URLSearchParams() }));
const auth = vi.hoisted(() => ({ login: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => router,
  useSearchParams: () => query.params,
}));
vi.mock("@/lib/auth", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/auth")>()),
  login: auth.login,
  isTenantSelection: () => false,
}));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));
vi.mock("@/components/require-section", () => ({
  RequireSection: ({ children }: { children: ReactNode }) => <>{children}</>,
}));
vi.mock("@/lib/turnstile", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/turnstile")>()),
  useTurnstileGate: () => ({ widget: null, token: null, isReady: true, failed: false, reset: vi.fn() }),
}));
vi.mock("@/lib/api/public-check", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/public-check")>()),
  ...api,
}));

const { SavedChecksPage } = await import("@/components/public-check/saved-pages");
const { default: ImportChecksPage } = await import("@/app/(dashboard)/coverage/saved-checks/page");
const { RequestAccessForm } = await import("@/app/(auth)/register/request-access-form");
const { SelfServeRegisterForm } = await import("@/app/(auth)/register/self-serve-register-form");
const { default: LoginPage } = await import("@/app/(auth)/login/page");

const t = enMessages.publicCheck;

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
Element.prototype.scrollIntoView = vi.fn();

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  router.replace.mockReset();
  router.push.mockReset();
  query.params = new URLSearchParams();
  window.history.replaceState(null, "", "/coverage/saved-checks");
  sessionStorage.clear();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function render(node: ReactNode) {
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages} timeZone="UTC">
        {node}
      </NextIntlClientProvider>,
    );
  });
  await act(async () => {
    await Promise.resolve();
  });
}

const byId = <T extends HTMLElement = HTMLElement>(id: string) =>
  document.body.querySelector<T>(`[data-testid="${id}"]`);

async function click(el: HTMLElement | null) {
  await act(async () => {
    el!.click();
  });
}

const REGISTER = "https://app.example/register?utm_source=public_check&utm_medium=my_checks";
const IMPORT = "https://app.example/coverage/saved-checks";

function list(overrides: Partial<SavedChecks> = {}, moved = [false, false]): SavedChecks {
  return {
    email: "visitor+1@example.com",
    account: false,
    checks: [
      {
        id: "c-2",
        created_at: "2026-10-02T10:00:00Z",
        title: "Close the month",
        status: "ready",
        share_moves: 42,
        expires_at: null,
        moved: moved[0],
      },
      {
        id: "c-1",
        created_at: "2026-10-01T10:00:00Z",
        title: "Hire a person",
        status: "ready",
        share_moves: null,
        expires_at: null,
        moved: moved[1],
      },
    ],
    ...overrides,
  };
}

async function openMyChecks(data: SavedChecks) {
  api.listSaved.mockResolvedValue(data);
  await render(
    <SavedChecksPage
      token="m/1"
      myHref="/my"
      inputHref="/"
      moveRegisterHref={REGISTER}
      moveImportHref={IMPORT}
    />,
  );
}

describe("move to HRPulsar on my checks", () => {
  it("registers with the address when it has no account", async () => {
    await openMyChecks(list());
    const link = byId<HTMLAnchorElement>("check-my-move-link")!;
    expect(link.getAttribute("href")).toBe(`${REGISTER}&email=visitor%2B1%40example.com`);
    expect(link.textContent).toBe(t.myMoveCta);
    expect(byId("check-my-move")!.textContent).toContain("visitor+1@example.com");
  });

  it("signs in to the import page with the list's link when it has one", async () => {
    await openMyChecks(list({ account: true }));
    // A bearer token: in the fragment, never in the query (logs, next=, Referer).
    expect(byId("check-my-move-link")!.getAttribute("href")).toBe(`${IMPORT}#link=m%2F1`);
  });

  it("marks a moved check and drops the offer once nothing is left to move", async () => {
    await openMyChecks(list({ account: true }, [true, false]));
    const items = [...document.querySelectorAll('[data-testid="check-my-item"]')];
    expect(items[0].textContent).toContain(t.statusMoved);
    expect(items[1].textContent).toContain(t.statusReady);
    expect(byId("check-my-move")).not.toBeNull();

    act(() => root.unmount());
    root = createRoot(container);
    await openMyChecks(list({ account: true }, [true, true]));
    expect(byId("check-my-move")).toBeNull();
  });

  it("offers nothing for checks that are not ready", async () => {
    const data = list();
    data.checks = data.checks.map((c) => ({ ...c, status: "error" as const }));
    await openMyChecks(data);
    expect(byId("check-my-move")).toBeNull();
  });
});

/** The move link of "my checks" lands with the list's link in the fragment. */
function openWithLink(link: string) {
  window.history.replaceState(null, "", `/coverage/saved-checks#link=${encodeURIComponent(link)}`);
}

describe("the import page", () => {
  it("takes the link from the fragment, drops it from the address and keeps it for a reload", async () => {
    openWithLink("m/1+x");
    api.moveSaved.mockResolvedValue({ moved: 1, skipped: 0 });
    await render(<ImportChecksPage />);
    expect(window.location.href).toBe(`${window.location.origin}/coverage/saved-checks`);

    // The reload: no fragment, the session still has it.
    act(() => root.unmount());
    root = createRoot(container);
    await render(<ImportChecksPage />);
    await click(byId("coverage-import-btn"));
    expect(api.moveSaved).toHaveBeenCalledWith("m/1+x");
  });

  it("ignores the link in the query", async () => {
    window.history.replaceState(null, "", "/coverage/saved-checks?link=m-1");
    await render(<ImportChecksPage />);
    expect(byId("coverage-import-error")!.textContent).toContain(t.importNoLink);
  });

  it("moves on the button and says how many", async () => {
    openWithLink("m-1");
    api.moveSaved.mockResolvedValue({ moved: 2, skipped: 0 });
    await render(<ImportChecksPage />);
    expect(api.moveSaved).not.toHaveBeenCalled();
    await click(byId("coverage-import-btn"));
    expect(api.moveSaved).toHaveBeenCalledWith("m-1");
    expect(byId("coverage-import-done")!.textContent).toContain(
      "2 checks became processes in Coverage.",
    );
    expect(byId("coverage-import-open")!.getAttribute("href")).toBe("/coverage");
  });

  it("says when there is nothing left to move", async () => {
    openWithLink("m-1");
    api.moveSaved.mockResolvedValue({ moved: 0, skipped: 0 });
    await render(<ImportChecksPage />);
    await click(byId("coverage-import-btn"));
    expect(byId("coverage-import-done")!.textContent).toContain(t.importNothing);
  });

  it("says how many checks could not be moved, and nothing about the rest being in already", async () => {
    openWithLink("m-1");
    api.moveSaved.mockResolvedValue({ moved: 1, skipped: 2 });
    await render(<ImportChecksPage />);
    await click(byId("coverage-import-btn"));
    expect(byId("coverage-import-done")!.textContent).toContain("1 check became a process in Coverage.");
    expect(byId("coverage-import-skipped")!.textContent).toBe(
      "2 checks could not be moved and stay in \u201cMy checks\u201d.",
    );

    act(() => root.unmount());
    root = createRoot(container);
    api.moveSaved.mockResolvedValue({ moved: 0, skipped: 1 });
    await render(<ImportChecksPage />);
    await click(byId("coverage-import-btn"));
    expect(byId("coverage-import-done")!.textContent).not.toContain(t.importNothing);
    expect(byId("coverage-import-skipped")!.textContent).toContain("1 check could not be moved");
  });

  it("shows the backend's refusal - another account - and stays on the button", async () => {
    openWithLink("m-1");
    api.moveSaved.mockRejectedValue(
      new ApiError(403, "Sign in with that address.", undefined, "public_check_move_wrong_account"),
    );
    await render(<ImportChecksPage />);
    await click(byId("coverage-import-btn"));
    expect(byId("coverage-import-error")!.textContent).toContain("Sign in with that address.");
    expect(byId("coverage-import-btn")).not.toBeNull();
    expect(byId("coverage-import-done")).toBeNull();
  });

  it("says what is missing without a link", async () => {
    await render(<ImportChecksPage />);
    expect(byId("coverage-import-error")!.textContent).toContain(t.importNoLink);
    expect(byId<HTMLButtonElement>("coverage-import-btn")!.disabled).toBe(true);
  });
});

describe("sign-in on the way to the import page", () => {
  it("hands the fragment the proxy's redirect kept back with next", async () => {
    // proxy: /coverage/saved-checks#link=m-1 -> /login?next=/coverage/saved-checks,
    // and the browser keeps the fragment over the redirect.
    window.history.replaceState(null, "", "/login?next=%2Fcoverage%2Fsaved-checks#link=m-1");
    query.params = new URLSearchParams({ next: "/coverage/saved-checks" });
    auth.login.mockResolvedValue({ access_token: "a" });
    await render(<LoginPage />);
    await act(async () => {
      byId("login-form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });
    expect(router.push).toHaveBeenCalledWith("/coverage/saved-checks#link=m-1");
  });
});

describe("the registration forms", () => {
  it("open with the address of the checks", async () => {
    await render(<RequestAccessForm defaultEmail="visitor@example.com" />);
    expect(byId<HTMLInputElement>("register-input-email")!.value).toBe("visitor@example.com");
    act(() => root.unmount());
    root = createRoot(container);
    await render(<SelfServeRegisterForm defaultEmail="visitor@example.com" />);
    expect(byId<HTMLInputElement>("register-input-email")!.value).toBe("visitor@example.com");
  });
});
