// @vitest-environment jsdom
//
// HRP-676 — the "View as" switcher used to derive the active persona from
// the user's email domain, so any change to the demo email scheme silently
// marked the wrong button active. handleSwitch returns early on the persona
// it believes is already active, so the failure looked like a dead button:
// no request, no toast. The persona now comes from /auth/me, and these
// cases pin that the email is never consulted again.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import type { User } from "@/lib/types";

let user: Partial<User>;

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ user }),
}));

// Credits are a SaaS-only call; keeping this false skips the fetch.
vi.mock("@/hooks/use-is-saas", () => ({ useIsSaas: () => false }));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

const switchDemoPersona = vi.fn((persona: string) => Promise.resolve(persona));
vi.mock("@/lib/demo", () => ({
  switchDemoPersona: (persona: string) => switchDemoPersona(persona),
  saveDemoAccess: vi.fn(),
}));

const { DemoBanner } = await import("@/components/dashboard/demo-banner");

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
        <DemoBanner />
      </NextIntlClientProvider>,
    );
  });
}

function personaButton(persona: "admin" | "employee") {
  return document.querySelector<HTMLButtonElement>(
    `[data-testid="demo-banner-view-${persona}"]`,
  );
}

beforeEach(() => {
  switchDemoPersona.mockClear();
  storage.clear();
  user = {
    id: "u-1",
    first_name: "Carlos",
    // Deliberately the demo *admin* domain while the session is in the
    // employee persona: the switcher must follow the field, not the email.
    email: "demo-abc123@demo.hrpulsar.local",
    tenant_is_demo: true,
    tenant_expires_at: new Date(Date.now() + 3_600_000).toISOString(),
    demo_persona: "employee",
  };
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("DemoBanner persona switcher (HRP-676)", () => {
  it("sends the switch when the inactive persona is clicked", () => {
    mount();
    const admin = personaButton("admin");
    expect(admin).not.toBeNull();
    expect(admin!.disabled).toBe(false);

    act(() => admin!.click());
    expect(switchDemoPersona).toHaveBeenCalledWith("admin");
  });

  it("marks the persona from /auth/me as active, not the one in the email", () => {
    mount();
    // Employee is the active persona, so clicking it is a no-op...
    act(() => personaButton("employee")!.click());
    expect(switchDemoPersona).not.toHaveBeenCalled();
    // ...and the admin-domain email did not make Admin the active one.
    act(() => personaButton("admin")!.click());
    expect(switchDemoPersona).toHaveBeenCalledTimes(1);
  });

  it("renders no switcher when the session carries no persona", () => {
    user = { ...user, demo_persona: null };
    mount();
    expect(document.querySelector('[data-testid="demo-banner"]')).not.toBeNull();
    expect(personaButton("admin")).toBeNull();
  });
});
