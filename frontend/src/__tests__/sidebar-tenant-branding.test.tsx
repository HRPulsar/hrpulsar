// @vitest-environment jsdom
//
// HRP-808 — the platform admin can swap the site logo in the sidebar
// header for the tenant's own (initials + name when the tenant has no
// logo) and hide the version badge. The tenant switcher right below must
// not show the tenant a second time.

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "../../messages/en.json";
import type { User } from "@/lib/types";

const TENANT = { id: "t-1", name: "Acme Works", slug: "acme", roles: ["admin"] };
let user: Partial<User> = {};
let tenants = [TENANT];

vi.mock("next/navigation", () => ({
  usePathname: () => "/dashboard",
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("next-themes", () => ({
  useTheme: () => ({ resolvedTheme: "light" }),
}));

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ user, tenants, switchTenant: vi.fn() }),
}));

vi.mock("@/lib/ee-hooks", () => ({
  useEENavItems: () => ({ items: [], credits: null }),
}));

vi.mock("@/components/app-version", () => ({
  AppVersion: () => <span data-testid="version">v9.9.9</span>,
}));

const { Sidebar } = await import("@/components/sidebar");

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  tenants = [TENANT];
});

async function renderWith(branding: Partial<User>) {
  user = {
    id: "u-1",
    first_name: "Test",
    last_name: "User",
    roles: ["admin"],
    tenant_id: TENANT.id,
    tenant_name: TENANT.name,
    ...branding,
  };
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <Sidebar />
      </NextIntlClientProvider>,
    );
  });
}

const byTestId = (id: string) => container.querySelector(`[data-testid="${id}"]`);

describe("sidebar header branding (HRP-808)", () => {
  it("keeps the site logo, version and switcher by default", async () => {
    await renderWith({});
    expect(byTestId("sidebar-logo-platform")).not.toBeNull();
    expect(byTestId("sidebar-logo-tenant")).toBeNull();
    expect(byTestId("sidebar-tenant-mark")).toBeNull();
    expect(byTestId("version")).not.toBeNull();
    expect(byTestId("sidebar-tenant")?.textContent).toContain("AW");
  });

  it("shows the tenant logo instead of the site logo", async () => {
    await renderWith({
      tenant_hide_platform_logo: true,
      tenant_logo_url: "https://files/acme.png",
    });
    expect(byTestId("sidebar-logo-platform")).toBeNull();
    const logo = byTestId("sidebar-logo-tenant") as HTMLImageElement;
    expect(logo.getAttribute("src")).toBe("https://files/acme.png");
    expect(logo.getAttribute("alt")).toBe("Acme Works");
    expect(byTestId("version")).not.toBeNull();
    // Nothing to switch to: the static tenant block would only repeat the logo.
    expect(byTestId("sidebar-tenant")).toBeNull();
  });

  it("falls back to initials and name without a tenant logo", async () => {
    await renderWith({ tenant_hide_platform_logo: true, tenant_logo_url: null });
    expect(byTestId("sidebar-logo-platform")).toBeNull();
    expect(byTestId("sidebar-tenant-mark")?.textContent).toBe("AWAcme Works");
    expect(byTestId("sidebar-tenant")).toBeNull();
  });

  it("names the tenant even when the tenant list lacks it", async () => {
    // /auth/tenants lists verified accounts only; switch_tenant does not
    // require one.
    tenants = [];
    await renderWith({ tenant_hide_platform_logo: true, tenant_logo_url: null });
    expect(byTestId("sidebar-tenant-mark")?.textContent).toBe("AWAcme Works");
  });

  it("keeps the switcher without the initials when there is somewhere to switch", async () => {
    tenants = [TENANT, { id: "t-2", name: "Other Co", slug: "other", roles: ["hr"] }];
    await renderWith({ tenant_hide_platform_logo: true, tenant_logo_url: null });
    const switcher = byTestId("sidebar-tenant");
    expect(switcher).not.toBeNull();
    expect(switcher?.textContent).toContain("Acme Works");
    expect(switcher?.textContent).not.toContain("AW");
  });

  it("hides the version badge on its own flag", async () => {
    await renderWith({ tenant_hide_app_version: true });
    expect(byTestId("version")).toBeNull();
    expect(byTestId("sidebar-logo-platform")).not.toBeNull();
  });
});
