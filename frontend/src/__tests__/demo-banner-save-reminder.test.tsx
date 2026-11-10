// @vitest-environment jsdom
//
// HRP-1160: the banner reminds a visitor with unsaved work to save it —
// after a change worth keeping and a card's save block closed without an
// email, never while a card is asking — and stops once an email is left.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import type { User } from "@/lib/types";

let user: Partial<User>;

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ user }) }));
vi.mock("@/hooks/use-is-saas", () => ({ useIsSaas: () => false }));
vi.mock("@/lib/google-ads", () => ({
  loadGoogleAds: vi.fn(),
  trackDemoConversion: vi.fn(),
}));
const saveDemoAccess = vi.fn();
vi.mock("@/lib/demo", () => ({
  saveDemoAccess: (...args: unknown[]) => saveDemoAccess(...args),
  switchDemoPersona: vi.fn(),
}));
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

const storage = new Map<string, string>();
vi.stubGlobal("localStorage", {
  getItem: (k: string) => storage.get(k) ?? null,
  setItem: (k: string, v: string) => void storage.set(k, String(v)),
  removeItem: (k: string) => void storage.delete(k),
  clear: () => storage.clear(),
});

const { DemoBanner } = await import("@/components/dashboard/demo-banner");
const { DEMO_SAVE_STATE_EVENT } = await import(
  "@/components/dashboard/demo-feedback-popup"
);
const { MUTATION_EVENT } = await import("@/lib/api");

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.clearAllMocks();
  storage.clear();
  user = {
    id: "u-1",
    tenant_id: "t-demo",
    tenant_is_demo: true,
    tenant_expires_at: new Date(Date.now() + 3_600_000).toISOString(),
  };
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

const byId = (id: string) =>
  document.querySelector<HTMLElement>(`[data-testid="${id}"]`);

function mount() {
  act(() => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <DemoBanner />
      </NextIntlClientProvider>,
    );
  });
}

function mutate(path: string, method = "POST") {
  act(() => {
    window.dispatchEvent(
      new CustomEvent(MUTATION_EVENT, {
        detail: { method, path, status: 200, data: {} },
      }),
    );
  });
}

function flag(key: string) {
  act(() => {
    storage.set(`${key}:t-demo`, "1");
    window.dispatchEvent(new Event(DEMO_SAVE_STATE_EVENT));
  });
}

const reminding = () =>
  byId("demo-banner-remaining")!.textContent!.startsWith("Your sandbox resets in");

it("reminds only after a change and a save block closed without an email", () => {
  mount();
  mutate("/pdp");
  // The card after that same action is still asking for the email.
  expect(reminding()).toBe(false);
  expect(byId("demo-banner-save-access")!.className).not.toContain("bg-brand");

  flag("demo_save_skipped");
  expect(reminding()).toBe(true);
  expect(byId("demo-banner-save-access")!.className).toContain("bg-brand");
  expect(byId("demo-banner-talk")!.className).not.toContain("bg-brand");
});

it("does not count the demo's own plumbing as a change", () => {
  mount();
  flag("demo_save_skipped");
  mutate("/demo/switch-view");
  mutate("/feedback");
  mutate("/auth/logout");
  expect(reminding()).toBe(false);
  mutate("/pdp/p-1", "PATCH");
  expect(reminding()).toBe(true);
});

it("keeps both flags across a reload", () => {
  storage.set("demo_mutated:t-demo", "1");
  storage.set("demo_save_skipped:t-demo", "1");
  mount();
  expect(reminding()).toBe(true);
});

it("stops once an email was left", () => {
  storage.set("demo_mutated:t-demo", "1");
  storage.set("demo_save_skipped:t-demo", "1");
  mount();
  flag("demo_saved");
  expect(reminding()).toBe(false);
});

it("an expired sandbox with a pending save waits for approval", () => {
  storage.set("demo_saved:t-demo", "1");
  user = { ...user, tenant_expires_at: new Date(Date.now() - 1000).toISOString() };
  mount();
  expect(byId("demo-banner-expired-saved")).not.toBeNull();
  expect(byId("demo-banner-expired")!.textContent).not.toContain("Create account");
});

it("the modal keeps the data by default and needs no name", async () => {
  saveDemoAccess.mockResolvedValue({});
  mount();
  act(() => byId("demo-banner-save-access")!.click());
  expect((byId("demo-save-access-keep-data") as HTMLInputElement).checked).toBe(true);
  const email = byId("demo-save-access-input-email") as HTMLInputElement;
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(
      email,
      "jane@example.com",
    );
    email.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => {
    byId("demo-save-access-submit")!.click();
  });
  expect(saveDemoAccess.mock.calls[0][0]).toMatchObject({
    email: "jane@example.com",
    first_name: null,
    keep_demo_data: true,
  });
  expect(storage.get("demo_saved:t-demo")).toBe("1");
});
