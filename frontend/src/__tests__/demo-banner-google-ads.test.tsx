// @vitest-environment jsdom
//
// HRP-1052: the demo banner is the only surface that loads gtag.js, and the
// conversion fires on the target button — a successful "Save access" submit
// — never on a failed one, so Google Ads counts the same lead our own
// tracker (the signup request) just recorded.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import type { User } from "@/lib/types";

let user: Partial<User>;

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ user }) }));
vi.mock("@/hooks/use-is-saas", () => ({ useIsSaas: () => false }));
vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

const saveDemoAccess = vi.fn();
vi.mock("@/lib/demo", () => ({
  saveDemoAccess: (...args: unknown[]) => saveDemoAccess(...args),
  switchDemoPersona: vi.fn(),
}));

// Always-ready captcha so the submit button is live at once.
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

const loadGoogleAds = vi.fn();
const trackDemoConversion = vi.fn();
vi.mock("@/lib/google-ads", () => ({
  loadGoogleAds: () => loadGoogleAds(),
  trackDemoConversion: () => trackDemoConversion(),
}));

const { DemoBanner } = await import("@/components/dashboard/demo-banner");

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.clearAllMocks();
  user = {
    id: "u-1",
    email: "demo-abc@demo.hrpulsar.local",
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

async function submitSaveAccess() {
  mount();
  act(() => byId("demo-banner-save-access")!.click());
  const input = (id: string, value: string) => {
    const el = byId(id) as HTMLInputElement;
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!;
    setter.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  };
  act(() => {
    input("demo-save-access-input-email", "jane@example.com");
    const name = document.querySelector<HTMLInputElement>(
      'input[type="text"][required]',
    )!;
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!;
    setter.call(name, "Jane");
    name.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => {
    byId("demo-save-access-submit")!.click();
  });
}

it("loads gtag only for a demo session", () => {
  mount();
  expect(loadGoogleAds).toHaveBeenCalledTimes(1);

  act(() => root.unmount());
  loadGoogleAds.mockClear();
  user = { ...user, tenant_is_demo: false };
  root = createRoot(container);
  mount();
  expect(loadGoogleAds).not.toHaveBeenCalled();
});

it("fires the conversion on a successful Save access submit", async () => {
  saveDemoAccess.mockResolvedValue({});
  await submitSaveAccess();

  expect(saveDemoAccess).toHaveBeenCalledTimes(1);
  expect(trackDemoConversion).toHaveBeenCalledTimes(1);
});

it("reports no conversion when the submit fails", async () => {
  saveDemoAccess.mockRejectedValue(new Error("nope"));
  await submitSaveAccess();

  expect(saveDemoAccess).toHaveBeenCalledTimes(1);
  expect(trackDemoConversion).not.toHaveBeenCalled();
});
