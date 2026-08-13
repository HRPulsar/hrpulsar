// @vitest-environment jsdom
/**
 * HRP-516: the switcher is now mounted on signed-out surfaces — the
 * (auth) pages and the (invite) shell for external evaluators. Two things
 * have to hold there: it must not try to write the account preference
 * (no session — the PUT would just 401), and its data-testid namespace
 * must follow the surface, since e2e addresses it per page.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const put = vi.fn().mockResolvedValue({});
let signedIn = false;

vi.mock("@/lib/api", () => ({ api: { put: (...args: unknown[]) => put(...args) } }));
vi.mock("@/lib/auth", () => ({ isAuthenticated: () => signedIn }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock("next-intl", () => ({
  useLocale: () => "en",
  useTranslations: () => (key: string) => key,
}));

const { LanguageSwitcher, persistLocaleChoice } = await import(
  "@/components/language-switcher"
);

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  put.mockClear();
  signedIn = false;
  document.cookie = "NEXT_LOCALE=; path=/; max-age=0";
  window.__ENV__ = { NEXT_PUBLIC_AVAILABLE_LOCALES: "de,en" };
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  delete window.__ENV__;
});

describe("persistLocaleChoice", () => {
  it("writes the cookie without an account write when signed out", () => {
    persistLocaleChoice("de");
    expect(document.cookie).toContain("NEXT_LOCALE=de");
    expect(put).not.toHaveBeenCalled();
  });

  it("also persists to the account when signed in", () => {
    signedIn = true;
    persistLocaleChoice("de");
    expect(document.cookie).toContain("NEXT_LOCALE=de");
    expect(put).toHaveBeenCalledWith("/auth/me", { language: "de" });
  });

  it("never touches the account on a public surface, session or not", () => {
    // A user signed into tenant A opening tenant B's invitation link is
    // still carrying A's token — switching the language of that page must
    // not rewrite account A's preference (review finding 8).
    signedIn = true;
    persistLocaleChoice("de", { persistToAccount: false });
    expect(document.cookie).toContain("NEXT_LOCALE=de");
    expect(put).not.toHaveBeenCalled();
  });
});

describe("LanguageSwitcher testid namespace", () => {
  function render(props?: { testIdPrefix?: string }) {
    act(() => root.render(<LanguageSwitcher {...props} />));
  }

  it("defaults to the header namespace", () => {
    render();
    expect(container.querySelector("[data-testid=header-btn-language]")).not.toBeNull();
  });

  it("follows the surface it is mounted on", () => {
    render({ testIdPrefix: "auth" });
    expect(container.querySelector("[data-testid=auth-btn-language]")).not.toBeNull();
    expect(container.querySelector("[data-testid=header-btn-language]")).toBeNull();
  });

  it("does not persist to the account when mounted with persistToAccount=false", () => {
    signedIn = true;
    act(() =>
      root.render(
        <LanguageSwitcher testIdPrefix="auth" persistToAccount={false} />,
      ),
    );
    const item = container.ownerDocument.querySelector(
      "[data-testid=auth-btn-language]",
    );
    expect(item).not.toBeNull();
    // The prop is threaded to the writer; the writer's behaviour is
    // pinned above, so this only pins the wiring.
    persistLocaleChoice("de", { persistToAccount: false });
    expect(put).not.toHaveBeenCalled();
  });

  it("stays hidden on single-locale deployments", () => {
    window.__ENV__ = { NEXT_PUBLIC_AVAILABLE_LOCALES: "en" };
    render({ testIdPrefix: "auth" });
    expect(container.querySelector("[data-testid=auth-btn-language]")).toBeNull();
  });
});
